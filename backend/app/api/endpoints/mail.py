"""信箱連接端點（Gmail / Outlook 完整信件讀取）。

- GET    /mail/connect/{provider}    取得授權網址（App 用瀏覽器開啟）
- GET    /mail/callback/{provider}   OAuth 轉址回呼（提供者呼叫，無 JWT）
- GET    /mail/accounts              已連接的信箱列表
- DELETE /mail/accounts/{id}         中斷連接（連同判定紀錄一併刪除）
- POST   /mail/sync                  立即同步（打開郵件分頁時呼叫）
- GET    /mail/messages              已分析的信件列表
- GET    /mail/messages/{id}/content 單封信的完整內容（回報詐騙信時取用）

【資料落地原則】
判定結果存資料庫，信件內容不存。列表要顯示的主旨／寄件者／預覽是本次請求
即時向 Gmail API／Graph API 取回的（passthrough，只經過記憶體），
取不到時該三欄為 null，判定結果照常顯示。細節見 app/models/mail.py。
"""

import asyncio
import logging
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import settings
from app.core.crypto import encrypt_secret
from app.core.security import create_mail_oauth_state, decode_mail_oauth_state
from app.crud import crud_mail, crud_user
from app.db.base import utcnow
from app.models.mail import MailAccount, MailAnalysis
from app.schemas.mail import (
    MailAccountOut,
    MailAccountsResponse,
    MailBlockedSenderOut,
    MailBlockedSendersResponse,
    MailBlockSenderRequest,
    MailBlockSenderResponse,
    MailConnectResponse,
    MailDisconnectResponse,
    MailMessageContent,
    MailMessageItem,
    MailMessagesResponse,
    MailProvider,
    MailSyncResponse,
)
from app.schemas.phone import RiskLevel
from app.services import mail_sync
from app.services.mail_oauth import (
    MailAuthRevokedError,
    MailOAuthError,
    MailProviderNotConfiguredError,
    build_authorize_url,
    exchange_code,
    get_provider_config,
)
from app.services.mail_provider import (
    MailAuthExpiredError,
    MailFetchError,
    MailPermissionError,
    MailSummary,
    block_sender,
    fetch_account_email,
    fetch_message_content,
    fetch_message_summary,
    normalize_sender_address,
    unblock_sender,
)
from app.services.rag_service import RagService, get_rag_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mail", tags=["信箱連接"])


# ============================================================
# OAuth 授權
# ============================================================

@router.get(
    "/connect/{provider}",
    response_model=MailConnectResponse,
    summary="取得信箱授權網址",
    description=(
        "回傳 Google／Microsoft 官方授權網址，App 以瀏覽器或 Custom Tab 開啟。"
        "網址中的 state 為短效簽章權杖（綁定發起授權的使用者、可防 CSRF），"
        "逾時後需重新取得。授權完成後提供者會轉址回 `/mail/callback/{provider}`。"
    ),
)
async def connect_mailbox(
    provider: MailProvider, current_user: CurrentUser
) -> MailConnectResponse:
    state = create_mail_oauth_state(current_user.id, provider)
    try:
        authorize_url = build_authorize_url(provider, state)
    except MailProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    except MailOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )

    return MailConnectResponse(
        provider=provider,
        authorize_url=authorize_url,
        expires_in_minutes=settings.MAIL_OAUTH_STATE_EXPIRE_MINUTES,
    )


def _callback_page(title: str, message: str, status_code: int) -> HTMLResponse:
    """回傳授權結果頁（使用者此時人在瀏覽器，不能只丟 JSON 給他看）。"""
    html = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 64px auto;
                text-align: center; line-height: 1.8;">
      <h2>{title}</h2>
      <p>{message}</p>
      <p style="color: #888;">可以關閉這個視窗，回到 F.L.A.S.H. App。</p>
    </div>
    """
    return HTMLResponse(content=html, status_code=status_code)


@router.get(
    "/callback/{provider}",
    response_class=HTMLResponse,
    # 回應可能是結果頁或導回 App 的轉址，不套用回應模型
    response_model=None,
    include_in_schema=False,  # 由提供者轉址呼叫，不是給 App 直接打的端點
    summary="OAuth 授權回呼",
)
async def oauth_callback(
    provider: MailProvider,
    db: DbSession,
    code: Annotated[str | None, Query(description="授權碼")] = None,
    state: Annotated[str | None, Query(description="授權發起時簽發的 state")] = None,
    error: Annotated[str | None, Query(description="提供者回報的錯誤代碼")] = None,
) -> HTMLResponse | RedirectResponse:
    """處理提供者的授權回呼：驗證 state、換 refresh_token、加密存檔。"""
    display_name = get_provider_config(provider).display_name

    # 使用者在授權畫面按了「取消」
    if error:
        return _callback_page(
            "連接未完成", f"{display_name} 授權被取消或遭拒（{error}）。", 400
        )
    if not code or not state:
        return _callback_page("連接失敗", "授權回應缺少必要參數。", 400)

    # state 決定「這次授權屬於誰」，驗不過就不能繼續
    try:
        user_id, state_provider = decode_mail_oauth_state(state)
    except jwt.InvalidTokenError:
        return _callback_page(
            "連接失敗", "授權連結已過期或無效，請回到 App 重新點一次連接。", 400
        )
    if state_provider != provider:
        return _callback_page("連接失敗", "授權來源與請求的信箱類型不符。", 400)

    user = await crud_user.get_by_id(db, user_id)
    if user is None or not user.is_active:
        return _callback_page("連接失敗", "使用者不存在或已停用。", 403)

    # 換 refresh_token，並向提供者確認實際授權的信箱位址
    try:
        tokens = await exchange_code(provider, code)
        email_address = await fetch_account_email(provider, tokens.access_token)
    except (MailOAuthError, MailFetchError) as exc:
        logger.warning("信箱授權失敗（使用者 %s，%s）：%s", user_id, provider, exc)
        return _callback_page("連接失敗", f"{display_name} 授權處理失敗：{exc}", 502)

    await crud_mail.upsert_account(
        db,
        user_id=user_id,
        provider=provider,
        email_address=email_address,
        # refresh_token 絕不明碼落地
        refresh_token_encrypted=encrypt_secret(tokens.refresh_token or ""),
    )
    logger.info("使用者 %s 已連接 %s 信箱", user_id, provider)

    # 設定了深層連結就直接把使用者送回 App
    if settings.MAIL_OAUTH_SUCCESS_REDIRECT:
        return RedirectResponse(
            url=settings.MAIL_OAUTH_SUCCESS_REDIRECT,
            status_code=status.HTTP_302_FOUND,
        )
    return _callback_page(
        "連接成功", f"已成功連接 {display_name}：{email_address}", 200
    )


# ============================================================
# 已連接的信箱
# ============================================================

@router.get(
    "/accounts",
    response_model=MailAccountsResponse,
    summary="查詢已連接的信箱",
    description=(
        "列出目前使用者已連接的信箱。`last_sync_error` 不為 null 表示上次同步失敗；"
        "`is_active` 為 false 代表授權已失效，需要重新連接。"
    ),
)
async def list_mail_accounts(
    db: DbSession, current_user: CurrentUser
) -> MailAccountsResponse:
    accounts = await crud_mail.list_accounts(db, current_user.id)
    items = [MailAccountOut.model_validate(account) for account in accounts]
    return MailAccountsResponse(total=len(items), items=items)


@router.delete(
    "/accounts/{account_id}",
    response_model=MailDisconnectResponse,
    summary="中斷信箱連接",
    description=(
        "刪除該信箱連接：加密的 refresh_token 與所有判定紀錄一併移除，"
        "後端不再抓取這個信箱的信件。"
        "（提供者端的授權另需使用者自行到 Google／Microsoft 帳號設定移除。）"
    ),
)
async def disconnect_mail_account(
    account_id: int, db: DbSession, current_user: CurrentUser
) -> MailDisconnectResponse:
    account = await crud_mail.get_account(db, account_id, current_user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="找不到此信箱連接"
        )

    email_address = account.email_address
    deleted = await crud_mail.delete_account(db, account)
    return MailDisconnectResponse(
        message=f"已中斷 {email_address} 的連接",
        deleted_analyses=deleted,
    )


# ============================================================
# 需要即時呼叫提供者的端點：共用的取用與錯誤對應
# ============================================================

async def _require_active_account(
    db: AsyncSession, account_id: int, user_id: int
) -> MailAccount:
    """取出使用者自己、且仍在生效中的信箱連接。"""
    account = await crud_mail.get_account(db, account_id, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="找不到此信箱連接"
        )
    if not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="此信箱的授權已失效，請重新連接後再試",
        )
    return account


async def _access_token(db: AsyncSession, account: MailAccount) -> str:
    """換取 access_token，並把失敗轉成對 App 有意義的 HTTP 狀態。

    這裡刻意**不**動 is_active：停用信箱是同步流程（mail_sync.sync_account）的
    職責，讀取／設定端點順手停用，會讓使用者的信箱因為一次操作失敗而整個斷線。
    """
    try:
        return await mail_sync.get_access_token(db, account)
    except MailProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    except MailAuthRevokedError as exc:
        logger.info("信箱 %s 的授權已被撤銷：%s", account.id, exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="此信箱的授權已失效，請重新連接後再試",
        )
    except (MailOAuthError, mail_sync.MailSyncError) as exc:
        logger.warning("信箱 %s 換取 access_token 失敗：%s", account.id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"暫時無法與信箱提供者連線：{exc}",
        )


def _require_sender_address(raw: str) -> str:
    """自請求帶來的寄件人字串取出可用於封鎖的位址。"""
    address = normalize_sender_address(raw)
    if address is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="無法從寄件人欄位取出有效的信箱位址",
        )
    return address


# ============================================================
# 寄件人封鎖（提供者端「真封鎖」）
# ============================================================

@router.post(
    "/accounts/{account_id}/block-sender",
    response_model=MailBlockSenderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="封鎖寄件人",
    description=(
        "在 Gmail 端建立一條過濾規則，讓這個寄件人的信不再進收件匣"
        "（criteria.from = 該位址、action 移除 INBOX 標籤），"
        "並把封鎖紀錄存進資料庫。\n\n"
        "這是**提供者端**的封鎖，不是 App 自己把信藏起來：信不再進收件匣，"
        "後端的同步也就不會再列到、不會再耗一次 AI 判定。信件本身仍留在"
        "Gmail 的「所有郵件」，使用者事後查得到，不會遺失。\n\n"
        "`sender` 可直接傳信件列表拿到的 From 原文，後端會取出其中的位址。\n\n"
        "⚠ 需要 `gmail.settings.basic` 授權範圍。在後端加上這個 scope 之前"
        "連接的信箱，權杖不涵蓋此範圍，會回 403 並要求重新連接信箱。\n\n"
        "錯誤：403 授權範圍不足（請重新連接信箱）；404 找不到信箱連接；"
        "409 授權已失效或已封鎖過此寄件人；422 寄件人位址無法解析；"
        "501 該提供者尚未支援（目前僅 Gmail）；502 提供者暫時無法完成。"
    ),
)
async def block_mail_sender(
    account_id: int,
    body: MailBlockSenderRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> MailBlockSenderResponse:
    account = await _require_active_account(db, account_id, current_user.id)
    if account.provider != "gmail":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="目前僅 Gmail 支援寄件人封鎖",
        )

    sender_address = _require_sender_address(body.sender)
    if sender_address == account.email_address.lower():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="不能封鎖這個信箱自己的位址",
        )

    # 先擋重複：重複呼叫會在 Gmail 端堆出多條同樣的規則，而資料庫只留得住
    # 最後一條的 ID，先前那些就再也刪不掉了
    if await crud_mail.get_blocked_sender(db, account.id, sender_address):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"已經封鎖過 {sender_address}",
        )

    access_token = await _access_token(db, account)
    try:
        filter_id = await block_sender(account.provider, access_token, sender_address)
    except MailPermissionError as exc:
        logger.info("信箱 %s 缺少建立過濾規則的授權範圍：%s", account.id, exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "這個信箱連接的授權範圍不含「管理過濾規則」，無法在 Gmail 端封鎖。"
                "請重新連接一次信箱並同意所有權限。"
            ),
        )
    except MailAuthExpiredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="此信箱的授權已失效，請重新連接後再試",
        )
    except MailFetchError as exc:
        logger.warning("信箱 %s 建立封鎖規則失敗：%s", account.id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"封鎖失敗：{exc}"
        )

    # 規則已經建好才落地：反過來寫的話，Gmail 端建立失敗會留下一筆
    # 「以為封鎖了、其實沒有」的紀錄
    await crud_mail.upsert_blocked_sender(
        db,
        account_id=account.id,
        sender_address=sender_address,
        provider_filter_id=filter_id,
    )
    logger.info("信箱 %s 已封鎖寄件人 %s（filter %s）", account.id, sender_address, filter_id)

    return MailBlockSenderResponse(
        message=f"已封鎖 {sender_address}，之後這個寄件人的信不會再進收件匣",
        sender_address=sender_address,
    )


@router.get(
    "/accounts/{account_id}/blocked-senders",
    response_model=MailBlockedSendersResponse,
    summary="查詢封鎖名單",
    description="列出這個信箱目前封鎖了哪些寄件人（新到舊）。",
)
async def list_blocked_mail_senders(
    account_id: int, db: DbSession, current_user: CurrentUser
) -> MailBlockedSendersResponse:
    # 授權失效的信箱仍要查得到名單（純資料庫查詢，不呼叫提供者）
    account = await crud_mail.get_account(db, account_id, current_user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="找不到此信箱連接"
        )

    blocked = await crud_mail.list_blocked_senders(db, account.id)
    items = [MailBlockedSenderOut.model_validate(item) for item in blocked]
    return MailBlockedSendersResponse(total=len(items), items=items)


@router.delete(
    "/accounts/{account_id}/blocked-senders/{sender}",
    response_model=MailBlockSenderResponse,
    summary="解除封鎖寄件人",
    description=(
        "刪除 Gmail 端的過濾規則並移除封鎖紀錄，這個寄件人的信恢復進收件匣。\n\n"
        "提供者端規則已經不存在（例如使用者自己進 Gmail 設定刪過）時視為成功。"
    ),
)
async def unblock_mail_sender(
    account_id: int, sender: str, db: DbSession, current_user: CurrentUser
) -> MailBlockSenderResponse:
    account = await _require_active_account(db, account_id, current_user.id)
    sender_address = _require_sender_address(sender)

    blocked = await crud_mail.get_blocked_sender(db, account.id, sender_address)
    if blocked is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"沒有封鎖 {sender_address}",
        )

    if blocked.provider_filter_id:
        access_token = await _access_token(db, account)
        try:
            await unblock_sender(
                account.provider, access_token, blocked.provider_filter_id
            )
        except MailAuthExpiredError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="此信箱的授權已失效，請重新連接後再試",
            )
        except MailFetchError as exc:
            # 這裡不刪資料庫紀錄：Gmail 端規則還在，刪掉紀錄只會讓使用者
            # 以為解除了，實際上信照樣被擋，而且再也找不到那條規則的 ID
            logger.warning("信箱 %s 刪除封鎖規則失敗：%s", account.id, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=f"解除封鎖失敗：{exc}"
            )

    await crud_mail.delete_blocked_sender(db, blocked)
    logger.info("信箱 %s 已解除封鎖寄件人 %s", account.id, sender_address)

    return MailBlockSenderResponse(
        message=f"已解除封鎖 {sender_address}",
        sender_address=sender_address,
    )


# ============================================================
# 同步與讀取
# ============================================================

@router.post(
    "/sync",
    response_model=MailSyncResponse,
    summary="立即同步信箱",
    description=(
        "抓取上次同步之後的新信並逐封做 AI 判斷，只把判定結果存進資料庫。"
        "App 打開郵件分頁時呼叫；背景排程（MAIL_SYNC_INTERVAL_SECONDS）"
        "會另外定期執行同一段流程，所以 App 沒開也會持續更新。\n\n"
        "本地 LLM 同時只服務得了一個請求，判斷是逐封序列執行的，"
        "封數多時這個請求會跑上數十秒；同一時間全系統只會有一次同步在跑。"
    ),
)
async def sync_mailboxes(
    db: DbSession,
    current_user: CurrentUser,
    rag: Annotated[RagService, Depends(get_rag_service)],
) -> MailSyncResponse:
    results = await mail_sync.sync_user_accounts(db, current_user.id, rag)
    return MailSyncResponse(synced_at=utcnow(), accounts=results)


async def _load_summaries(
    db: AsyncSession,
    accounts: dict[int, MailAccount],
    analyses: list[MailAnalysis],
) -> dict[str, MailSummary]:
    """即時向提供者取回這批信件的主旨／寄件者／預覽（passthrough）。

    回傳以「mail_account_id:message_id」為鍵的對照表；取不到的信件不會出現在
    表中，呼叫端據此把顯示欄位留空。任何失敗都只記錄日誌不往外拋——顯示欄位
    拿不到是可接受的降級，判定結果才是這個端點的主體。
    """
    summaries: dict[str, MailSummary] = {}
    semaphore = asyncio.Semaphore(settings.MAIL_PREVIEW_CONCURRENCY)

    # 依信箱分組：一個信箱只需換一次 access_token
    by_account: dict[int, list[str]] = {}
    for analysis in analyses:
        by_account.setdefault(analysis.mail_account_id, []).append(
            analysis.provider_message_id
        )

    for account_id, message_ids in by_account.items():
        account = accounts.get(account_id)
        if account is None or not account.is_active:
            continue

        try:
            access_token = await mail_sync.get_access_token(db, account)
        except (MailOAuthError, mail_sync.MailSyncError) as exc:
            logger.warning("取回信件摘要失敗（信箱 %s）：%s", account_id, exc)
            continue

        # account／access_token 以預設引數綁定當次迴圈的值（gather 在本輪就會等完，
        # 但綁定後讀起來不必再去推敲閉包捕捉的是哪一輪）
        async def load(
            message_id: str,
            account: MailAccount = account,
            access_token: str = access_token,
        ) -> None:
            async with semaphore:
                try:
                    summary = await fetch_message_summary(
                        account.provider, access_token, message_id
                    )
                except MailFetchError as exc:
                    logger.debug(
                        "取回信件摘要失敗（信箱 %s，信件 %s）：%s",
                        account.id,
                        message_id,
                        exc,
                    )
                    return
                summaries[f"{account.id}:{message_id}"] = summary

        await asyncio.gather(*(load(message_id) for message_id in message_ids))

    return summaries


@router.get(
    "/messages",
    response_model=MailMessagesResponse,
    summary="查詢已分析的信件",
    description=(
        "回傳目前使用者信箱中已完成 AI 判斷的信件，依收信時間新到舊。\n\n"
        "風險等級、判定理由與建議來自資料庫；主旨、寄件者與預覽片段"
        "不儲存於資料庫，而是本次請求即時向 Gmail API／Graph API 取回"
        "（取不到時為 null，`preview_available` 為 false）。"
        "只要判定結果、不需要顯示欄位時，帶 `include_preview=false` 可省下這段往返。"
    ),
)
async def list_mail_messages(
    db: DbSession,
    current_user: CurrentUser,
    risk_level: Annotated[
        RiskLevel | None, Query(description="只回傳指定風險等級的信件")
    ] = None,
    include_preview: Annotated[
        bool, Query(description="是否即時取回主旨／寄件者／預覽")
    ] = True,
    limit: Annotated[int, Query(ge=1, le=100, description="每頁筆數")] = 20,
    offset: Annotated[int, Query(ge=0, description="略過筆數")] = 0,
) -> MailMessagesResponse:
    total, analyses = await crud_mail.list_analyses(
        db, current_user.id, risk_level=risk_level, limit=limit, offset=offset
    )

    accounts = {
        account.id: account
        for account in await crud_mail.list_accounts(db, current_user.id)
    }
    summaries: dict[str, MailSummary] = {}
    if include_preview and analyses:
        summaries = await _load_summaries(db, accounts, analyses)

    items: list[MailMessageItem] = []
    for analysis in analyses:
        summary = summaries.get(
            f"{analysis.mail_account_id}:{analysis.provider_message_id}"
        )
        account = accounts.get(analysis.mail_account_id)
        items.append(
            MailMessageItem(
                id=analysis.id,
                provider=analysis.provider,
                message_id=analysis.provider_message_id,
                received_at=analysis.received_at,
                account_email=account.email_address if account else "",
                subject=summary.subject if summary else None,
                sender=summary.sender if summary else None,
                preview=summary.preview if summary else None,
                preview_available=summary is not None,
                is_scam=analysis.is_scam,
                risk_level=analysis.risk_level,
                scam_type=analysis.scam_type,
                confidence=analysis.confidence,
                reasons=analysis.reasons or [],
                advice=analysis.advice,
                model=analysis.model,
                analyzed_at=analysis.analyzed_at,
            )
        )

    return MailMessagesResponse(total=total, items=items)


def _build_report_text(sender: str | None, subject: str | None, body: str) -> str:
    """把一封信組成可直接送出的回報文字。

    格式刻意對齊 mail_sync.build_detect_text（寄件者／主旨／空行／內文）：
    回報進向量資料庫的案例，結構要和偵測時餵給模型的文字一致，
    檢索時比對到的才會是同一種東西。差別只在長度上限——偵測要壓到
    MAIL_DETECT_MAX_CHARS，回報則保留 MAIL_CONTENT_MAX_CHARS 的完整證據。
    """
    lines: list[str] = []
    if sender:
        lines.append(f"寄件者：{sender}")
    if subject:
        lines.append(f"主旨：{subject}")
    if body:
        lines.append("")
        lines.append(body)
    return "\n".join(lines).strip()


@router.get(
    "/messages/{analysis_id}/content",
    response_model=MailMessageContent,
    summary="取得單封信的完整內容",
    description=(
        "回傳指定信件的完整內文，供 App 回報詐騙信時作為證據送出"
        "（回報後由 RAG 入庫程式寫進向量資料庫）。\n\n"
        "`analysis_id` 就是 `GET /mail/messages` 每個項目的 `id`。"
        "內容一樣不儲存於資料庫，而是本次請求即時向 Gmail API／Graph API 取回；"
        "與列表端點不同的是，這裡取不到內容就回錯誤而非留空——"
        "回報少了信件全文就失去意義。\n\n"
        "`report_text` 已把寄件者、主旨與內文組好，可直接當作 "
        "`POST /reports/full` 的 `content` 送出。\n\n"
        "錯誤：404 找不到此信件判定紀錄；409 信箱授權已失效（需重新連接）；"
        "502 提供者暫時取不到這封信；503 後端未設定該提供者的 OAuth 憑證。"
    ),
)
async def get_mail_message_content(
    analysis_id: int, db: DbSession, current_user: CurrentUser
) -> MailMessageContent:
    analysis = await crud_mail.get_analysis(db, analysis_id, current_user.id)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="找不到此信件判定紀錄"
        )

    # 判定紀錄隨信箱 CASCADE 刪除，找不到信箱是不該發生的狀態；
    # _require_active_account 的 404／409 訊息在這裡一樣說得通
    account = await _require_active_account(
        db, analysis.mail_account_id, current_user.id
    )
    access_token = await _access_token(db, account)

    try:
        mail = await fetch_message_content(
            account.provider, access_token, analysis.provider_message_id
        )
    except MailAuthExpiredError as exc:
        # 排程同步遲早也會撞到同一件事並停用這個信箱，這裡只回報，不改狀態
        logger.info("取回信件內容時發現授權失效（信箱 %s）：%s", account.id, exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="此信箱的授權已失效，請重新連接後再回報",
        )
    except MailFetchError as exc:
        logger.warning(
            "取回信件內容失敗（信箱 %s，信件 %s）：%s",
            account.id,
            analysis.provider_message_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"暫時無法取得信件內容：{exc}",
        )

    limit = settings.MAIL_CONTENT_MAX_CHARS
    body = mail.body or ""
    body_truncated = len(body) > limit
    if body_truncated:
        body = body[:limit]

    return MailMessageContent(
        id=analysis.id,
        provider=analysis.provider,
        # 以資料庫中的 ID 為準：這是 App 回頭定位這封信的依據
        message_id=analysis.provider_message_id,
        account_id=account.id,
        account_email=account.email_address,
        # 收信時間以判定當下記下的為準，與列表顯示的一致
        received_at=analysis.received_at,
        subject=mail.subject,
        sender=mail.sender,
        body=body or None,
        body_truncated=body_truncated,
        report_text=_build_report_text(mail.sender, mail.subject, body),
        is_scam=analysis.is_scam,
        risk_level=analysis.risk_level,
        scam_type=analysis.scam_type,
    )
