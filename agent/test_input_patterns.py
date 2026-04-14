"""
Responses API の input に渡せる様々な type を Foundry Agent Service で検証する。

経費精算入力支援シナリオ: ユーザーの過去データを参考にして入力を支援する場合に
使えるパターンを比較テストする。

テスト対象（FunctionTool を登録していない通常エージェント travel-expense-helpdesk を使用）:
  0. function_call + function_call_output 事前注入（ベースライン）
  A. developer/system ロールメッセージ — Foundry が拒否（400）
  A2. instructions パラメータ          — agent_reference 使用時は拒否（400）
  A3. assistant ロール（EasyInput）    — HTTP OK だがエージェントがデータ無視
  B. item_reference                    — HTTP OK だがデータ反映は部分的
  C. file_search_call 結果の事前注入   — HTTP OK だがエージェントがデータ無視
  D. mcp_call（output 付き）           — HTTP OK だがエージェントがデータ無視

結論: function_call + function_call_output が唯一、データが確実に反映されるパターン。

Usage:
    python agent/test_input_patterns.py              # 全パターン実行
    python agent/test_input_patterns.py -p A         # パターン A のみ
    python agent/test_input_patterns.py -p 0,A3,C    # 複数選択
"""

import os
import sys
import json
import argparse

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

load_dotenv()

ENDPOINT = os.environ["PROJECT_ENDPOINT"]
# FunctionTool 未登録のエージェント（file_search のみ）
AGENT_NAME = os.environ.get("AGENT_NAME", "travel-expense-helpdesk")

QUESTION = "前回の大阪出張の精算はどうなりましたか？"

# ユーザー固有データ（本番では DB から取得する想定）
USER_HISTORY = {
    "user_id": "emp-12345",
    "history": [
        {
            "date": "2026-03-22",
            "type": "精算申請",
            "summary": "大阪出張（3/15-3/17）旅費精算。金額: 85,000円。ステータス: 承認済み。",
        },
        {
            "date": "2026-02-10",
            "type": "問い合わせ",
            "summary": "海外出張（ベトナム）の日当について質問。一般社員の東南アジア地域日当を回答。",
        },
    ],
}

HISTORY_JSON = json.dumps(USER_HISTORY, ensure_ascii=False)
HISTORY_TEXT = "\n".join(
    f"- {h['date']} [{h['type']}] {h['summary']}" for h in USER_HISTORY["history"]
)


def agent_ref():
    return {"agent_reference": {"name": AGENT_NAME, "type": "agent_reference"}}


# ===========================================================================
# パターン 0: function_call + function_call_output 事前注入（ベースライン）
# ===========================================================================
def test_pattern_0(openai, conv_id):
    """function_call + function_call_output 事前注入（検証済みベースライン）"""
    response = openai.responses.create(
        conversation=conv_id,
        input=[
            {
                "type": "function_call",
                "name": "get_user_history",
                "arguments": "{}",
                "call_id": "preloaded_001",
            },
            {
                "type": "function_call_output",
                "call_id": "preloaded_001",
                "output": HISTORY_JSON,
            },
            {"role": "user", "content": QUESTION},
        ],
        extra_body=agent_ref(),
    )
    return response


# ===========================================================================
# パターン A: developer ロールメッセージ
# ===========================================================================
def test_pattern_a(openai, conv_id):
    """developer ロール — システムレベルでユーザーデータを注入"""
    developer_content = (
        "以下はログインユーザー（emp-12345）の過去の経費精算履歴です。"
        "質問に回答する際、この履歴を参考にしてください。\n\n"
        f"{HISTORY_TEXT}"
    )

    # 試行 1: 明示的 message type + developer ロール
    try:
        response = openai.responses.create(
            conversation=conv_id,
            input=[
                {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": developer_content}],
                },
                {"role": "user", "content": QUESTION},
            ],
            extra_body=agent_ref(),
        )
        return response
    except Exception as e:
        print(f"  [message type + developer] ERROR: {type(e).__name__}: {e}")

    # 試行 2: system ロール（developer の別名）
    print("  → system ロールで再試行...")
    try:
        response = openai.responses.create(
            conversation=conv_id,
            input=[
                {
                    "type": "message",
                    "role": "system",
                    "content": [{"type": "input_text", "text": developer_content}],
                },
                {"role": "user", "content": QUESTION},
            ],
            extra_body=agent_ref(),
        )
        return response
    except Exception as e:
        print(f"  [message type + system] ERROR: {type(e).__name__}: {e}")

    # 試行 3: EasyInputMessage の system ロール
    print("  → EasyInputMessage system で再試行...")
    try:
        response = openai.responses.create(
            conversation=conv_id,
            input=[
                {"role": "system", "content": developer_content},
                {"role": "user", "content": QUESTION},
            ],
            extra_body=agent_ref(),
        )
        return response
    except Exception as e:
        print(f"  [EasyInputMessage system] ERROR: {type(e).__name__}: {e}")
        return None


# ===========================================================================
# パターン B: item_reference（前回レスポンスのアイテムを参照）
# ===========================================================================
def test_pattern_b(openai, conv_id):
    """item_reference — 前回レスポンスの出力アイテムを ID で参照"""
    # Step 1: 別の conversation でデータを含む応答を生成して store させる
    setup_conv = openai.conversations.create()
    print(f"  [setup] setup_conv={setup_conv.id}")

    setup_response = openai.responses.create(
        conversation=setup_conv.id,
        input=[
            {
                "type": "function_call",
                "name": "get_user_history",
                "arguments": "{}",
                "call_id": "setup_001",
            },
            {
                "type": "function_call_output",
                "call_id": "setup_001",
                "output": HISTORY_JSON,
            },
            {"role": "user", "content": "この履歴を覚えておいてください。"},
        ],
        extra_body=agent_ref(),
    )
    print(f"  [setup] response_id={setup_response.id}")
    print(f"  [setup] output items: {len(setup_response.output)}")
    for item in setup_response.output:
        print(f"    - id={item.id}, type={item.type}")

    # Step 2: 別の conversation で item_reference を使って参照
    ref_item_id = setup_response.output[-1].id

    # 試行 1: 新しい conversation で item_reference
    try:
        response = openai.responses.create(
            conversation=conv_id,
            input=[
                {"type": "item_reference", "id": ref_item_id},
                {"role": "user", "content": QUESTION},
            ],
            extra_body=agent_ref(),
        )
        return response
    except Exception as e:
        print(f"  [item_reference + new conv] ERROR: {type(e).__name__}: {e}")

    # 試行 2: conversation なし、item_reference のみ
    print("  → conversation なしで再試行...")
    try:
        response = openai.responses.create(
            input=[
                {"type": "item_reference", "id": ref_item_id},
                {"role": "user", "content": QUESTION},
            ],
            extra_body=agent_ref(),
        )
        return response
    except Exception as e:
        print(f"  [item_reference standalone] ERROR: {type(e).__name__}: {e}")

    # 試行 3: function_call_output アイテムを参照（メッセージではなく）
    print("  → function_call_output の item_reference で再試行...")
    # setup_response の input items から function_call_output の id を探す
    try:
        input_items = openai.responses.input_items.list(setup_response.id)
        for item in input_items.data:
            print(f"    input_item: id={item.id}, type={item.type}")
        fc_output_items = [i for i in input_items.data if i.type == "function_call_output"]
        if fc_output_items:
            fc_output_id = fc_output_items[0].id
            print(f"  → function_call_output id: {fc_output_id}")
            response = openai.responses.create(
                input=[
                    {"type": "item_reference", "id": fc_output_id},
                    {"role": "user", "content": QUESTION},
                ],
                extra_body=agent_ref(),
            )
            return response
    except Exception as e:
        print(f"  [item_reference fc_output] ERROR: {type(e).__name__}: {e}")
        return None


# ===========================================================================
# パターン C: file_search_call 結果の事前注入
# ===========================================================================
def test_pattern_c(openai, conv_id):
    """file_search_call — ファイル検索結果を事前に注入（検索を実行せずに結果だけ渡す）"""
    try:
        response = openai.responses.create(
            conversation=conv_id,
            input=[
                {
                    "type": "file_search_call",
                    "id": "fs_preloaded_001",
                    "status": "completed",
                    "queries": ["大阪出張 精算 履歴"],
                    "results": [
                        {
                            "file_id": "virtual_user_history",
                            "filename": "user_history_emp-12345.json",
                            "score": 0.95,
                            "text": HISTORY_TEXT,
                            "attributes": {},
                        }
                    ],
                },
                {"role": "user", "content": QUESTION},
            ],
            extra_body=agent_ref(),
        )
        return response
    except Exception as e:
        print(f"  [file_search_call] ERROR: {type(e).__name__}: {e}")
        return None


# ===========================================================================
# パターン A2: instructions パラメータ
# ===========================================================================
def test_pattern_a2(openai, conv_id):
    """instructions パラメータ — agent_reference 使用時は拒否される"""
    try:
        response = openai.responses.create(
            conversation=conv_id,
            input=[{"role": "user", "content": QUESTION}],
            instructions=(
                "以下はログインユーザー(emp-12345)の経費精算履歴。"
                "回答に必ず反映せよ。\n\n" + HISTORY_TEXT
            ),
            extra_body=agent_ref(),
        )
        return response
    except Exception as e:
        print(f"  [instructions] ERROR: {type(e).__name__}: {e}")
        return None


# ===========================================================================
# パターン A3: assistant ロール（EasyInputMessage）
# ===========================================================================
def test_pattern_a3(openai, conv_id):
    """assistant ロール（EasyInput）— HTTP OK だがエージェントがデータ無視"""
    try:
        response = openai.responses.create(
            conversation=conv_id,
            input=[
                {"role": "assistant", "content": "あなたの経費精算履歴:\n" + HISTORY_TEXT},
                {"role": "user", "content": QUESTION},
            ],
            extra_body=agent_ref(),
        )
        return response
    except Exception as e:
        print(f"  [assistant EasyInput] ERROR: {type(e).__name__}: {e}")
        return None


# ===========================================================================
# パターン D: mcp_call（output 付き）
# ===========================================================================
def test_pattern_d(openai, conv_id):
    """mcp_call（output 付き）— HTTP OK だがエージェントがデータ無視"""
    try:
        response = openai.responses.create(
            conversation=conv_id,
            input=[
                {
                    "type": "mcp_call",
                    "id": "mcp_001",
                    "name": "get_user_history",
                    "arguments": "{}",
                    "server_label": "user_data_server",
                    "output": HISTORY_JSON,
                    "status": "completed",
                },
                {"role": "user", "content": QUESTION},
            ],
            extra_body=agent_ref(),
        )
        return response
    except Exception as e:
        print(f"  [mcp_call] ERROR: {type(e).__name__}: {e}")
        return None


# ===========================================================================
# メイン
# ===========================================================================
def run_test(label, func, openai, conv_id):
    """テストを実行して結果を表示"""
    print(f"\n{'='*70}")
    print(f"パターン {label}: {func.__doc__}")
    print(f"{'='*70}")
    try:
        response = func(openai, conv_id)
        if response is None:
            print("  結果: ❌ エラー（上記参照）")
            return {"status": "ERROR", "response": None}
        print(f"\n  response_id: {response.id}")
        print(f"  output items: {len(response.output)}")
        print(f"\n  回答:\n  {response.output_text[:500]}")
        # 過去データが反映されているか確認
        text = response.output_text
        has_osaka = "大阪" in text
        has_amount = "85,000" in text or "85000" in text or "8万5" in text
        has_approved = "承認" in text
        print(f"\n  データ反映チェック:")
        print(f"    大阪出張: {'✅' if has_osaka else '❌'}")
        print(f"    金額 85,000円: {'✅' if has_amount else '❌'}")
        print(f"    承認済み: {'✅' if has_approved else '❌'}")
        data_ok = has_osaka and has_amount and has_approved
        return {"status": "OK", "data_reflected": data_ok, "response": response}
    except Exception as e:
        print(f"\n  結果: ❌ {type(e).__name__}: {e}")
        return {"status": "ERROR", "data_reflected": False, "response": None}


def main():
    parser = argparse.ArgumentParser(
        description="Responses API input type patterns test"
    )
    parser.add_argument(
        "-p",
        "--patterns",
        default="0,A,A2,A3,B,C,D",
        help="テストするパターン（カンマ区切り）。例: 0,A,A2,A3,B,C,D",
    )
    args = parser.parse_args()

    patterns_to_run = [p.strip().upper() for p in args.patterns.split(",")]

    credential = DefaultAzureCredential()
    project = AIProjectClient(endpoint=ENDPOINT, credential=credential)
    openai = project.get_openai_client()

    all_tests = {
        "0": ("0 (FC事前注入/ベースライン)", test_pattern_0),
        "A": ("A (developer/system ロール)", test_pattern_a),
        "A2": ("A2 (instructions パラメータ)", test_pattern_a2),
        "A3": ("A3 (assistant ロール)", test_pattern_a3),
        "B": ("B (item_reference)", test_pattern_b),
        "C": ("C (file_search_call 事前注入)", test_pattern_c),
        "D": ("D (mcp_call)", test_pattern_d),
    }

    results = {}
    for key in patterns_to_run:
        if key not in all_tests:
            print(f"⚠️  未知のパターン: {key}")
            continue
        label, func = all_tests[key]
        # パターンごとに新しい conversation を使う
        conv = openai.conversations.create()
        print(f"\n  Conversation: {conv.id}")
        results[key] = run_test(label, func, openai, conv.id)

    # サマリー
    print(f"\n\n{'='*70}")
    print("サマリー")
    print(f"{'='*70}")
    print(f"エージェント: {AGENT_NAME}（FunctionTool 未登録）")
    print(f"質問: {QUESTION}")
    print()
    for key in patterns_to_run:
        if key in results:
            label = all_tests[key][0]
            r = results[key]
            status = r["status"]
            data = r.get("data_reflected", False)
            if status == "ERROR":
                print(f"  ❌ パターン {label}: HTTP エラー")
            elif data:
                print(f"  ✅ パターン {label}: OK（データ反映あり）")
            else:
                print(f"  ⚠️  パターン {label}: HTTP OK だがデータ反映なし")


if __name__ == "__main__":
    main()
