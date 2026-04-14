"""
Function Calling 付き旅費精算エージェントを作成する。

既存の travel-expense-helpdesk と同じナレッジ（file_search）に加え、
get_user_history Function Tool を持つ別エージェントを作成する。

Usage:
    python agent/create_fc_agent.py
"""

import os
import argparse
from pathlib import Path

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    FileSearchTool,
    FunctionTool,
    PromptAgentDefinition,
)

load_dotenv()

ENDPOINT = os.environ["PROJECT_ENDPOINT"]
MODEL = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-5.4")
AGENT_NAME = "travel-expense-helpdesk-fc"

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

KNOWLEDGE_FILES = [
    KNOWLEDGE_DIR / "travel-expense-policy.md",
    KNOWLEDGE_DIR / "system-manual.md",
    KNOWLEDGE_DIR / "faq.md",
]

# --- Function Tool 定義 ---
GET_USER_HISTORY_TOOL = FunctionTool(
    name="get_user_history",
    description=(
        "ユーザーの過去の問い合わせ履歴・申請履歴を取得する。"
        "ユーザーが「前回」「以前」「先日」「この前」など過去の相談内容に言及した場合に呼び出すこと。"
        "ユーザーIDはシステムが自動で特定するため、指定不要。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "取得する履歴件数（デフォルト: 5）",
            },
        },
        "required": [],
    },
    strict=False,
)

INSTRUCTIONS = """\
あなたは「TravelExpense（旅費精算システム）」のヘルプデスク AI アシスタントです。

## 役割
社員からの旅費精算に関する質問に、正確かつ丁寧に回答してください。

## ツール
1. **file_search** — 旅費規程・操作マニュアル・FAQ を検索する
2. **get_user_history** — ユーザーの過去の問い合わせ・申請履歴を取得する

## ルール
- 必ず file_search ツールを使って、旅費規程・操作マニュアル・FAQ を検索してから回答してください。
- ユーザーが「前回」「以前」「先日」「この前」「さっきの件」など過去の内容に言及した場合は、
  get_user_history を呼び出して履歴を確認してください。
  ユーザーの特定はシステムが自動で行うため、ユーザーIDを聞く必要はありません。
- 回答はナレッジドキュメントの内容に基づいてください。ドキュメントにない情報を推測で答えないでください。
- 回答には、参照した規程の条項番号やマニュアルのセクション番号を記載してください。
- ドキュメントに記載のないケースについては「規程に明記されていないため、経理部（内線: 3200）にお問い合わせください」と案内してください。
"""


def main():
    parser = argparse.ArgumentParser(description="Create FC agent")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--agent-name", default=AGENT_NAME)
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    project = AIProjectClient(endpoint=ENDPOINT, credential=credential)
    openai = project.get_openai_client()

    # 1. Vector Store 作成
    print("Creating vector store...")
    vector_store = openai.vector_stores.create(
        name=f"{args.agent_name}-knowledge",
    )
    print(f"  Vector Store: {vector_store.id}")

    # 2. ナレッジドキュメントをアップロード
    for file_path in KNOWLEDGE_FILES:
        print(f"  Uploading {file_path.name}...")
        with file_path.open("rb") as f:
            openai.vector_stores.files.upload_and_poll(
                vector_store_id=vector_store.id,
                file=f,
            )
    print(f"  {len(KNOWLEDGE_FILES)} files uploaded")

    # 3. Prompt Agent 作成（file_search + function calling）
    print(f"Creating agent: {args.agent_name}...")
    agent = project.agents.create_version(
        agent_name=args.agent_name,
        definition=PromptAgentDefinition(
            model=args.model,
            instructions=INSTRUCTIONS,
            tools=[
                FileSearchTool(vector_store_ids=[vector_store.id]),
                GET_USER_HISTORY_TOOL,
            ],
            temperature=0.1,
        ),
        description="旅費精算ヘルプデスク（Function Calling デモ用）",
    )
    print(f"  Agent: {agent.name} (version: {agent.version})")
    print("\nDone! Test the agent:")
    print(f"  python agent/test_fc_agent.py")


if __name__ == "__main__":
    main()
