"""
旅費精算ヘルプデスクエージェントに質問を送ってテストする。

Usage:
    python agent/test_agent.py                          # 対話モード
    python agent/test_agent.py -q "大阪出張の日当は？"   # 単発質問
"""

import os
import argparse

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

load_dotenv()

ENDPOINT = os.environ["PROJECT_ENDPOINT"]
AGENT_NAME = os.environ.get("AGENT_NAME", "travel-expense-helpdesk")


def send_message(openai, conversation_id: str, message: str) -> str:
    """Send a message and return the agent's response text."""
    response = openai.responses.create(
        conversation=conversation_id,
        input=message,
        extra_body={
            "agent_reference": {"name": AGENT_NAME, "type": "agent_reference"},
        },
    )
    return response.output_text


def main():
    parser = argparse.ArgumentParser(description="Test travel expense helpdesk agent")
    parser.add_argument("-q", "--question", help="Single question (skip interactive mode)")
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    project = AIProjectClient(endpoint=ENDPOINT, credential=credential)
    openai = project.get_openai_client()

    conversation = openai.conversations.create()
    print(f"Conversation: {conversation.id}\n")

    if args.question:
        print(f"Q: {args.question}")
        answer = send_message(openai, conversation.id, args.question)
        print(f"A: {answer}")
        return

    # 対話モード
    print("旅費精算ヘルプデスクエージェントとの対話モード（quit で終了）")
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
