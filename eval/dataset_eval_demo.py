"""
架空データによるデータセット評価デモ。
Foundry Agent を使わず、事前に用意した response を含むデータで評価を実行する。
"""

import os
import sys
import json
import time
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

load_dotenv()

ENDPOINT = os.environ["PROJECT_ENDPOINT"]
MODEL = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-5.4")

# 架空のデータセット（response が既に含まれている）
FICTITIOUS_DATA = [
    {
        "query": "有給休暇の申請方法を教えてください",
        "response": "有給休暇は社内ポータルの「休暇申請」メニューから申請してください。申請は取得日の3営業日前までに行う必要があります。上長の承認後、人事部に自動通知されます。",
        "ground_truth": "有給休暇は社内ポータルの「休暇申請」メニューから申請します。取得日の3営業日前までに申請が必要で、上長の承認を経て人事部に通知されます。",
    },
    {
        "query": "リモートワークの申請条件は？",
        "response": "リモートワークは週3日まで利用可能です。事前に上長の承認が必要で、業務内容がリモート対応可能であることが条件です。",
        "ground_truth": "リモートワークは週3日まで利用可能で、事前に上長の承認が必要です。業務内容がリモート対応可能であることが条件となります。",
    },
    {
        "query": "経費精算の締め日はいつですか？",
        "response": "経費精算の締め日は毎月25日です。翌月10日に振り込まれます。",
        "ground_truth": "経費精算の締め日は毎月末日です。翌月15日に振り込まれます。",
    },
    {
        "query": "社内研修の受講方法は？",
        "response": "社内研修は Learning Portal から申し込みできます。必須研修は年度初めに通知され、任意研修は随時申し込み可能です。受講後はアンケート回答が必要です。",
        "ground_truth": "社内研修は Learning Portal から申し込みます。必須研修は年度初めに通知、任意研修は随時申し込み可能。受講後のアンケート回答が必須です。",
    },
]


def main():
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=ENDPOINT, credential=credential)
    oc = project_client.get_openai_client()

    # 1. JSONL ファイルを一時作成してアップロード
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        for item in FICTITIOUS_DATA:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        tmp_path = f.name

    print(f"Temp dataset: {tmp_path}")

    # Azure AI datasets API でアップロード（.jsonl 拡張子が保持される）
    ds = project_client.datasets.upload_file(
        name="fictitious-dataset-eval-demo",
        version=str(int(time.time())),
        file_path=tmp_path,
    )
    print(f"Dataset uploaded: {ds.id}")
    Path(tmp_path).unlink()

    # 2. Evaluation 作成（response はデータに含まれている）
    eval_obj = oc.evals.create(
        name="dataset-eval-demo",
        data_source_config={
            "type": "custom",
            "item_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "response": {"type": "string"},
                    "ground_truth": {"type": "string"},
                },
                "required": ["query", "response", "ground_truth"],
            },
            "include_sample_schema": False,
        },
        testing_criteria=[
            {
                "type": "azure_ai_evaluator",
                "name": "response_completeness",
                "evaluator_name": "builtin.response_completeness",
                "initialization_parameters": {"deployment_name": MODEL},
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                    "ground_truth": "{{item.ground_truth}}",
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "coherence",
                "evaluator_name": "builtin.coherence",
                "initialization_parameters": {"deployment_name": MODEL},
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                },
            },
        ],
    )
    print(f"Evaluation created: {eval_obj.id}")

    # 3. Run 作成
    # Azure AI Evals API ではモデルターゲットが必須だが、
    # evaluator の data_mapping は {{item.response}} を参照するため
    # モデル出力 (sample) は使わない。max_tokens=1 でコスト最小化。
    eval_run = oc.evals.runs.create(
        eval_id=eval_obj.id,
        name="dataset-eval-demo-run",
        data_source={
            "type": "azure_ai_target_completions",
            "source": {"type": "file_id", "id": ds.id},
            "input_messages": {
                "type": "template",
                "template": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": {"type": "input_text", "text": "dummy"},
                    }
                ],
            },
            "target": {"type": "azure_ai_model", "model": MODEL},
            "sampling_params": {"max_completions_tokens": 1},
        },
    )
    print(f"Run created: {eval_run.id}, status: {eval_run.status}")

    # 4. ポーリング
    print("\nPolling...")
    for _ in range(60):
        run = oc.evals.runs.retrieve(run_id=eval_run.id, eval_id=eval_obj.id)
        print(f"  Status: {run.status}")
        if run.status in ("completed", "failed", "canceled"):
            break
        time.sleep(10)

    # 5. 結果表示
    if run.status == "failed":
        print(f"FAILED: {run.error}")
        sys.exit(1)

    print(f"\nResult counts: {run.result_counts}")
    print(f"Report URL: {run.report_url}")

    items = list(oc.evals.runs.output_items.list(run_id=run.id, eval_id=eval_obj.id))
    for item in items:
        query = item.datasource_item.get("query", "") if item.datasource_item else ""
        results_str = []
        for r in getattr(item, "results", []):
            name = getattr(r, "name", "?")
            score = getattr(r, "score", None)
            passed = getattr(r, "passed", None)
            results_str.append(f"{name}={score}({'PASS' if passed else 'FAIL'})")
        print(f"  {query[:40]:40s} → {', '.join(results_str)}")

    print("\nDone! Check Foundry Portal for details.")


if __name__ == "__main__":
    main()
