"""地端模型下載的回應 Schema。

欄位與《後端協助_地端模型私有下載部署需求》第三節的契約逐字對齊，
換版時 App 端不需改程式，只要後端調整 version／size_bytes／sha256／URL。

第二顆模型（階段判定）加進來時**沒有動 `LocalModelManifest` 一個欄位**：
`/manifest` 不論帶不帶 `?model=stage`，回的都是同一組六個欄位，App 端那支
既有的解析程式可以原封不動地重用（Android 上 kotlinx.serialization 預設
遇到沒宣告的鍵會直接丟例外，多塞欄位等於逼已上架的版本改程式）。
要一次看到有哪些模型可下載，改呼叫 `/catalog`——那是一支新端點，
舊版 App 不會碰到它。
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_serializer


class LocalModelManifest(BaseModel):
    """地端模型的版本資訊與短效下載網址。"""

    version: str = Field(description="模型版本，例：4.1", examples=["4.1"])
    file_name: str = Field(
        description="模型檔名（App 存檔時沿用）", examples=["flash-v5.gguf"]
    )
    size_bytes: int = Field(
        description="模型檔大小（bytes），App 用來顯示下載量與檢查空間",
        examples=[1929902464],
    )
    sha256: str = Field(
        description="模型檔的 SHA-256；App 下載完成後須核對通過才可啟用地端模式",
        examples=["497857a75365ee0daaea7fe353fa9a8a77208b0ec9233de03b90be36875b20e9"],
    )
    download_url: str = Field(
        description=(
            "短效簽章下載網址（支援 HTTP Range 續傳）。"
            "此網址已內含授權，下載時不需要再帶 Authorization 標頭"
        )
    )
    expires_at: datetime = Field(
        description=(
            "下載網址的到期時間（UTC）。過期後重新呼叫本端點取得新網址即可，"
            "已下載的部分不必重來"
        )
    )

    @field_serializer("expires_at")
    def _serialize_expires_at(self, value: datetime) -> str:
        """以 `2026-08-19T12:00:00Z` 格式輸出（對齊需求書範例，Android 端好解析）。

        專案內部一律以 UTC 記時間，naive 的值視為 UTC。
        """
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LocalModelCatalogEntry(LocalModelManifest):
    """catalog 裡的一顆模型：manifest 的六個欄位，外加「這顆是誰」。"""

    model_id: str = Field(
        description="模型代號，供 `/manifest?model=` 使用",
        examples=["detect", "stage"],
    )
    role: str = Field(
        description="這顆模型在 App 裡負責的判定（顯示用）",
        examples=["詐騙偵測（判斷訊息是不是詐騙）"],
    )


class LocalModelCatalog(BaseModel):
    """目前提供下載的所有地端模型。

    只列出**真的部署好**的那幾顆：某一顆設定錯了或還沒上傳，它只是不出現在
    這份清單裡，不會讓整份 catalog 失敗（否則階段模型換版的空窗期會連偵測
    模型都下載不了）。App 端請依 `model_id` 取用，不要依賴陣列順序。
    """

    models: list[LocalModelCatalogEntry] = Field(
        description="可下載的模型清單（每筆都已內含自己的短效簽章網址）"
    )
