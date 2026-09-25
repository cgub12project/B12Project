"""信件讀取服務：Gmail API 與 Microsoft Graph API 的統一介面。

把兩家差異極大的 API 收斂成同一組資料結構，讓同步邏輯（mail_sync.py）與
讀取端點不必分別處理 Gmail 與 Outlook：

- `MailSummary`：顯示用摘要（主旨、寄件者、預覽、收信時間）
- `MailContent`：摘要 + 純文字內文（送進 AI 判斷用）

⚠ 這裡取回的任何內容都只存在於記憶體：判定結果進資料庫，信件本身不進。
   列表顯示所需的主旨／寄件者是每次請求即時向提供者取回的（passthrough）。

各家對應關係：

| 動作 | Gmail API | Microsoft Graph |
|------|-----------|-----------------|
| 列出新信 | `users.messages.list`（`q=after:<YYYY/MM/DD>`） | `/me/mailFolders/inbox/messages`（`$filter=receivedDateTime ge …`） |
| 取單封 | `users.messages.get`（`format=full` / `metadata`） | `/me/messages/{id}`（`$select=…`） |
| 信箱位址 | `users.getProfile` | `/me`（`mail` 或 `userPrincipalName`） |

Gmail 回傳的是 RFC 2822 原始信件（內文為 base64url 的 MIME 結構，須自行走訪
part 樹並挑出 text/plain）；Graph 則直接給結構化 JSON。差異全部吸收在本模組。
"""

import base64
import binascii
import html as html_module
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

# API 基底位址
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0/me"

# 呼叫信件 API 的逾時秒數
MAIL_API_TIMEOUT = 20

# 預覽片段長度（對齊 Gmail snippet 的量級）
PREVIEW_MAX_CHARS = 200


class MailFetchError(Exception):
    """向提供者讀取信件失敗（網路、配額、API 回應異常）。"""


class MailAuthExpiredError(MailFetchError):
    """存取權杖已失效（使用者撤銷授權、改密碼等），需重新連接信箱。"""


class MailPermissionError(MailFetchError):
    """權杖有效，但缺少這次操作所需的授權範圍（HTTP 403）。

    實務上幾乎都是同一個原因：使用者是在後端加上新 scope **之前**連接的，
    手上那張 refresh_token 只涵蓋舊 scope。解法是請使用者重新連接一次信箱。
    """


@dataclass
class MailSummary:
    """顯示用的信件摘要（不落地，僅在回應中即時帶出）。"""

    message_id: str
    subject: str | None
    sender: str | None
    preview: str | None
    received_at: datetime  # naive UTC，與資料庫時間格式一致


@dataclass
class MailContent(MailSummary):
    """信件摘要 + 純文字內文（送進 AI 判斷後即丟棄）。"""

    body: str


# ------------------------------------------------------------
# 共用工具
# ------------------------------------------------------------

def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _check_response(response: httpx.Response, *, expected: tuple[int, ...]) -> None:
    """檢查提供者 API 的回應狀態，把錯誤轉成本模組的例外。"""
    if response.status_code == 401:
        raise MailAuthExpiredError("信箱授權已失效，請重新連接信箱")
    if response.status_code == 403:
        detail = response.text.strip()[:200] or "（回應主體為空）"
        raise MailPermissionError(f"信箱授權範圍不足：{detail}")
    if response.status_code not in expected:
        detail = response.text.strip()[:200] or "（回應主體為空）"
        raise MailFetchError(f"信件 API 回傳 HTTP {response.status_code}：{detail}")


async def _api_get(url: str, access_token: str, params: dict | None = None) -> dict:
    """呼叫提供者 API 並回傳 JSON。

    Raises:
        MailAuthExpiredError: HTTP 401（權杖失效）。
        MailPermissionError: HTTP 403（授權範圍不足）。
        MailFetchError: 其他失敗。
    """
    try:
        async with httpx.AsyncClient(timeout=MAIL_API_TIMEOUT) as client:
            response = await client.get(
                url, headers=_auth_headers(access_token), params=params
            )
    except httpx.HTTPError as exc:
        raise MailFetchError(f"信件 API 連線失敗（{type(exc).__name__}）") from exc

    _check_response(response, expected=(200,))
    return response.json()


async def _api_post(url: str, access_token: str, json_body: dict) -> dict:
    """對提供者 API 送出 POST（目前用於建立 Gmail 過濾規則）。"""
    try:
        async with httpx.AsyncClient(timeout=MAIL_API_TIMEOUT) as client:
            response = await client.post(
                url, headers=_auth_headers(access_token), json=json_body
            )
    except httpx.HTTPError as exc:
        raise MailFetchError(f"信件 API 連線失敗（{type(exc).__name__}）") from exc

    _check_response(response, expected=(200, 201))
    return response.json()


async def _api_delete(url: str, access_token: str) -> None:
    """對提供者 API 送出 DELETE（目前用於移除 Gmail 過濾規則）。

    404 視為成功：規則已經不在了，與「刪掉了」對使用者是同一件事
    （使用者可能自己在 Gmail 設定裡刪過）。
    """
    try:
        async with httpx.AsyncClient(timeout=MAIL_API_TIMEOUT) as client:
            response = await client.delete(url, headers=_auth_headers(access_token))
    except httpx.HTTPError as exc:
        raise MailFetchError(f"信件 API 連線失敗（{type(exc).__name__}）") from exc

    if response.status_code == 404:
        return
    _check_response(response, expected=(200, 204))


def _to_naive_utc(value: datetime) -> datetime:
    """轉為 naive UTC（專案統一的時間儲存格式）。"""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _make_preview(text: str | None) -> str | None:
    """把內文壓成單行預覽片段。"""
    if not text:
        return None
    collapsed = re.sub(r"\s+", " ", text).strip()
    if not collapsed:
        return None
    return collapsed[:PREVIEW_MAX_CHARS]


def _html_to_text(html: str) -> str:
    """把 HTML 信件內文轉成純文字。

    只做最低限度處理：移除 script／style 整段、把標籤換成空白、還原 HTML 實體。
    目的是讓 AI 讀到「使用者會看到的字」，不是完整還原排版——引入 HTML 解析
    套件對這個需求並不划算。
    """
    without_blocks = re.sub(
        r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE
    )
    without_tags = re.sub(r"<[^>]+>", " ", without_blocks)
    return html_module.unescape(without_tags)


# ------------------------------------------------------------
# Gmail API
# ------------------------------------------------------------

def _decode_base64url(data: str) -> str:
    """解碼 Gmail 的 base64url 內文（自動補齊 padding）。"""
    padding = "=" * (-len(data) % 4)
    try:
        raw = base64.urlsafe_b64decode(data + padding)
    except (binascii.Error, ValueError):
        return ""
    return raw.decode("utf-8", errors="replace")


def _gmail_header(payload: dict, name: str) -> str | None:
    """自 Gmail payload 取出指定標頭值（標頭名稱不分大小寫）。"""
    target = name.lower()
    for header in payload.get("headers") or []:
        if str(header.get("name", "")).lower() == target:
            return header.get("value")
    return None


def _gmail_extract_body(payload: dict) -> str:
    """走訪 Gmail 的 MIME part 樹，取出信件純文字內文。

    優先取 text/plain；整封只有 HTML 時退而取 text/html 並轉純文字。
    多層 multipart（multipart/alternative 包在 multipart/mixed 裡）以遞迴處理。
    """
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict) -> None:
        mime_type = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data:
            if mime_type == "text/plain":
                plain_parts.append(_decode_base64url(data))
            elif mime_type == "text/html":
                html_parts.append(_html_to_text(_decode_base64url(data)))
        for sub_part in part.get("parts") or []:
            walk(sub_part)

    walk(payload)
    chosen = plain_parts or html_parts
    return "\n".join(chosen).strip()


def _gmail_received_at(message: dict) -> datetime:
    """自 Gmail 的 internalDate（毫秒 epoch 字串）取得收信時間。"""
    try:
        millis = int(message.get("internalDate", 0))
    except (TypeError, ValueError):
        millis = 0
    if millis <= 0:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).replace(tzinfo=None)


# Gmail 增量查詢往回多退的天數（見 _gmail_after_query 的說明）
GMAIL_QUERY_SLACK_DAYS = 1


def _gmail_after_query(since: datetime) -> str:
    """組出 Gmail 增量查詢用的 `after:` 條件（**刻意只到「日」的精度**）。

    Gmail 的 `q` 走的是搜尋語法，不是精確的欄位比較，而且它有兩個對增量抓取
    很致命的性質：

    1. `after:`／`before:` 是以**信箱帳號自己設定的時區**換算日期的，後端這邊
       只有 UTC，兩者相差幾小時；用秒級的 unix 時間戳反而是把一個不精確的
       比較假裝成精確的。
    2. 搜尋索引是**最終一致**的——信件已經送達收件匣，但要再過一段時間才進得了
       搜尋索引。以「同步開始的時刻」當游標往前推進，剛好落在這個空窗的信件
       就會被永久跳過：下一輪問的是更晚的時間，那封信再也不會被列出來。

    所以這裡改成往回退整整 GMAIL_QUERY_SLACK_DAYS 天、且只取到日期：查詢一定
    是真正需要的區間的**超集**，時區差幾小時、索引晚幾分鐘都吃得下。多列到的
    舊信不會造成任何額外成本——sync_account 會先用 provider_message_id 向
    資料庫去重，只有沒分析過的才會真的去取內容。
    """
    window_start = since - timedelta(days=GMAIL_QUERY_SLACK_DAYS)
    return f"after:{window_start.strftime('%Y/%m/%d')}"


async def _gmail_list_message_ids(
    access_token: str, since: datetime | None, limit: int
) -> list[str]:
    params: dict[str, str | int] = {"maxResults": limit, "labelIds": "INBOX"}
    if since is not None:
        params["q"] = _gmail_after_query(since)

    payload = await _api_get(f"{GMAIL_API_BASE}/messages", access_token, params)
    ids = [item["id"] for item in payload.get("messages") or [] if item.get("id")]
    logger.debug(
        "Gmail 列出收件匣信件：q=%s，取回 %d 筆", params.get("q", "（無）"), len(ids)
    )
    return ids


async def _gmail_get_message(
    access_token: str, message_id: str, *, with_body: bool
) -> dict:
    """取回單封 Gmail 信件。

    with_body=False 時使用 format=metadata，只要求 From／Subject／Date 三個標頭：
    Google 不會回傳任何內文，是列表 passthrough 該用的最小權限形式。
    """
    if with_body:
        params: dict[str, str | list[str]] = {"format": "full"}
    else:
        params = {
            "format": "metadata",
            "metadataHeaders": ["From", "Subject", "Date"],
        }
    return await _api_get(f"{GMAIL_API_BASE}/messages/{message_id}", access_token, params)


def _gmail_to_summary(message: dict) -> MailSummary:
    payload = message.get("payload") or {}
    return MailSummary(
        message_id=message.get("id", ""),
        subject=_gmail_header(payload, "Subject"),
        sender=_gmail_header(payload, "From"),
        # Gmail 直接提供 snippet（其自身產生的預覽片段）
        preview=_make_preview(message.get("snippet")),
        received_at=_gmail_received_at(message),
    )


# ------------------------------------------------------------
# Microsoft Graph API
# ------------------------------------------------------------

# 列表與單封取用的欄位（$select 明確列出，避免抓回整包不需要的資料）
GRAPH_SUMMARY_FIELDS = "id,subject,from,bodyPreview,receivedDateTime"
GRAPH_CONTENT_FIELDS = f"{GRAPH_SUMMARY_FIELDS},body"


def _graph_received_at(message: dict) -> datetime:
    """解析 Graph 的 receivedDateTime（ISO 8601，結尾為 Z）。"""
    raw = message.get("receivedDateTime")
    if not raw:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        # Python 3.11 前的 fromisoformat 不吃結尾的 Z，統一換成 +00:00
        return _to_naive_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    except ValueError:
        return datetime.now(timezone.utc).replace(tzinfo=None)


def _graph_sender(message: dict) -> str | None:
    """組出「顯示名稱 <位址>」格式的寄件者（對齊 Gmail 的 From 標頭）。"""
    address_info = ((message.get("from") or {}).get("emailAddress")) or {}
    address = address_info.get("address")
    name = address_info.get("name")
    if address and name and name != address:
        return f"{name} <{address}>"
    return address or name


def _graph_to_summary(message: dict) -> MailSummary:
    return MailSummary(
        message_id=message.get("id", ""),
        subject=message.get("subject"),
        sender=_graph_sender(message),
        preview=_make_preview(message.get("bodyPreview")),
        received_at=_graph_received_at(message),
    )


def _graph_extract_body(message: dict) -> str:
    """取出 Graph 信件內文（contentType 為 html 時轉純文字）。"""
    body = message.get("body") or {}
    content = str(body.get("content") or "")
    if str(body.get("contentType", "")).lower() == "html":
        return _html_to_text(content).strip()
    return content.strip()


async def _graph_list_message_ids(
    access_token: str, since: datetime | None, limit: int
) -> list[str]:
    params: dict[str, str | int] = {
        # $orderby 是為了讓 $top 截到的是「最新的 limit 封」，不是隨機的 limit 封
        # （Gmail 沒有對應參數，其列表本身就是新到舊）
        "$select": "id",
        "$orderby": "receivedDateTime desc",
        "$top": limit,
    }
    if since is not None:
        # Graph 的 $filter 要求 UTC ISO 8601（結尾 Z）
        params["$filter"] = (
            f"receivedDateTime ge {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )

    payload = await _api_get(
        f"{GRAPH_API_BASE}/mailFolders/inbox/messages", access_token, params
    )
    return [item["id"] for item in payload.get("value") or [] if item.get("id")]


# ------------------------------------------------------------
# 對外統一介面
# ------------------------------------------------------------

def normalize_sender_address(raw: str | None) -> str | None:
    """自 From 標頭取出純小寫的信箱位址。

    寄件者欄位有兩種長相：`"顯示名稱" <bad@example.com>` 與裸位址 `bad@example.com`。
    封鎖必須以位址為準——顯示名稱是寄件人自己填的，改一個字就繞過去了。
    大小寫一律轉小寫，讓資料庫的唯一鍵與同步時的比對能對得起來。

    回傳 None 表示這串文字裡找不到看起來像信箱位址的東西。
    """
    if not raw:
        return None
    text = raw.strip()
    # 角括號內優先（有顯示名稱時位址一定在裡面）
    bracketed = re.search(r"<([^<>]+)>", text)
    if bracketed:
        text = bracketed.group(1).strip()
    match = re.fullmatch(r"[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]+", text)
    return match.group(0).lower() if match else None


async def block_sender(provider: str, access_token: str, sender_address: str) -> str:
    """在提供者端建立「這個寄件人的信不要進收件匣」的規則，回傳規則 ID。

    Gmail 沒有 block sender 端點，等價作法是 Filters API：criteria.from 指定
    寄件位址、action.removeLabelIds 拿掉 INBOX。之後這個人寄來的信仍會進信箱
    （留在「所有郵件」，使用者事後查得到），但不再出現在收件匣——
    也就不會被 list_message_ids 列出、不會再耗一次 AI 判定。

    ⚠ 需要 gmail.settings.basic 授權範圍。在加上這個 scope 之前連接的使用者，
      手上的權杖只有 gmail.readonly，這裡會收到 403（MailPermissionError）。
    """
    if provider == "gmail":
        payload = await _api_post(
            f"{GMAIL_API_BASE}/settings/filters",
            access_token,
            {
                "criteria": {"from": sender_address},
                "action": {"removeLabelIds": ["INBOX"]},
            },
        )
        filter_id = payload.get("id")
        if not filter_id:
            raise MailFetchError("Gmail 未回傳過濾規則 ID")
        return str(filter_id)
    if provider == "outlook":
        # Graph 的對應功能是 /me/mailFolders/inbox/messageRules，尚未實作
        raise MailFetchError("Outlook 尚未支援寄件人封鎖")
    raise MailFetchError(f"不支援的信箱提供者：{provider}")


async def unblock_sender(provider: str, access_token: str, filter_id: str) -> None:
    """移除先前建立的封鎖規則。"""
    if provider == "gmail":
        await _api_delete(f"{GMAIL_API_BASE}/settings/filters/{filter_id}", access_token)
        return
    if provider == "outlook":
        raise MailFetchError("Outlook 尚未支援寄件人封鎖")
    raise MailFetchError(f"不支援的信箱提供者：{provider}")


async def fetch_account_email(provider: str, access_token: str) -> str:
    """取得已授權信箱的位址（連接完成時記錄用）。"""
    if provider == "gmail":
        payload = await _api_get(f"{GMAIL_API_BASE}/profile", access_token)
        email = payload.get("emailAddress")
    elif provider == "outlook":
        payload = await _api_get(
            GRAPH_API_BASE, access_token, {"$select": "mail,userPrincipalName"}
        )
        # 公司帳號可能只有 userPrincipalName 沒有 mail
        email = payload.get("mail") or payload.get("userPrincipalName")
    else:
        raise MailFetchError(f"不支援的信箱提供者：{provider}")

    if not email:
        raise MailFetchError("提供者未回傳信箱位址")
    return str(email)


async def list_message_ids(
    provider: str, access_token: str, *, since: datetime | None, limit: int
) -> list[str]:
    """列出收件匣中 `since` 之後的信件 ID（最新的最多 limit 筆）。

    回傳順序僅為提供者給的順序，不是保證：Graph 有 `$orderby`，Gmail 的
    `users.messages.list` 卻沒有排序參數。呼叫端要依時間處理，請以每封信
    自己的 `received_at` 排序（mail_sync.sync_account 就是這麼做的）。
    """
    if provider == "gmail":
        return await _gmail_list_message_ids(access_token, since, limit)
    if provider == "outlook":
        return await _graph_list_message_ids(access_token, since, limit)
    raise MailFetchError(f"不支援的信箱提供者：{provider}")


async def fetch_message_summary(
    provider: str, access_token: str, message_id: str
) -> MailSummary:
    """取回單封信件的顯示用摘要（不含內文）。"""
    if provider == "gmail":
        message = await _gmail_get_message(access_token, message_id, with_body=False)
        return _gmail_to_summary(message)
    if provider == "outlook":
        message = await _api_get(
            f"{GRAPH_API_BASE}/messages/{message_id}",
            access_token,
            {"$select": GRAPH_SUMMARY_FIELDS},
        )
        return _graph_to_summary(message)
    raise MailFetchError(f"不支援的信箱提供者：{provider}")


async def fetch_message_content(
    provider: str, access_token: str, message_id: str
) -> MailContent:
    """取回單封信件的完整內容（摘要 + 純文字內文），供 AI 判斷使用。"""
    if provider == "gmail":
        message = await _gmail_get_message(access_token, message_id, with_body=True)
        summary = _gmail_to_summary(message)
        body = _gmail_extract_body(message.get("payload") or {})
    elif provider == "outlook":
        message = await _api_get(
            f"{GRAPH_API_BASE}/messages/{message_id}",
            access_token,
            {"$select": GRAPH_CONTENT_FIELDS},
        )
        summary = _graph_to_summary(message)
        body = _graph_extract_body(message)
    else:
        raise MailFetchError(f"不支援的信箱提供者：{provider}")

    return MailContent(
        message_id=summary.message_id,
        subject=summary.subject,
        sender=summary.sender,
        preview=summary.preview,
        received_at=summary.received_at,
        body=body,
    )
