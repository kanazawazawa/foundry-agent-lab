"""
旅費精算ヘルプデスクエージェントを Foundry に作成する。

1. Vector Store を作成
2. ナレッジドキュメント（旅費規程・操作マニュアル・FAQ）をアップロード
3. file_search ツール付きの Prompt Agent を作成

Usage:
    python agent/create_agent.py [--model MODEL] [--agent-name NAME]

Prerequisites:
    - Foundry プロジェクトが作成済み
    - モデル（gpt-4o 等）がデプロイ済み
    - 環境変数 PROJECT_ENDPOINT が設定済み
"""

import os
import argparse
from pathlib import Path

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FileSearchTool, PromptAgentDefinition

load_dotenv()

ENDPOINT = os.environ["PROJECT_ENDPOINT"]
MODEL = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-5.4")
AGENT_NAME = os.environ.get("AGENT_NAME", "travel-expense-helpdesk")

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

KNOWLEDGE_FILES = [
    KNOWLEDGE_DIR / "travel-expense-policy.md",
    KNOWLEDGE_DIR / "system-manual.md",
    KNOWLEDGE_DIR / "faq.md",
]

INSTRUCTIONS = """\
あなたは「TravelExpense（旅費精算システム）」のヘルプデスク AI アシスタントです。

## 役割
社員からの旅費精算に関する質問に、正確かつ丁寧に回答してください。
対象は以下の3つのカテゴリです。
1. 旅費規程（制度・ルール）に関する質問
2. TravelExpense システムの操作方法・トラブルに関する質問
3. よくある質問（FAQ）に記載のある一般的な質問

## ルール
- 必ず file_search ツールを使って、旅費規程・操作マニュアル・FAQ を検索してから回答してください。
- 回答はナレッジドキュメントの内容に基づいてください。ドキュメントにない情報を推測で答えないでください。
- 回答には、参照した規程の条項番号やマニュアルのセクション番号を記載してください。
- 役職によって金額や条件が異なる場合は、該当する役職ごとの情報を正確に提示してください。
- ドキュメントに記載のないケースについては「規程に明記されていないため、経理部（内線: 3200）にお問い合わせください」と案内してください。
- 他の社員の個人情報（申請状況、承認状況、経費明細など）を開示しないでください。
- システムの設定変更や承認の代行など、権限を超える操作は行わないでください。

## 重要: 2026年4月 緊急改定対応（※本番前に削除すること）
以下は2026年4月の緊急改定で変更された値です。
ナレッジドキュメント（file_search）はまだ更新されていないため、以下の項目については
file_search の検索結果よりもこちらの値を優先して回答してください。
- 一般社員の宿泊出張日当: 2,500円/泊（旧: 3,000円）
- 課長職の宿泊出張日当: 3,500円/泊（旧: 4,000円）
- 精算申請の期限: 出張完了後5営業日以内（旧: 10営業日）
- グリーン車利用条件: 課長職以上、片道200km以上（旧: 部長職以上、300km以上）
"""


def main():
    parser = argparse.ArgumentParser(description="Create travel expense helpdesk agent")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--agent-name", default=AGENT_NAME)
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    project = AIProjectClient(
        endpoint=ENDPOINT,
        credential=credential,
    )
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

    # 3. Prompt Agent 作成
    print(f"Creating agent: {args.agent_name}...")
    agent = project.agents.create_version(
        agent_name=args.agent_name,
        definition=PromptAgentDefinition(
            model=args.model,
            instructions=INSTRUCTIONS,
            tools=[FileSearchTool(vector_store_ids=[vector_store.id])],
            temperature=0.1,
        ),
        description="旅費精算システム TravelExpense のヘルプデスク AI エージェント",
    )
    print(f"  Agent: {agent.name} (version: {agent.version})")

    # 4. メタデータ保存
    metadata_dir = Path(__file__).parent.parent / ".foundry"
    metadata_dir.mkdir(exist_ok=True)
    metadata_path = metadata_dir / "agent-metadata.yaml"
    metadata_path.write_text(
        f"""\
agent:
  name: {agent.name}
  version: "{agent.version}"
  model: {args.model}
vectorStore:
  id: {vector_store.id}
  name: {vector_store.name}
project:
  endpoint: {ENDPOINT}
""",
        encoding="utf-8",
    )
    print(f"  Metadata saved to {metadata_path}")

    print("\nDone! Test the agent:")
    print(f"  python agent/test_agent.py")


if __name__ == "__main__":
    main()
