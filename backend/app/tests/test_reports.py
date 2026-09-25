"""回報功能測試：電話回報、帳號回報、完整回報、個人紀錄與查詢端點。"""

from httpx import AsyncClient


async def test_phone_report_and_query(client: AsyncClient, auth_headers: dict):
    """電話回報 → 號碼建檔 → 列表／詳情查詢與風險升級。"""
    # 內容不足 10 字 → 422（pydantic 驗證）
    response = await client.post(
        "/api/v1/reports/phone/0912345678",
        json={"fraud_type": "投資詐騙", "content": "太短"},
        headers=auth_headers,
    )
    assert response.status_code == 422

    # 正常回報
    response = await client.post(
        "/api/v1/reports/phone/0912345678",
        json={
            "fraud_type": "投資詐騙",
            "content": "對方自稱投資老師，保證獲利要求加入群組操作",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["report_id"] > 0

    # 號碼列表可查到，風險為 mid（1 筆回報）
    response = await client.get(
        "/api/v1/phones", params={"search": "0912"}, headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["risk_level"] == "mid"
    assert body["items"][0]["report_count"] == 1

    # 電話詳情含社群回報（回報者名稱已遮罩）
    response = await client.get("/api/v1/phones/0912345678", headers=auth_headers)
    assert response.status_code == 200
    detail = response.json()
    assert len(detail["reports"]) == 1
    assert "*" in detail["reports"][0]["reporter"]

    # 再回報 4 次 → 累計 5 筆 → 升級為 high
    for i in range(4):
        await client.post(
            "/api/v1/reports/phone/0912345678",
            json={"fraud_type": "投資詐騙", "content": f"重複詐騙行為回報，第 {i + 2} 次回報"},
            headers=auth_headers,
        )
    response = await client.get("/api/v1/phones/0912345678", headers=auth_headers)
    assert response.json()["risk_level"] == "high"

    # 查無情報的號碼 → 404
    response = await client.get("/api/v1/phones/0999999999", headers=auth_headers)
    assert response.status_code == 404


async def test_account_report_and_detail(client: AsyncClient, auth_headers: dict):
    """帳號回報 → 建立可疑帳號檔案 → 威脅檔案查詢。"""
    response = await client.post(
        "/api/v1/reports/account",
        json={
            "fraud_type": "交友詐騙",
            "content": "假冒外籍工程師交友，誘導投資虛擬貨幣平台",
            "platform": "LINE",
            "account_name": "David_Chen",
            "account_id": "david123",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["case_number"].startswith("AC-")

    # 可疑帳號列表
    response = await client.get(
        "/api/v1/accounts", params={"platform": "LINE"}, headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    account_id = body["items"][0]["id"]
    assert body["items"][0]["report_count"] == 1

    # 威脅檔案詳情：含風險評分與觸發規則
    response = await client.get(f"/api/v1/accounts/{account_id}", headers=auth_headers)
    assert response.status_code == 200
    detail = response.json()
    assert 0 <= detail["risk_score"] <= 100
    assert any("交友詐騙" in rule for rule in detail["triggered_rules"])

    # 同帳號再次回報 → 累計而非新建
    await client.post(
        "/api/v1/reports/account",
        json={
            "fraud_type": "投資詐騙",
            "content": "同一帳號又來推薦投資平台，明顯詐騙話術",
            "platform": "LINE",
            "account_name": "David_Chen",
            "account_id": "david123",
        },
        headers=auth_headers,
    )
    response = await client.get(f"/api/v1/accounts/{account_id}", headers=auth_headers)
    assert response.json()["report_count"] == 2


async def test_full_report_and_mine(client: AsyncClient, auth_headers: dict):
    """完整回報產生 FR 案件編號；個人紀錄合併三種回報。"""
    # 完整回報
    response = await client.post(
        "/api/v1/reports/full",
        json={
            "fraud_type": "假冒公務機關",
            "content": "接到自稱刑事局來電，要求將存款轉入監管帳戶",
            "evidence_files": ["https://example.com/evidence1.png"],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["case_number"].startswith("FR-")

    # 再各提交一筆電話與帳號回報
    await client.post(
        "/api/v1/reports/phone/0287654321",
        json={"fraud_type": "假冒親友", "content": "假冒女兒稱手機遺失要求轉帳五萬元"},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/reports/account",
        json={
            "fraud_type": "購物詐騙",
            "content": "一頁式廣告賣名牌包，收款後即封鎖買家",
            "platform": "Facebook",
            "account_name": "精品特賣小舖",
        },
        headers=auth_headers,
    )

    # 個人回報紀錄：三種回報都在，依時間新到舊
    response = await client.get("/api/v1/reports/mine", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    kinds = {item["kind"] for item in body["items"]}
    assert kinds == {"phone", "account", "full"}


async def test_account_report_accepts_gmail_sender(
    client: AsyncClient, auth_headers: dict
):
    """回報詐騙信寄件人：platform 帶 "Gmail"、account_name 帶真實寄件位址。

    寄件位址是信箱連接讀回來的 From，不像 LINE 顯示名稱可能重複，
    因此沿用既有的帳號回報流程即可，不需要另外的端點。
    """
    response = await client.post(
        "/api/v1/reports/account",
        json={
            "fraud_type": "釣魚郵件",
            "content": "偽造銀行通知信，要求點擊連結輸入網銀帳號密碼",
            "platform": "Gmail",
            "account_name": "no-reply@bank-secure.example",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["case_number"].startswith("AC-")

    # 與社群平台回報走同一條路：可疑帳號檔案照樣建得出來
    listed = await client.get(
        "/api/v1/accounts", params={"platform": "Gmail"}, headers=auth_headers
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["account_name"] == "no-reply@bank-secure.example"


async def test_account_report_rejects_unknown_platform(
    client: AsyncClient, auth_headers: dict
):
    """platform 仍是封閉清單：沒列進去的平台要被擋下。"""
    response = await client.post(
        "/api/v1/reports/account",
        json={
            "fraud_type": "釣魚郵件",
            "content": "偽造銀行通知信，要求點擊連結輸入網銀帳號密碼",
            "platform": "Outlook",
            "account_name": "no-reply@bank-secure.example",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
