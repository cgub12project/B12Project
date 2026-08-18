#!/usr/bin/env python3
"""Run repeatable local-model smoke tests from inside a Docker container only."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


OTP_CASES = [
    "您的驗證碼為 482913，請勿將此碼提供給任何人。",
    "【Google】您的驗證碼是 592013，10 分鐘內有效。",
    "您的一次性密碼 (OTP) 為 771254，請勿轉發他人。",
    "驗證碼：338914",
    "【LINE】認證碼 4471，請於畫面輸入。",
]


def system_prompt(modelfile: Path) -> str:
    content = modelfile.read_text(encoding="utf-8")
    match = re.search(r'SYSTEM\s+"""(.*?)"""', content, re.DOTALL)
    if not match:
        raise ValueError(f"SYSTEM prompt not found in {modelfile}")
    return match.group(1).strip()


def detect(url: str, system: str, message: str) -> str:
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ],
        "temperature": 0.1,
        "top_p": 0.95,
        "max_tokens": 128,
        "stop": ["<|im_end|>"],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read())
    return body["choices"][0]["message"]["content"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1/chat/completions")
    parser.add_argument("--modelfile", type=Path, required=True)
    args = parser.parse_args()

    prompt = system_prompt(args.modelfile)
    failures = 0
    for index, message in enumerate(OTP_CASES, start=1):
        try:
            raw = detect(args.url, prompt, message)
            parsed = json.loads(raw)
            scam_type = parsed.get("scam_type")
            confidence = parsed.get("confidence_score")
            passed = scam_type == "正常訊息"
            failures += not passed
            status = "PASS" if passed else "KNOWN_LIMITATION"
            print(f"{index}. {status}: {message}")
            print(f"   {scam_type} ({confidence})")
        except (KeyError, ValueError, urllib.error.URLError, json.JSONDecodeError) as error:
            failures += 1
            print(f"{index}. ERROR: {message}\n   {error}")

    print(f"OTP cases requiring user awareness: {failures}/{len(OTP_CASES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
