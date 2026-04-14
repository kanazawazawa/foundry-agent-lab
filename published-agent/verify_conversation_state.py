"""
会話ステート保持の検証:
  - 発行前（開発エンドポイント）: conversation API でマルチターン
  - 発行後（Agent Application）: Responses API でステートレス確認

手順:
  1. 「私の名前は田中です」と送る
  2. 「私の名前は何ですか？」と送る
  3. 2番目の回答に「田中」が含まれていれば会話ステートが保持されている

Usage:
    python experiments/verify_conversation_state.py
"""

import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from openai import OpenAI

load_dotenv()

ENDPOINT = os.environ["PROJECT_ENDPOINT"]
AGENT_NAME = os.environ.get("AGENT_NAME", "travel-expense-helpdesk")
BASE_URL = os.environ["AGENT_APP_BASE_URL"]

MSG1 = "私の名前は田中です。覚えてください。"
MSG2 = "私の名前は何ですか？"

SEPARATOR = "=" * 60


def test_dev_endpoint():
    """発行前: 開発エンドポイント（Conversations API）"""
    print(SEPARATOR)
    print("【検証1】発行前 — 開発エンドポイント (Conversations API)")
    print(SEPARATOR)

    credential = DefaultAzureCredential()
    project = AIProjectClient(endpoint=ENDPOINT, credential=credential)
    openai = project.get_openai_client()

    conversation = openai.conversations.create()
    print(f"Conversation ID: {conversation.id}\n")

    # メッセージ1
    print(f"→ 送信: {MSG1}")
    r1 = openai.responses.create(
        conversation=conversation.id,
        input=MSG1,
        extra_body={"agent_reference": {"name": AGENT_NAME, "type": "agent_reference"}},
    )
    print(f"← 応答: {r1.output_text}\n")

    # メッセージ2
    print(f"→ 送信: {MSG2}")
    r2 = openai.responses.create(
        conversation=conversation.id,
        input=MSG2,
        extra_body={"agent_reference": {"name": AGENT_NAME, "type": "agent_reference"}},
    )
    print(f"← 応答: {r2.output_text}\n")

    has_state = "田中" in r2.output_text
    print(f"結果: 会話ステート保持 = {'✅ YES' if has_state else '❌ NO'}")
    return has_state


def test_published_endpoint():
    """発行後: Agent Application（Responses API / ステートレス）"""
    print(SEPARATOR)
    print("【検証2】発行後 — Agent Application (Responses API)")
    print(SEPARATOR)

    credential = DefaultAzureCredential()
    token = credential.get_token("https://ai.azure.com/.default")

    client = OpenAI(
        api_key=token.token,
        base_url=BASE_URL,
        default_query={"api-version": "2025-11-15-preview"},
    )

    # メッセージ1
    print(f"→ 送信: {MSG1}")
    r1 = client.responses.create(input=MSG1)
    print(f"← 応答: {r1.output_text}")
    print(f"  Response ID: {r1.id}\n")

    # メッセージ2（前のレスポンスIDなし = 完全に独立したリクエスト）
    print(f"→ 送信: {MSG2}")
    r2 = client.responses.create(input=MSG2)
    print(f"← 応答: {r2.output_text}\n")

    has_state = "田中" in r2.output_text
    print(f"結果: 会話ステート保持 = {'✅ YES' if has_state else '❌ NO'}")
    return has_state


def main():
    print("会話ステート保持の検証\n")

    dev_result = test_dev_endpoint()
    print()
    pub_result = test_published_endpoint()

    print(f"\n{SEPARATOR}")
    print("【まとめ】")
    print(f"  発行前（開発エンドポイント）: {'✅ ステート保持' if dev_result else '❌ ステートなし'}")
    print(f"  発行後（Agent Application）:  {'✅ ステート保持' if pub_result else '❌ ステートなし'}")
    print(SEPARATOR)


if __name__ == "__main__":
    main()
