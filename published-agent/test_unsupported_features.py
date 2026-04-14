"""
発行済みエンドポイントで「サポートされていない」会話機能が本当に使えないか検証。

1. previous_response_id によるチェーン
2. conversations.create() による会話オブジェクト作成
"""

import os
from dotenv import load_dotenv
from openai import OpenAI
from azure.identity import DefaultAzureCredential

load_dotenv()

BASE_URL = os.environ["AGENT_APP_BASE_URL"]

credential = DefaultAzureCredential()
token = credential.get_token("https://ai.azure.com/.default")

client = OpenAI(
    api_key=token.token,
    base_url=BASE_URL,
    default_query={"api-version": "2025-11-15-preview"},
)

SEPARATOR = "=" * 60

# --- テスト1: previous_response_id ---
print(SEPARATOR)
print("【テスト1】previous_response_id によるチェーン")
print(SEPARATOR)
try:
    r1 = client.responses.create(input="私の名前は田中です。覚えてください。")
    print(f"→ 1回目 OK (id={r1.id})")
    print(f"  応答: {r1.output_text[:100]}\n")

    r2 = client.responses.create(
        input="私の名前は何ですか？",
        previous_response_id=r1.id,
    )
    print(f"→ 2回目 OK (id={r2.id})")
    print(f"  応答: {r2.output_text[:200]}\n")

    has_name = "田中" in r2.output_text
    print(f"結果: previous_response_id = {'✅ 動作する' if has_name else '❌ 文脈なし'}")
except Exception as e:
    print(f"→ エラー: {type(e).__name__}: {e}")

print()

# --- テスト2: conversations.create() ---
print(SEPARATOR)
print("【テスト2】conversations.create()")
print(SEPARATOR)
try:
    conv = client.conversations.create()
    print(f"→ 会話作成 OK (id={conv.id})")

    r1 = client.responses.create(
        conversation=conv.id,
        input="私の名前は田中です。覚えてください。",
    )
    print(f"→ 1回目 OK: {r1.output_text[:100]}\n")

    r2 = client.responses.create(
        conversation=conv.id,
        input="私の名前は何ですか？",
    )
    print(f"→ 2回目 OK: {r2.output_text[:200]}\n")

    has_name = "田中" in r2.output_text
    print(f"結果: conversations = {'✅ 動作する' if has_name else '❌ 文脈なし'}")
except Exception as e:
    print(f"→ エラー: {type(e).__name__}: {e}")
