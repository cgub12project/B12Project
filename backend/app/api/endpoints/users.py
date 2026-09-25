"""使用者端點：個人資料與設定同步（設定頁功能，README 未列出、依功能補齊）。"""

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession
from app.crud import crud_user
from app.schemas.user import (
    UserOut,
    UserSettingsOut,
    UserSettingsUpdateRequest,
    UserUpdateRequest,
)

router = APIRouter(prefix="/users", tags=["使用者"])


@router.get(
    "/me",
    response_model=UserOut,
    summary="取得個人資料",
    description="取得目前登入使用者的個人資料（設定頁顯示名稱與 Email）。",
)
async def get_me(current_user: CurrentUser) -> UserOut:
    return UserOut.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserOut,
    summary="更新個人資料",
    description="更新顯示名稱或頭像 URL（僅需傳入要變更的欄位）。",
)
async def update_me(
    body: UserUpdateRequest, db: DbSession, current_user: CurrentUser
) -> UserOut:
    user = await crud_user.update_profile(
        db, current_user, name=body.name, avatar_url=body.avatar_url
    )
    return UserOut.model_validate(user)


@router.get(
    "/me/settings",
    response_model=UserSettingsOut,
    summary="取得使用者設定",
    description=(
        "取得設定頁 6 個功能開關的伺服器端狀態。"
        "App 端 SQLite 雙寫時以此為跨裝置同步來源。"
    ),
)
async def get_my_settings(db: DbSession, current_user: CurrentUser) -> UserSettingsOut:
    setting = await crud_user.get_or_create_settings(db, current_user.id)
    return UserSettingsOut.model_validate(setting)


@router.put(
    "/me/settings",
    response_model=UserSettingsOut,
    summary="更新使用者設定",
    description="更新設定開關（僅需傳入要變更的欄位，未傳入者維持原值）。",
)
async def update_my_settings(
    body: UserSettingsUpdateRequest, db: DbSession, current_user: CurrentUser
) -> UserSettingsOut:
    # 只取有傳值的欄位（exclude_unset），未傳入的開關不變動
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    setting = await crud_user.update_settings(db, current_user.id, changes)
    return UserSettingsOut.model_validate(setting)
