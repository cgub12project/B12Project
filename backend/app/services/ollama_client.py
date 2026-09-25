"""Ollama /api/chat 的共用呼叫層。

原本這段（POST /api/chat + structured outputs + 失敗原因分類）只存在於
RagService 的私有方法裡。詐騙階段判定（stage_service.py）需要用同一套呼叫方式
但換一顆模型與一份 schema，複製第二份的話，逾時訊息與錯誤分類就會開始各自漂移——
而這段的價值正是「能分辨逾時、連不上、模型不存在」，漂掉就白寫了。故抽出共用。

呼叫端各自決定模型、JSON Schema 與逾時；本模組只負責送出請求與把失敗轉成
一句看得懂的話（OllamaError），不做任何業務判斷。
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 提示詞含教科書與多筆中文案例／多輪對話，加大 context 避免被截斷
DEFAULT_NUM_CTX = 8192

# 低溫度，判斷結果穩定
DEFAULT_TEMPERATURE = 0.1

# 生成長度上限。不設的話 Ollama 預設無上限，而**無上限在這裡等於不會結束**：
# 撞到 num_ctx 之後 llama.cpp 會做 context shift（丟掉最舊的繼續生），
# 所以掉進重複迴圈的請求永遠不會自己停。實測 2026-08-24：階段評測 236 次呼叫中
# 有 2 次（約 1%）如此，server log 顯示 n_gen 一路長到 19,999 個 token、
# 速度全程 67 tok/s 都沒有掉——不是模型變慢，是它不吐停止符；呼叫端看到的
# 「逾時」其實是自己等到 OLLAMA_TIMEOUT 才斷線，而模型還在生。
#
# 上限訂 512 是因為兩條線的正常輸出都遠低於它：偵測的 assistant 最長 196 字
# （約 140 token，取自 data/finetune.jsonl 3000 筆）、階段判定實測 79–111 token。
# 也就是留了三倍以上的餘裕，正常回答不可能被截斷；而失控的請求會在約 7 秒後
# 回傳截斷的 JSON，解析失敗 → 呼叫端立刻走退路，不再卡滿兩分鐘。
#
# 這是上限，不是解法：真正讓它迴圈的是貪婪解碼（temperature 0）配上
# 沒有長度限制的 schema 字串欄位。上限只保證失敗得快。
DEFAULT_NUM_PREDICT = 512


class OllamaError(Exception):
    """呼叫 Ollama 失敗（連線、逾時、HTTP 錯誤）。訊息已是可直接顯示的說明。"""


def describe_error(
    exc: httpx.HTTPError, *, base_url: str, model: str, timeout: float
) -> str:
    """把 httpx 例外轉成能區分失敗原因的訊息。

    httpx 的逾時例外（ReadTimeout 等）`str()` 是空字串，若直接內插會得到
    「…請確認 Ollama 已啟動」加一個空冒號——逾時、連不上、模型不存在三種
    完全不同的故障長得一模一樣，評測時無從判斷是環境沒開還是推論太慢。
    故一律帶上例外類別名稱，並針對各失敗模式給對應的處置方向。
    """
    detail = str(exc) or "（無錯誤內容）"

    if isinstance(exc, httpx.TimeoutException):
        return (
            f"Ollama 推論逾時（{type(exc).__name__}，上限 "
            f"{timeout}s，模型 {model}）。"
            "模型已回應但沒在時限內跑完：可調高 OLLAMA_TIMEOUT，"
            "或確認是否因切換模型觸發重新載入權重。"
        )

    if isinstance(exc, httpx.ConnectError):
        return (
            f"無法連線到 Ollama（{base_url}）：{detail}。請確認 Ollama 服務已啟動。"
        )

    if isinstance(exc, httpx.HTTPStatusError):
        # Ollama 的錯誤原因在回應主體（例：模型不存在會回 404 + 說明）
        body = exc.response.text.strip()[:200] or "（回應主體為空）"
        return (
            f"Ollama 回傳 HTTP {exc.response.status_code}"
            f"（模型 {model}）：{body}"
        )

    return f"Ollama API 呼叫失敗（{type(exc).__name__}，模型 {model}）：{detail}"


async def chat(
    messages: list[dict[str, str]],
    *,
    base_url: str,
    model: str,
    timeout: float,
    response_schema: dict[str, Any] | str | None = None,
    num_ctx: int = DEFAULT_NUM_CTX,
    temperature: float = DEFAULT_TEMPERATURE,
    num_predict: int = DEFAULT_NUM_PREDICT,
    think: bool | None = None,
) -> str:
    """呼叫 Ollama /api/chat，回傳 LLM 的文字回應。

    response_schema 不為 None 時走 structured outputs（Ollama 0.5+），
    於解碼階段強制輸出符合 schema 的 JSON，小模型也不會漏欄位或給錯型別。

    ⚠ 傳 dict（完整 schema）時，**鍵的輸出順序不是你在 dict 裡寫的順序**：
    Ollama 會把 format 解析成 map 再重新序列化，鍵因而按字碼排序。2026-09-15 實測
    偵測線的五個中文鍵被排成「分析原因→可信度評分→是否為詐騙→詐騙類別→防詐建議」，
    模型得在下判斷之前先填分數，flash_v6 因此把可信度評分填成 0 或 25（同一批輸入
    不帶 schema 時是 85）。微調樣本的鍵序與這個順序不同，等於推論條件與訓練不一致。

    傳字串 "json" 則走純 JSON 模式：只保證輸出是合法 JSON，不指定鍵、不強制 enum，
    模型照自己訓練時的鍵序輸出。代價是漏欄位／型別錯要由呼叫端的解析器兜住。

    Raises:
        OllamaError: 連線、逾時或 HTTP 錯誤（訊息已含可辨識的失敗原因）。
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    if response_schema is not None:
        payload["format"] = response_schema
    # 思考型模型（實測 gemma4）預設會先輸出一段 thinking，而 Ollama 把它放在
    # message.thinking、不是 message.content——也就是說在思考結束前 content 是空字串。
    # 對本專案有兩個後果：一是延遲從 6 秒變成 27 秒，二是 num_predict 若在思考途中
    # 用完，回來的 content 是空的、解析必定失敗，而且看起來像「模型壞掉」而不是
    # 「被截斷」。非思考型模型收到這個欄位會直接忽略（實測 flash_v4.1 正常回應），
    # 所以送 False 是安全的；None 則整個欄位不送，維持呼叫端原本的行為。
    if think is not None:
        payload["think"] = think

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{base_url}/api/chat", json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise OllamaError(
            describe_error(exc, base_url=base_url, model=model, timeout=timeout)
        ) from exc

    return response.json().get("message", {}).get("content", "")
