"""認證端點：登入、註冊、忘記密碼（OTP）、社交登入、權杖管理。

README 已定義 6 個端點；另依功能需求補齊 3 個：
- POST /auth/refresh          換發權杖（README 提及 refresh_token 機制）
- POST /auth/change-password  更改密碼（設定頁功能）
- POST /auth/logout           登出（設定頁功能）
"""

import logging

import jwt
from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.crud import crud_auth, crud_user
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    OAuthRequest,
    RefreshTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
)
from app.schemas.user import UserOut
from app.services import email_service
from app.services.oauth_service import OAuthError, verify_oauth_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["認證"])


def _build_token_response(user) -> TokenResponse:
    """為使用者建立 JWT 權杖組回應。"""
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="註冊",
    description="以 Email 與密碼註冊新帳號，成功後直接回傳 JWT 權杖組（免再登入）。",
)
async def register(body: RegisterRequest, db: DbSession) -> TokenResponse:
    # Email 不可重複註冊
    if await crud_user.get_by_email(db, body.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="此 Email 已被註冊"
        )

    user = await crud_user.create(
        db, email=body.email, name=body.name, password=body.password
    )
    logger.info("新使用者註冊：%s（id=%s）", user.email, user.id)
    return _build_token_response(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="登入",
    description="以 Email 與密碼登入，回傳 JWT（access_token + refresh_token）。",
)
async def login(body: LoginRequest, db: DbSession) -> TokenResponse:
    user = await crud_user.get_by_email(db, body.email)

    # 帳號不存在與密碼錯誤回傳相同訊息，避免帳號列舉攻擊
    if (
        user is None
        or user.password_hash is None
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Email 或密碼錯誤"
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="帳號已被停用")

    await crud_user.touch_last_login(db, user)
    return _build_token_response(user)


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="忘記密碼（發送 OTP）",
    description=(
        "發送 6 位數 OTP 驗證碼至指定 Email。"
        "無論 Email 是否存在皆回傳成功，避免帳號列舉攻擊。"
    ),
)
async def forgot_password(
    body: ForgotPasswordRequest, db: DbSession, background_tasks: BackgroundTasks
) -> MessageResponse:
    user = await crud_user.get_by_email(db, body.email)
    if user is not None and user.is_active:
        otp = await crud_auth.create_reset_otp(db, user)
        # 以背景任務寄信，不阻塞 API 回應
        background_tasks.add_task(email_service.send_otp_email, user.email, otp)

    return MessageResponse(message="若該 Email 已註冊，驗證碼已寄出，請於 10 分鐘內完成驗證")


@router.post(
    "/verify-otp",
    response_model=VerifyOtpResponse,
    summary="驗證 OTP",
    description="驗證 6 位數 OTP；成功後回傳一次性 reset_token，用於下一步重設密碼。",
)
async def verify_otp(body: VerifyOtpRequest, db: DbSession) -> VerifyOtpResponse:
    user = await crud_user.get_by_email(db, body.email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="驗證碼錯誤或已過期"
        )

    reset_token = await crud_auth.verify_otp(db, user, body.otp)
    if reset_token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="驗證碼錯誤或已過期"
        )

    return VerifyOtpResponse(message="驗證成功，請設定新密碼", reset_token=reset_token)


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="重設密碼",
    description="以 verify-otp 取得的 reset_token 重設密碼（權杖為一次性使用）。",
)
async def reset_password(body: ResetPasswordRequest, db: DbSession) -> MessageResponse:
    user = await crud_auth.consume_reset_token(db, body.reset_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="重設權杖無效或已過期，請重新申請",
        )

    await crud_user.update_password(db, user, body.new_password)
    logger.info("使用者 %s 已重設密碼", user.email)
    return MessageResponse(message="密碼重設成功，請以新密碼登入")


@router.post(
    "/oauth",
    response_model=TokenResponse,
    summary="社交登入",
    description=(
        "Google（id_token）或 Facebook（access_token）社交登入。"
        "首次登入自動建立帳號；Email 相同時自動綁定既有帳號。"
    ),
)
async def oauth_login(body: OAuthRequest, db: DbSession) -> TokenResponse:
    # 向提供者官方端點驗證權杖
    try:
        info = await verify_oauth_token(
            body.provider, id_token=body.id_token, access_token=body.access_token
        )
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    # 1) 已綁定過：直接登入
    link = await crud_auth.get_provider_link(db, info.provider, info.provider_user_id)
    if link is not None:
        user = await crud_user.get_by_id(db, link.user_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="帳號已被停用"
            )
        await crud_user.touch_last_login(db, user)
        return _build_token_response(user)

    # 2) 未綁定：依 Email 尋找既有帳號自動綁定，否則建立新帳號
    user = await crud_user.get_by_email(db, info.email) if info.email else None
    if user is None:
        if not info.email:
            # 本系統以 Email 為帳號識別，提供者未回傳 Email 時無法建立帳號
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{body.provider} 帳號未提供 Email，無法登入",
            )
        user = await crud_user.create(
            db,
            email=info.email,
            name=info.name,
            password=None,  # 純社交登入帳號無密碼
            email_verified=info.email_verified,
            avatar_url=info.avatar_url,
        )
        logger.info("社交登入建立新帳號：%s（%s）", user.email, info.provider)

    await crud_auth.link_provider(
        db,
        user_id=user.id,
        provider=info.provider,
        provider_user_id=info.provider_user_id,
        provider_email=info.email,
    )
    await crud_user.touch_last_login(db, user)
    return _build_token_response(user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="換發權杖",
    description="以有效的 refresh_token 換發新的權杖組（access + refresh）。",
)
async def refresh_token(body: RefreshTokenRequest, db: DbSession) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh_token 無效或已過期，請重新登入",
        )

    user = await crud_user.get_by_id(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="使用者不存在或已被停用"
        )
    return _build_token_response(user)


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="更改密碼",
    description="設定頁的更改密碼功能：驗證目前密碼後設定新密碼（需登入）。",
)
async def change_password(
    body: ChangePasswordRequest, db: DbSession, current_user: CurrentUser
) -> MessageResponse:
    # 純社交登入帳號沒有密碼可更改
    if current_user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="此帳號為社交登入帳號，無密碼可更改",
        )
    if not verify_password(body.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="目前密碼錯誤"
        )

    await crud_user.update_password(db, current_user, body.new_password)
    return MessageResponse(message="密碼更改成功")


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="登出",
    description=(
        "登出目前帳號。JWT 為無狀態設計，伺服器端不保存 session，"
        "用戶端收到成功回應後應自行刪除本地儲存的權杖。"
    ),
)
async def logout(current_user: CurrentUser) -> MessageResponse:
    logger.info("使用者 %s 登出", current_user.email)
    return MessageResponse(message="登出成功")
