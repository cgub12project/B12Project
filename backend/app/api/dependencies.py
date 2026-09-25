"""FastAPI 共用相依性：資料庫 Session、目前使用者、RAG 內部金鑰驗證。"""

import secrets
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_token
from app.crud import crud_user
from app.db.session import get_db
from app.models.user import User

# Swagger UI 的 Bearer Token 認證方式（auto_error=False 以便自訂錯誤訊息）
bearer_scheme = HTTPBearer(auto_error=False)

# 資料庫 Session 相依性型別別名
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> User:
    """解析 Bearer Token 並載入目前使用者。

    Raises:
        HTTPException 401: 未帶權杖、權杖無效／過期、或使用者不存在。
        HTTPException 403: 帳號已被停用。
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="請提供 Bearer Token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="權杖無效或已過期，請重新登入",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await crud_user.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="使用者不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="帳號已被停用"
        )
    return user


# 目前使用者相依性型別別名
CurrentUser = Annotated[User, Depends(get_current_user)]


async def verify_rag_api_key(
    x_api_key: Annotated[str | None, Header(description="RAG 內部 API 金鑰")] = None,
) -> None:
    """驗證 RAG Worker 的內部 API 金鑰（X-API-Key 標頭）。

    此金鑰僅供內部服務（RAG 入庫程式）使用，與使用者 JWT 認證分離。
    """
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.RAG_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key 無效",
        )
