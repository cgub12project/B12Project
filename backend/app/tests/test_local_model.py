"""地端模型下載端點測試。

以一個 16 KB 的假模型檔取代 1.93 GB 的 GGUF（行為完全相同，只是小得可以放進
測試），逐項對應需求書第六節的驗收條件：401／403、manifest 欄位、SHA-256、
Range 206 續傳、HEAD、以及換版後舊簽章失效。

第二顆模型（`stage`，詐騙階段判定）另有一組測試，盯的是三件加進來才會有的事：
`/manifest` 的預設行為一個位元都沒變、兩顆的簽章不能互用、一顆沒部署不會拖垮
另一顆（catalog 少列一項，偵測那條線照常）。
"""

import hashlib
import logging

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.security import create_local_model_token
from app.services.local_model import (
    _DownloadTokenLogFilter,
    build_download_url,
    download_path,
)

MANIFEST_URL = "/api/v1/local-model/manifest"
CATALOG_URL = "/api/v1/local-model/catalog"

# 假模型檔內容：16 KB，內容固定以便驗證 Range 續傳拼回來的位元組完全一致
MODEL_BYTES = bytes(range(256)) * 64
MODEL_SHA256 = hashlib.sha256(MODEL_BYTES).hexdigest()

# 階段模型用另一份內容：兩顆若不小心指到同一個檔案，靠 sha256 才看得出來
STAGE_BYTES = bytes(range(255, -1, -1)) * 32
STAGE_SHA256 = hashlib.sha256(STAGE_BYTES).hexdigest()


@pytest.fixture
def model_file(tmp_path, monkeypatch):
    """部署一個假的地端模型檔，並把設定指向它。"""
    path = tmp_path / "flash-v5.gguf"
    path.write_bytes(MODEL_BYTES)

    monkeypatch.setattr(settings, "LOCAL_MODEL_ENABLED", True)
    monkeypatch.setattr(settings, "LOCAL_MODEL_PATH", str(path))
    monkeypatch.setattr(settings, "LOCAL_MODEL_FILE_NAME", "flash-v5.gguf")
    monkeypatch.setattr(settings, "LOCAL_MODEL_VERSION", "5.0")
    monkeypatch.setattr(settings, "LOCAL_MODEL_SHA256", "")
    monkeypatch.setattr(settings, "LOCAL_MODEL_SIZE_BYTES", 0)
    monkeypatch.setattr(settings, "LOCAL_MODEL_PUBLIC_BASE_URL", "")
    monkeypatch.setattr(settings, "LOCAL_MODEL_XACCEL_LOCATION", "")
    monkeypatch.setattr(settings, "LOCAL_MODEL_RATE_LIMIT_BYTES_PER_SEC", 0)

    # 階段模型預設為「尚未部署」：偵測那條線的每一條測試都必須在只有一顆模型的
    # 情況下照樣通過（這正是第二顆對已上架 App 的相容性保證）
    monkeypatch.setattr(settings, "LOCAL_MODEL_STAGE_ENABLED", True)
    monkeypatch.setattr(settings, "LOCAL_MODEL_STAGE_PATH", "")
    monkeypatch.setattr(settings, "LOCAL_MODEL_STAGE_FILE_NAME", "flash-stage-v2.gguf")
    monkeypatch.setattr(settings, "LOCAL_MODEL_STAGE_VERSION", "2.0")
    monkeypatch.setattr(settings, "LOCAL_MODEL_STAGE_SHA256", "")
    monkeypatch.setattr(settings, "LOCAL_MODEL_STAGE_SIZE_BYTES", 0)
    return path


@pytest.fixture
def stage_model_file(tmp_path, monkeypatch, model_file):
    """再部署一顆階段判定模型（flash-stage-v2.gguf）。"""
    path = tmp_path / "flash-stage-v2.gguf"
    path.write_bytes(STAGE_BYTES)
    monkeypatch.setattr(settings, "LOCAL_MODEL_STAGE_PATH", str(path))
    return path


async def _get_download_url(client: AsyncClient, auth_headers: dict) -> str:
    """取得一組合法的簽章下載網址。"""
    response = await client.get(MANIFEST_URL, headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()["download_url"]


# ============================================================
# manifest
# ============================================================

async def test_manifest_requires_auth(client: AsyncClient, model_file):
    """未帶 Authorization → 401（驗收條件一）。"""
    response = await client.get(MANIFEST_URL)
    assert response.status_code == 401


async def test_manifest_contract_fields(
    client: AsyncClient, auth_headers: dict, model_file
):
    """合法使用者可取得 manifest，欄位與需求書第三節一致（驗收條件二）。"""
    response = await client.get(MANIFEST_URL, headers=auth_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert set(body) == {
        "version",
        "file_name",
        "size_bytes",
        "sha256",
        "download_url",
        "expires_at",
    }
    assert body["version"] == "5.0"
    assert body["file_name"] == "flash-v5.gguf"
    assert body["size_bytes"] == len(MODEL_BYTES)
    # 未設定 LOCAL_MODEL_SHA256 時由後端讀檔計算
    assert body["sha256"] == MODEL_SHA256
    assert body["download_url"].startswith(
        f"http://test{download_path('flash-v5.gguf')}?token="
    )
    # 需求書範例的時間格式（結尾為 Z），Android 端可直接解析
    assert body["expires_at"].endswith("Z")


async def test_manifest_uses_public_base_url(
    client: AsyncClient, auth_headers: dict, model_file, monkeypatch
):
    """設定正式網域後，下載網址走該網域（不受反向代理標頭影響）。"""
    monkeypatch.setattr(
        settings, "LOCAL_MODEL_PUBLIC_BASE_URL", "https://models.example.com/"
    )
    response = await client.get(MANIFEST_URL, headers=auth_headers)
    assert response.json()["download_url"].startswith(
        "https://models.example.com/api/v1/local-model/download/flash-v5.gguf?token="
    )


async def test_manifest_503_when_not_deployed(
    client: AsyncClient, auth_headers: dict, model_file, monkeypatch
):
    """模型尚未部署 → 503（而不是回一份指向不存在檔案的 manifest）。"""
    monkeypatch.setattr(settings, "LOCAL_MODEL_PATH", "")
    response = await client.get(MANIFEST_URL, headers=auth_headers)
    assert response.status_code == 503


async def test_manifest_503_on_size_mismatch(
    client: AsyncClient, auth_headers: dict, model_file, monkeypatch
):
    """實際檔案與設定的大小不符 → 503。

    傳輸未完成或換版只改了一半設定時，發出去的 manifest 其 sha256 永遠核對不過，
    使用者會白下載 1.93 GB 才在最後一步失敗，所以寧可在這裡就擋下來。
    """
    monkeypatch.setattr(settings, "LOCAL_MODEL_SIZE_BYTES", len(MODEL_BYTES) + 1)
    response = await client.get(MANIFEST_URL, headers=auth_headers)
    assert response.status_code == 503


# ============================================================
# 下載：授權
# ============================================================

async def test_download_without_token_401(client: AsyncClient, model_file):
    """未帶簽章 → 401（驗收條件一）。"""
    response = await client.get(download_path("flash-v5.gguf"))
    assert response.status_code == 401


async def test_download_with_invalid_token_401(client: AsyncClient, model_file):
    """偽造的簽章 → 401。"""
    response = await client.get(
        download_path("flash-v5.gguf"), params={"token": "not-a-real-token"}
    )
    assert response.status_code == 401


async def test_download_with_expired_token_401(client: AsyncClient, model_file):
    """過期的簽章 → 401（驗收條件一）。"""
    token, _ = create_local_model_token(1, "flash-v5.gguf", "5.0", expire_hours=-1)
    response = await client.get(
        download_path("flash-v5.gguf"), params={"token": token}
    )
    assert response.status_code == 401


async def test_download_rejects_access_token(
    client: AsyncClient, auth_headers: dict, model_file
):
    """使用者的 access token 不能當下載簽章用（權杖類型分離）。"""
    access_token = auth_headers["Authorization"].removeprefix("Bearer ")
    response = await client.get(
        download_path("flash-v5.gguf"), params={"token": access_token}
    )
    assert response.status_code == 401


async def test_download_rejects_token_of_other_version(client: AsyncClient, model_file):
    """換版後舊網址失效：簽章綁定版本，不會下載到已下架的模型。"""
    token, _ = create_local_model_token(1, "flash-v5.gguf", "3.9", expire_hours=24)
    response = await client.get(
        download_path("flash-v5.gguf"), params={"token": token}
    )
    assert response.status_code == 401


async def test_download_rejects_token_of_unknown_user(client: AsyncClient, model_file):
    """簽章對應的使用者不存在（已刪除帳號）→ 401。"""
    token, _ = create_local_model_token(999_999, "flash-v5.gguf", "5.0", 24)
    response = await client.get(
        download_path("flash-v5.gguf"), params={"token": token}
    )
    assert response.status_code == 401


async def test_download_unknown_file_name_404(
    client: AsyncClient, auth_headers: dict, model_file
):
    """檔名不是目前提供的模型 → 404（沒有匿名可列舉的檔案入口）。"""
    url = await _get_download_url(client, auth_headers)
    token = url.split("token=")[1]
    response = await client.get(download_path("other-model.gguf"), params={"token": token})
    assert response.status_code == 404


async def test_authorize_endpoint(client: AsyncClient, auth_headers: dict, model_file):
    """auth_request 端點：簽章有效回 204、無效回 401（不送檔案本體）。"""
    url = await _get_download_url(client, auth_headers)
    token = url.split("token=")[1]

    ok = await client.get("/api/v1/local-model/authorize", params={"token": token})
    assert ok.status_code == 204
    assert ok.content == b""

    missing = await client.get("/api/v1/local-model/authorize")
    assert missing.status_code == 401


# ============================================================
# 下載：檔案傳輸
# ============================================================

async def test_download_full_file_matches_sha256(
    client: AsyncClient, auth_headers: dict, model_file
):
    """完整下載的內容與 manifest 的 SHA-256 一致（驗收條件三）。"""
    response = await client.get(await _get_download_url(client, auth_headers))

    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == MODEL_SHA256
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == 'attachment; filename="flash-v5.gguf"'
    assert response.headers["accept-ranges"] == "bytes"
    # 續傳靠 ETag／Last-Modified 判斷檔案是否換過
    assert response.headers["etag"]
    assert response.headers["last-modified"]


async def test_download_range_returns_206_and_resumes(
    client: AsyncClient, auth_headers: dict, model_file
):
    """Range 請求回 206，且可從中斷位置續傳（驗收條件四、五）。"""
    url = await _get_download_url(client, auth_headers)

    first = await client.get(url, headers={"Range": "bytes=0-1023"})
    assert first.status_code == 206
    assert first.headers["accept-ranges"] == "bytes"
    assert first.headers["content-range"] == f"bytes 0-1023/{len(MODEL_BYTES)}"
    assert first.headers["content-length"] == "1024"
    assert first.content == MODEL_BYTES[:1024]

    # App 重啟後拿同一組簽章（24 小時內有效）從中斷處續傳
    rest = await client.get(url, headers={"Range": f"bytes=1024-{len(MODEL_BYTES) - 1}"})
    assert rest.status_code == 206
    assert first.content + rest.content == MODEL_BYTES


async def test_download_range_beyond_file_returns_416(
    client: AsyncClient, auth_headers: dict, model_file
):
    """Range 超出檔案範圍 → 416（而不是靜默回整包）。"""
    url = await _get_download_url(client, auth_headers)
    response = await client.get(url, headers={"Range": "bytes=99999999-"})
    assert response.status_code == 416


async def test_head_returns_headers_only(
    client: AsyncClient, auth_headers: dict, model_file
):
    """HEAD 只回標頭，供 App 確認大小／版本。"""
    response = await client.head(await _get_download_url(client, auth_headers))

    assert response.status_code == 200
    assert response.headers["content-length"] == str(len(MODEL_BYTES))
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content == b""


async def test_download_uses_xaccel_when_configured(
    client: AsyncClient, auth_headers: dict, model_file, monkeypatch
):
    """設定 internal location 後改由 Nginx 送檔，後端只回標頭。"""
    monkeypatch.setattr(settings, "LOCAL_MODEL_XACCEL_LOCATION", "/protected-models")
    monkeypatch.setattr(settings, "LOCAL_MODEL_RATE_LIMIT_BYTES_PER_SEC", 5_000_000)

    response = await client.get(await _get_download_url(client, auth_headers))

    assert response.status_code == 200
    assert response.headers["x-accel-redirect"] == "/protected-models/flash-v5.gguf"
    assert response.headers["x-accel-limit-rate"] == "5000000"
    assert response.headers["content-disposition"] == 'attachment; filename="flash-v5.gguf"'
    # content-length 必須交給 Nginx 決定；留下 0 會讓 App 只收到 0 bytes
    assert "content-length" not in response.headers
    assert response.content == b""


# ============================================================
# 其他
# ============================================================

def test_build_download_url_encodes_token():
    """權杖以 query 傳遞時完整編碼，不會被特殊字元截斷。"""
    url = build_download_url("a.b+c/d=", "flash-v5.gguf", "http://127.0.0.1:8000/")
    assert url == (
        "http://127.0.0.1:8000/api/v1/local-model/download/flash-v5.gguf"
        "?token=a.b%2Bc%2Fd%3D"
    )


def test_access_log_filter_redacts_token():
    """存取日誌不得留下下載權杖（權杖等同一條可直接使用的下載網址）。"""
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:1234",
            "GET",
            "/api/v1/local-model/download/flash-v5.gguf?token=eyJhbGciOi.secret",
            "1.1",
            200,
        ),
        exc_info=None,
    )

    assert _DownloadTokenLogFilter().filter(record) is True
    assert "secret" not in record.getMessage()
    assert "token=REDACTED" in record.getMessage()


# ============================================================
# 第二顆模型：flash-stage-v2（詐騙階段判定）
# ============================================================

async def test_manifest_default_still_returns_detect_model(
    client: AsyncClient, auth_headers: dict, stage_model_file
):
    """兩顆都部署好時，不帶 ?model= 仍回偵測模型。

    已上架的 App 版本呼叫的就是這一支、沒有這個參數。第二顆是加上來的，
    不是改出來的——這條測試就是那句話的定義。
    """
    body = (await client.get(MANIFEST_URL, headers=auth_headers)).json()
    assert body["file_name"] == "flash-v5.gguf"
    assert body["sha256"] == MODEL_SHA256
    # 欄位仍然只有需求書那六個，一個都沒多
    assert set(body) == {
        "version",
        "file_name",
        "size_bytes",
        "sha256",
        "download_url",
        "expires_at",
    }


async def test_manifest_of_stage_model(
    client: AsyncClient, auth_headers: dict, stage_model_file
):
    """?model=stage 回階段模型，且格式與偵測模型完全相同（App 可重用同一支解析）。"""
    response = await client.get(
        MANIFEST_URL, headers=auth_headers, params={"model": "stage"}
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["version"] == "2.0"
    assert body["file_name"] == "flash-stage-v2.gguf"
    assert body["size_bytes"] == len(STAGE_BYTES)
    assert body["sha256"] == STAGE_SHA256
    assert body["download_url"].startswith(
        f"http://test{download_path('flash-stage-v2.gguf')}?token="
    )


async def test_manifest_unknown_model_id_404(
    client: AsyncClient, auth_headers: dict, stage_model_file
):
    """代號不存在 → 404（而不是默默回偵測模型那顆）。"""
    response = await client.get(
        MANIFEST_URL, headers=auth_headers, params={"model": "nope"}
    )
    assert response.status_code == 404


async def test_manifest_stage_not_deployed_503_but_detect_ok(
    client: AsyncClient, auth_headers: dict, model_file
):
    """階段模型沒部署時只有它自己回 503，偵測模型照常。"""
    stage = await client.get(MANIFEST_URL, headers=auth_headers, params={"model": "stage"})
    assert stage.status_code == 503
    assert (await client.get(MANIFEST_URL, headers=auth_headers)).status_code == 200


async def test_catalog_lists_both_models(
    client: AsyncClient, auth_headers: dict, stage_model_file
):
    """catalog 一次列出兩顆，各自帶自己的簽章網址。"""
    response = await client.get(CATALOG_URL, headers=auth_headers)
    assert response.status_code == 200, response.text

    models = {entry["model_id"]: entry for entry in response.json()["models"]}
    assert set(models) == {"detect", "stage"}
    assert models["detect"]["sha256"] == MODEL_SHA256
    assert models["stage"]["sha256"] == STAGE_SHA256
    assert models["detect"]["role"] and models["stage"]["role"]
    # 兩顆的網址各指各的檔案（不是同一組簽章換個檔名）
    assert download_path("flash-v5.gguf") in models["detect"]["download_url"]
    assert download_path("flash-stage-v2.gguf") in models["stage"]["download_url"]


async def test_catalog_requires_auth(client: AsyncClient, stage_model_file):
    """catalog 與 manifest 同樣需要登入。"""
    assert (await client.get(CATALOG_URL)).status_code == 401


async def test_catalog_skips_undeployed_model(
    client: AsyncClient, auth_headers: dict, model_file
):
    """階段模型沒部署時 catalog 只列偵測那顆，不會整份失敗。"""
    body = (await client.get(CATALOG_URL, headers=auth_headers)).json()
    assert [entry["model_id"] for entry in body["models"]] == ["detect"]


async def test_catalog_503_when_nothing_deployed(
    client: AsyncClient, auth_headers: dict, model_file, monkeypatch
):
    """一顆都沒部署 → 503，而不是一份空清單。

    空清單在 App 端會被讀成「這個版本沒有地端模式」，而不是「伺服器還沒佈好」。
    """
    monkeypatch.setattr(settings, "LOCAL_MODEL_PATH", "")
    response = await client.get(CATALOG_URL, headers=auth_headers)
    assert response.status_code == 503


async def test_download_stage_model(
    client: AsyncClient, auth_headers: dict, stage_model_file
):
    """階段模型可用自己的簽章下載，內容與 sha256 相符。"""
    manifest = await client.get(
        MANIFEST_URL, headers=auth_headers, params={"model": "stage"}
    )
    response = await client.get(manifest.json()["download_url"])

    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == STAGE_SHA256
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="flash-stage-v2.gguf"'
    )


async def test_stage_token_cannot_fetch_detect_model(
    client: AsyncClient, auth_headers: dict, stage_model_file
):
    """兩顆的簽章不能互用：階段模型的權杖要不到偵測模型（反之亦然）。"""
    stage_manifest = await client.get(
        MANIFEST_URL, headers=auth_headers, params={"model": "stage"}
    )
    stage_token = stage_manifest.json()["download_url"].split("token=")[1]
    detect_token = (await _get_download_url(client, auth_headers)).split("token=")[1]

    crossed = await client.get(
        download_path("flash-v5.gguf"), params={"token": stage_token}
    )
    assert crossed.status_code == 401

    reversed_ = await client.get(
        download_path("flash-stage-v2.gguf"), params={"token": detect_token}
    )
    assert reversed_.status_code == 401


async def test_stage_version_bump_only_expires_stage_urls(
    client: AsyncClient, auth_headers: dict, stage_model_file, monkeypatch
):
    """階段模型換版只讓它自己的舊網址失效，偵測模型的網址仍然可用。"""
    detect_url = await _get_download_url(client, auth_headers)
    stage_url = (
        await client.get(MANIFEST_URL, headers=auth_headers, params={"model": "stage"})
    ).json()["download_url"]

    monkeypatch.setattr(settings, "LOCAL_MODEL_STAGE_VERSION", "2.1")

    assert (await client.get(stage_url)).status_code == 401
    assert (await client.get(detect_url)).status_code == 200


async def test_stage_download_uses_xaccel_location(
    client: AsyncClient, auth_headers: dict, stage_model_file, monkeypatch
):
    """X-Accel 模式下，階段模型導向的是它自己的檔名（兩顆共用同一個 location）。"""
    monkeypatch.setattr(settings, "LOCAL_MODEL_XACCEL_LOCATION", "/protected-models")
    stage_url = (
        await client.get(MANIFEST_URL, headers=auth_headers, params={"model": "stage"})
    ).json()["download_url"]

    response = await client.get(stage_url)
    assert response.headers["x-accel-redirect"] == "/protected-models/flash-stage-v2.gguf"


def test_two_models_must_not_share_a_file_name():
    """設定檢查：兩顆同名會讓「以檔名反查模型」互相蓋掉，啟動時就要炸。"""
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="不可相同"):
        Settings(
            LOCAL_MODEL_FILE_NAME="same.gguf",
            LOCAL_MODEL_STAGE_FILE_NAME="same.gguf",
        )
