"""Email 寄送服務（忘記密碼 OTP）。

未設定 SMTP_HOST 時為「開發模式」：不實際寄信，
OTP 直接輸出到後端日誌，方便本機開發測試。
"""

import logging
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


def _resolve_sender() -> tuple[str, str]:
    """解析寄件者設定，回傳（From 標頭顯示值, 信封寄件位址）。

    SMTP_FROM 支援三種寫法：
    - 完整格式：``F.L.A.S.H. 系統 <no-reply@example.com>``
    - 只有位址：``no-reply@example.com``
    - 只有顯示名稱（無 @）：以 SMTP_USER 作為寄件位址
      （Gmail 等服務本就強制以登入帳號寄出）
    """
    name, address = parseaddr(settings.SMTP_FROM)
    if "@" not in address:
        # SMTP_FROM 未含有效位址：整串視為顯示名稱，位址改用 SMTP_USER
        name = settings.SMTP_FROM.strip()
        address = settings.SMTP_USER or "no-reply@flash.local"

    if name:
        # 顯示名稱含中文等非 ASCII 字元時，需以 RFC 2047 編碼
        display = formataddr((str(Header(name, "utf-8")), address))
    else:
        display = address
    return display, address


async def send_otp_email(to_email: str, otp: str) -> None:
    """寄送 OTP 驗證碼 Email。

    Args:
        to_email: 收件者 Email。
        otp: 6 位數驗證碼。
    """
    # 開發模式：未設定 SMTP，僅輸出日誌
    if not settings.SMTP_HOST:
        logger.warning("【開發模式】未設定 SMTP，OTP 不寄送。%s 的驗證碼為：%s", to_email, otp)
        return

    # 組裝郵件內容（HTML + 純文字）
    from_display, from_address = _resolve_sender()
    message = MIMEMultipart("alternative")
    message["From"] = from_display
    message["To"] = to_email
    message["Subject"] = "F.L.A.S.H. 密碼重設驗證碼"

    text_body = (
        f"您的 F.L.A.S.H. 密碼重設驗證碼為：{otp}\n"
        f"驗證碼將於 {settings.OTP_EXPIRE_MINUTES} 分鐘後失效。\n"
        f"若您未申請重設密碼，請忽略此信。"
    )
    html_body = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
      <h2>F.L.A.S.H. 密碼重設</h2>
      <p>您的驗證碼為：</p>
      <p style="font-size: 32px; font-weight: bold; letter-spacing: 8px;">{otp}</p>
      <p>驗證碼將於 <b>{settings.OTP_EXPIRE_MINUTES} 分鐘</b>後失效。</p>
      <p style="color: #888;">若您未申請重設密碼，請忽略此信。</p>
    </div>
    """
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        # 明確指定信封寄件者／收件者，不依賴標頭解析
        await aiosmtplib.send(
            message,
            sender=from_address,
            recipients=[to_email],
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            start_tls=settings.SMTP_TLS,
        )
        logger.info("OTP Email 已寄送至 %s", to_email)
    except Exception:
        # 寄送失敗記錄日誌但不對外揭露細節（避免洩漏帳號存在與否）
        logger.exception("OTP Email 寄送失敗（收件者：%s）", to_email)
