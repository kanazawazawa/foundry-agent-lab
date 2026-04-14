"""
Function Calling 付きエージェントをテストする。

エージェントが get_user_history を呼んだら、クライアント側でモックデータを返し、
エージェントがそれを踏まえて回答する一連のフローを確認する。

Usage:
    python agent/test_fc_agent.py                                     # 対話モード
    python agent/test_fc_agent.py -q "前回の大阪出張の精算どうなった？"  # 単発質問
"""

import os
import json
import argparse

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

load_dotenv()

ENDPOINT = os.environ["PROJECT_ENDPOINT"]
AGENT_NAME = os.environ.get("FC_AGENT_NAME", "travel-expense-helpdesk-fc")

# --- モック: ユーザー履歴データ ---
MOCK_USER_HISTORY = {
    "emp-12345": [
        {
            "date": "2026-03-20",
            "type": "問い合わせ",
            "summary": "大阪出張（3/15-3/17）のグリーン車利用について質問。課長職のため利用可と回答。",
        },
        {
            "date": "2026-03-22",
            "type": "精算申請",
            "summary": "大阪出張（3/15-3/17）の旅費精算を申請済み。金額: 85,000円。ステータス: 承認済み。",
        },
        {
            "date": "2026-02-10",
            "type": "問い合わせ",
            "summary": "海外出張（ベトナム）の日当について質問。一般社員の東南アジア地域日当を回答。",
        },
    ],
}


# デモ用: 認証済みセッションのユーザーID（本番では認証基盤から取得）
SESSION_USER_ID = "emp-12345"


def execute_function(name: str, arguments: str) -> str:
    """Function call をクライアント側で実行し、結果 JSON を返す。

    エージェントの引数ではなく、認証済みセッションの user_id を使う。
    """
    args = json.loads(arguments)

    if name == "get_user_history":
        # エージェントは user_id を渡さない。セッションから取る
        user_id = SESSION_USER_ID
        limit = args.get("limit", 5)
        history = MOCK_USER_HISTORY.get(user_id, [])[:limit]
        if not history:
            return json.dumps(
                {"error": "履歴が見つかりません。"},
                ensure_ascii=False,
            )
        return json.dumps(
            {"user_id": user_id, "history": history},
            ensure_ascii=False,
        )

    return json.dumps({"error": f"Unknown function: {name}"}, ensure_ascii=False)


def send_message(openai, conversation_id: str, message: str) -> str:
    """
    メッセージを送信し、function_call があればクライアント側で実行して
    結果を返送する。最終的なテキスト応答を返す。
    """
    response = openai.responses.create(
        conversation=conversation_id,
        input=message,
        extra_body={
            "agent_reference": {"name": AGENT_NAME, "type": "agent_reference"},
        },
    )

    # function_call が含まれている間ループ
    while True:
        function_calls = [
            item for item in response.output if item.type == "function_call"
        ]
        if not function_calls:
            break

        # 各 function_call を実行して結果を集める
        tool_outputs = []
        for fc in function_calls:
            print(f"  [FC] {fc.name}({fc.arguments})")
            result = execute_function(fc.name, fc.arguments)
            print(f"  [FC] → {result[:200]}")
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": fc.call_id,
                    "output": result,
                }
            )

        # 結果を返送して次のレスポンスを取得（conversation ではなく previous_response_id でチェーン）
        response = openai.responses.create(
            input=tool_outputs,
            extra_body={
                "agent_reference": {"name": AGENT_NAME, "type": "agent_reference"},
            },
            previous_response_id=response.id,
        )

    return response.output_text


def main():
    parser = argparse.ArgumentParser(description="Test FC agent")
    parser.add_argument("-q", "--question", help="Single question (skip interactive mode)")
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    project = AIProjectClient(endpoint=ENDPOINT, credential=credential)
    openai = project.get_openai_client()

    conversation = openai.conversations.create()
    print(f"Conversation: {conversation.id}")
    print(f"Agent: {AGENT_NAME}")
    print()

    if args.question:
        print(f"Q: {args.question}")
        answer = send_message(openai, conversation.id, args.question)
        print(f"\nA: {answer}")
        return

    # 対話モード
    print("Function Calling デモ（quit で終了）")
    print(f"ログインユーザー: {SESSION_USER_ID}")
    print("ヒント: 「前回の大阪出張の件を教えて」と聞いてみてください")
    print("-" * 60)
    while True:
        question = input("\nQ: ").strip()
        if not question or question.lower() in ("quit", "exit", "q"):
            break
        answer = send_message(openai, conversation.id, question)
        print(f"\nA: {answer}")

    print("\n対話を終了しました。")


if __name__ == "__main__":
    main()
