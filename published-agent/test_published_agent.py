"""
発行済み Agent Application を Responses API で呼び出すテスト。

開発用エンドポイント（プロジェクト経由）ではなく、
Agent Application の公開エンドポイントを使用する。

Usage:
    python experiments/test_published_agent.py
    python experiments/test_published_agent.py -q "大阪出張の日当は？"
"""

import os
import argparse

from dotenv import load_dotenv
from openai import OpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

load_dotenv()

# --- 設定 ---
# 応答 API エンドポイントからベース URL を構成
# （エンドポイント末尾の /responses?api-version=... を除いた部分）
BASE_URL = os.environ["AGENT_APP_BASE_URL"]

DEFAULT_QUESTION = "一般社員が大阪に宿泊出張する場合の日当はいくらですか？"


def main():
    parser = argparse.ArgumentParser(
        description="発行済み Agent Application テスト"
    )
    parser.add_argument("-q", "--question", default=DEFAULT_QUESTION)
    args = parser.parse_args()

    print(f"=== 発行済み Agent Application テスト ===")
    print(f"Base URL: {BASE_URL}")
    print(f"Question: {args.question}")
    print()

    # Azure 認証でトークンプロバイダーを作成
    credential = DefaultAzureCredential()
    token = credential.get_token("https://ai.azure.com/.default")

    # OpenAI クライアントを Agent Application エンドポイントに向ける
    client = OpenAI(
        api_key=token.token,
        base_url=BASE_URL,
        default_query={"api-version": "2025-11-15-preview"},
    )

    print("Sending request...")
    try:
        response = client.responses.create(input=args.question)
        print(f"\n--- Agent Application Response ---")
        print(response.output_text)
    except Exception as e:
        print(f"\n--- Error ---")
        print(f"{type(e).__name__}: {e}")
        print()
        if "403" in str(e):
            print("→ 呼び出し元に Azure AI User ロールが必要です")
        elif "401" in str(e):
            print("→ 認証トークンの問題です")
        elif "tool" in str(e).lower() or "authorization" in str(e).lower():
            print("→ Agent Application の ID にツールへの権限が不足しています")


if __name__ == "__main__":
    main()
