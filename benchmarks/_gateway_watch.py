"""Wait until the live gateway emits non-empty content again; prints READY once."""
from __future__ import annotations

import time
from pathlib import Path

import requests

KEY = Path(r"C:\Users\Administrator\Desktop\new_api_key.txt").read_text(encoding="utf-8").strip()
URL = "http://192.168.128.161:3000/v1/chat/completions"
while True:
    try:
        response = requests.post(
            URL, headers={"Authorization": f"Bearer {KEY}"},
            json={"model": "deepseek-flash", "max_tokens": 5,
                  "messages": [{"role": "user", "content": "ping"}]}, timeout=20)
        text = ((response.json().get("choices") or [{}])[0]
                .get("message", {}).get("content") or "")
        if response.status_code == 200 and text.strip():
            print("READY", text.strip()[:10], flush=True)
            break
    except Exception:
        pass
    time.sleep(30)
