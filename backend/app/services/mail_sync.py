"""信箱同步服務：抓信 → 現有 AI 判斷流程 → 只存判定結果。

觸發時機（決策 1 採「輪詢」）：
1. 使用者打開郵件分頁時，App 呼叫 POST /mail/sync 觸發一次
2. 背景排程每 MAIL_SYNC_INTERVAL_SECONDS 秒跑一次全體信箱
   （這一路才是「App 沒開也持續更新」的來源；`run_scheduled_sync_loop`）

單一信箱的同步流程：

    refresh_token（解密）→ 換短效 access_token
      → 列出 last_synced_at 之後的收件匣信件 ID
      → 濾掉已分析過的（provider_message_id 去重）
      → 逐封取回內容 → 依收信時間由新到舊排序
      → 逐封 RagService.detect() → 寫入 mail_analysis
      → 更新 last_synced_at

【為什麼排序要自己做】
分析順序以每封信自己的 received_at 為準，不倚賴提供者列表 API 的回傳順序：
Graph 有 `$orderby` 可指定，Gmail 的 `users.messages.list` 卻沒有排序參數，
順序屬未保證的行為。自己排才能讓兩家提供者一致，也才能保證封數多、跑不完
或中途失敗時，先判完的一定是最新、使用者最可能正在看的那幾封。

【為什麼判斷是「逐封序列」跑的】
偵測會打本機 Ollama 與 GPU 上的嵌入模型，同一台機器同時只服務得了一個請求；
更關鍵的是嵌入模型冷啟動時的併發競爭曾造成相似度全部塌成 ~1.0、每封信都被
判成高風險（見 RagService._ensure_ready_sync 的暖機修正）。這裡不做任何併發
加速，寧可慢——一次同步最多分析 MAIL_SYNC_MAX_MESSAGES 封，本來就有上限。

【失敗處理】
每封信的判定各自 commit，因此中途失敗不會丟掉已完成的部分；只有整批成功才
推進 last_synced_at，下次輪詢會把沒做完的重抓一次（去重保證不會重複分析）。

失敗分成兩級，差別在「要不要停用這個信箱連接」：

| 級別 | 例外 | 處理 |
|------|------|------|
| 確定失效 | `MailAuthRevokedError`（提供者回 invalid_grant）、`MailAuthExpiredError`（API 回 401） | 停用連接，等使用者重新授權 |
| 暫時失敗 | `MailOAuthError`、`MailFetchError`、`MailSyncError` | 只記 last_sync_error，下一輪自己重試 |

這個界線很重要：早期版本把所有 `MailOAuthError` 都當成授權失效，於是
Google 權杖端點一次 5xx、一次限流、或後端一次 DNS 抖動，就會把使用者的信箱
停用、逼他手動重跑完整 OAuth。排程每五分鐘打一次 Google，跑幾小時就有足夠
機會撞上一次——外部看起來就是「授權每隔幾小時自己失效」。
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import SecretDecryptError, decrypt_secret, encrypt_secret
from app.crud import crud_mail
from app.db.base import utcnow
from app.db.session import async_session_factory
from app.models.mail import MailAccount
from app.schemas.mail import MailSyncAccountResult
from app.services.mail_oauth import (
    MailAuthRevokedError,
    MailOAuthError,
    MailProviderNotConfiguredError,
    refresh_access_token,
)
from app.services.mail_provider import (
    MailAuthExpiredError,
    MailContent,
    MailFetchError,
    fetch_message_content,
    list_message_ids,
    normalize_sender_address,
)
from app.services.rag_service import RagService, RagUnavailableError, get_rag_service

logger = logging.getLogger(__name__)

# 全域同步鎖：確保同一時間只有一次同步在跑。
# 手動同步與排程同步共用此鎖，理由見模組說明的「逐封序列」——本地 LLM 與
# 嵌入模型都只有一份，讓兩路同步交錯進行只會讓兩邊都變慢，還可能重複分析。
_sync_lock = asyncio.Lock()


class MailSyncError(Exception):
    """同步過程中的失敗（已轉為對使用者可讀的訊息）。"""


# ------------------------------------------------------------
# 權杖
# ------------------------------------------------------------

async def get_access_token(db: AsyncSession, account: MailAccount) -> str:
    """解密 refresh_token 並換取短效 access_token。

    access_token 只活在記憶體裡，不落地——需要時再換一顆即可，
    存下來只會多一個可外洩的憑證。

    Microsoft 刷新時會輪替 refresh_token，回傳新值時必須立刻寫回資料庫，
    否則下一次同步會拿已作廢的舊權杖去換，導致連接無故失效。
    """
    try:
        refresh_token = decrypt_secret(account.refresh_token_encrypted)
    except SecretDecryptError as exc:
        raise MailSyncError(str(exc)) from exc

    tokens = await refresh_access_token(account.provider, refresh_token)
    if tokens.refresh_token and tokens.refresh_token != refresh_token:
        await crud_mail.update_refresh_token(
            db, account, encrypt_secret(tokens.refresh_token)
        )
    return tokens.access_token


# ------------------------------------------------------------
# 送進 AI 判斷的文字
# ------------------------------------------------------------

def build_detect_text(mail: MailContent) -> str:
    """把一封信整理成送進偵測流程的文字。

    寄件者與主旨一併帶入：詐騙信的破綻常常就在寄件者網域與主旨（冒名、
    偽造網域、聳動標題），只餵內文等於把最有辨識度的線索丟掉。
    長度截斷至 MAIL_DETECT_MAX_CHARS，對齊 RagDetectRequest 的上限。
    """
    lines: list[str] = []
    if mail.sender:
        lines.append(f"寄件者：{mail.sender}")
    if mail.subject:
        lines.append(f"主旨：{mail.subject}")
    if mail.body:
        lines.append("")
        lines.append(mail.body)
    return "\n".join(lines).strip()[: settings.MAIL_DETECT_MAX_CHARS]


# ------------------------------------------------------------
# 增量抓取的時間游標
# ------------------------------------------------------------

def resolve_sync_window(account: MailAccount, started_at: datetime) -> datetime:
    """算出這次要向提供者查詢的「起點時間」。

    三件事都在這裡處理，因為它們共同決定了「會不會漏信」：

    1. **沒有游標**（首次連接或剛重新授權）→ 回溯
       MAIL_SYNC_INITIAL_LOOKBACK_HOURS 小時。
    2. **游標比現在還晚** → 視為壞資料，退回回溯視窗。游標一旦跑到未來，
       「只抓比游標新的信」就永遠篩不到任何東西，症狀是同步安靜地回報
       fetched=0、error=null，看起來像「沒有新信」，實際上是整個信箱都不會再更新。
       伺服器時鐘被調過、或資料庫時間欄位被人工改過都會造成這種狀態，
       而它不會自己好——必須在讀取端擋掉。
    3. **正常游標** → 往回多退 MAIL_SYNC_OVERLAP_MINUTES 分鐘。提供者列出新信
       的動作不是即時一致的（Gmail 的搜尋索引尤其明顯），剛好落在
       「已送達、尚未可被列出」空窗的信，會因為游標推進而被永久跳過。
       重疊區間重複列出的信由 provider_message_id 去重擋掉，不會重複分析。
    """
    lookback = started_at - timedelta(hours=settings.MAIL_SYNC_INITIAL_LOOKBACK_HOURS)
    cursor = account.last_synced_at
    if cursor is None:
        return lookback
    if cursor > started_at:
        logger.warning(
            "信箱 %s 的 last_synced_at（%s）比現在（%s）還晚，改用回溯視窗重抓",
            account.id,
            cursor,
            started_at,
        )
        return lookback
    return cursor - timedelta(minutes=settings.MAIL_SYNC_OVERLAP_MINUTES)


# ------------------------------------------------------------
# 單一信箱同步
# ------------------------------------------------------------

async def sync_account(
    db: AsyncSession, account: MailAccount, rag: RagService
) -> MailSyncAccountResult:
    """同步單一信箱：抓新信、依收信時間由新到舊逐封判定、寫入結果。

    不會往外拋例外——所有失敗都收斂成回傳結果的 `error` 欄位，
    並記錄到 mail_accounts.last_sync_error，避免一個壞掉的信箱
    讓整輪排程中斷。
    """
    result = MailSyncAccountResult(
        account_id=account.id,
        provider=account.provider,
        email_address=account.email_address,
        fetched=0,
        analyzed=0,
        skipped=0,
    )

    # 以「開始同步的時間」作為下次的增量起點：同步期間新到的信不會被跳過
    started_at = utcnow()
    since = resolve_sync_window(account, started_at)
    result.synced_since = since

    try:
        access_token = await get_access_token(db, account)
        message_ids = await list_message_ids(
            account.provider,
            access_token,
            since=since,
            limit=settings.MAIL_SYNC_MAX_MESSAGES,
        )
    except MailProviderNotConfiguredError as exc:
        # 憑證被清掉／換環境沒設定：這是後端配置問題，不是使用者的授權出事，
        # 停用連接只會逼使用者白重連一次（設定補回來就會自己好）
        await crud_mail.mark_sync_error(db, account, str(exc))
        result.error = str(exc)
        return result
    except (MailAuthExpiredError, MailAuthRevokedError) as exc:
        # 授權「確定」失效（提供者回 invalid_grant 或 API 回 401）：
        # 停用此連接，等使用者重新連接
        message = f"信箱授權已失效，請重新連接：{exc}"
        await crud_mail.mark_sync_error(db, account, message, deactivate=True)
        result.error = message
        return result
    except (MailOAuthError, MailFetchError, MailSyncError) as exc:
        # 暫時性失敗（連不上 Google、5xx、限流、權杖解密失敗…）：
        # 只記錄錯誤，**不停用**。停用等於強迫使用者重跑一次完整 OAuth，
        # 而排程每 MAIL_SYNC_INTERVAL_SECONDS 就會自己再試一次。
        await crud_mail.mark_sync_error(db, account, str(exc))
        result.error = str(exc)
        return result

    result.fetched = len(message_ids)

    # 去重：輪詢一定會重複拿到同一批信，先問資料庫哪些已經分析過
    already_done = await crud_mail.existing_message_ids(db, account.id, message_ids)
    pending = [mid for mid in message_ids if mid not in already_done]
    result.skipped = len(message_ids) - len(pending)

    # 「同步成功但一封都沒抓到」是最難查的狀況（沒有錯誤訊息可看），
    # 把查詢區間一起記下來，才分得出「真的沒新信」與「游標壞掉」
    logger.info(
        "信箱 %s（%s）列出 %d 封（since=%s，游標=%s），其中 %d 封待分析",
        account.id,
        account.email_address,
        len(message_ids),
        since,
        account.last_synced_at,
        len(pending),
    )

    # 先把待分析的信全部取回，才有 received_at 可以排序（列表 API 只給 ID）。
    # 一次最多 MAIL_SYNC_MAX_MESSAGES 封，同時放在記憶體裡的量是有上限的；
    # 抓信只是 HTTP 往返，比後面每封都要跑一次的 AI 判斷便宜得多。
    fetched: list[tuple[str, MailContent]] = []
    for message_id in pending:
        try:
            mail = await fetch_message_content(
                account.provider, access_token, message_id
            )
        except MailAuthExpiredError as exc:
            message = f"信箱授權已失效，請重新連接：{exc}"
            await crud_mail.mark_sync_error(db, account, message, deactivate=True)
            result.error = message
            return result
        except MailFetchError as exc:
            # 單封抓失敗（信被刪除、暫時性錯誤）不影響其他信，下次輪詢會再試
            logger.warning(
                "取回信件失敗（帳號 %s，信件 %s）：%s", account.id, message_id, exc
            )
            continue
        # 以當初請求的 ID 為準：這是去重與唯一鍵的依據，不能讓提供者少回一個
        # id 欄位就寫進空字串
        fetched.append((message_id, mail))

    # 新到舊；收信時間相同時維持提供者的原始順序（Python 的排序是穩定的）
    fetched.sort(key=lambda item: item[1].received_at, reverse=True)

    # 已封鎖的寄件人：提供者端的過濾規則從建立到生效之間有空窗，這段期間的信
    # 還是會被列出來。使用者已經表態不想再看到這個人的信，就別再花一次 LLM
    # 判定，也別讓它出現在列表裡。
    blocked = await crud_mail.blocked_sender_addresses(db, account.id)

    for message_id, mail in fetched:
        if blocked and normalize_sender_address(mail.sender) in blocked:
            result.skipped += 1
            continue

        detect_text = build_detect_text(mail)
        if not detect_text:
            # 純附件或空信：沒有可判斷的文字，略過（下次輪詢仍會略過同一封）
            continue

        try:
            verdict = await rag.detect(detect_text)
        except RagUnavailableError as exc:
            # 模型／Ollama 不可用是整台機器層級的問題，繼續跑只是重複失敗
            message = f"AI 偵測服務不可用：{exc}"
            await crud_mail.mark_sync_error(db, account, message)
            result.error = message
            return result

        try:
            await crud_mail.create_analysis(
                db,
                user_id=account.user_id,
                mail_account_id=account.id,
                provider=account.provider,
                provider_message_id=message_id,
                received_at=mail.received_at,
                is_scam=verdict.is_scam,
                risk_level=verdict.risk_level,
                scam_type=verdict.scam_type,
                confidence=verdict.confidence,
                reasons=verdict.reasons,
                advice=verdict.advice,
                model=verdict.model,
            )
        except IntegrityError:
            # 另一路同步剛好搶先寫入同一封（唯一鍵擋下）——這正是唯一鍵的用途
            await db.rollback()
            result.skipped += 1
            continue

        result.analyzed += 1

    # 全程沒有中斷才推進增量起點；中途 return 的路徑都不會走到這裡
    await crud_mail.mark_sync_success(db, account, started_at)
    return result


# ------------------------------------------------------------
# 批次同步
# ------------------------------------------------------------

async def sync_user_accounts(
    db: AsyncSession, user_id: int, rag: RagService
) -> list[MailSyncAccountResult]:
    """同步某使用者所有生效中的信箱（App 打開郵件分頁時觸發）。"""
    accounts = await crud_mail.list_accounts(db, user_id, active_only=True)
    async with _sync_lock:
        return [await sync_account(db, account, rag) for account in accounts]


async def sync_all_accounts() -> list[MailSyncAccountResult]:
    """同步全系統生效中的信箱（背景排程用，自行開啟資料庫 Session）。"""
    rag = get_rag_service()
    results: list[MailSyncAccountResult] = []
    async with _sync_lock:
        async with async_session_factory() as db:
            accounts = await crud_mail.list_all_active_accounts(db)
            for account in accounts:
                results.append(await sync_account(db, account, rag))
    return results


# ------------------------------------------------------------
# 背景排程
# ------------------------------------------------------------

async def run_scheduled_sync_loop() -> None:
    """定期輪詢所有已連接信箱（由 app.main 的 lifespan 建立為背景工作）。

    先睡再跑：服務剛啟動時嵌入模型還沒載入，讓開機路徑保持乾淨。
    任何未預期的例外都只記錄不中斷迴圈——排程掛掉會讓「App 沒開也持續更新」
    這個功能靜默失效，比單輪失敗嚴重得多。
    """
    interval = settings.MAIL_SYNC_INTERVAL_SECONDS
    logger.info("信箱同步排程已啟動（每 %d 秒輪詢一次）", interval)

    while True:
        try:
            await asyncio.sleep(interval)
            results = await sync_all_accounts()
            analyzed = sum(item.analyzed for item in results)
            failed = [item for item in results if item.error]
            if results:
                logger.info(
                    "信箱輪詢完成：%d 個信箱、新判定 %d 封、失敗 %d 個",
                    len(results),
                    analyzed,
                    len(failed),
                )
            for item in failed:
                logger.warning(
                    "信箱同步失敗（%s / %s）：%s",
                    item.provider,
                    item.email_address,
                    item.error,
                )
        except asyncio.CancelledError:
            logger.info("信箱同步排程已停止")
            raise
        except Exception:
            logger.exception("信箱輪詢發生未預期的錯誤，將於下一輪重試")
