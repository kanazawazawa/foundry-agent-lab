"""
response_completeness のみの評価を作成・実行する。
ポータル UI の不具合（built-in evaluator に不要なプロンプト入力が必須）を回避するため、
SDK 経由でクリーンな評価を作成する。

Usage:
    python eval/create_eval_completeness_only.py
    python eval/create_eval_completeness_only.py --eval-name my-eval
    python eval/create_eval_completeness_only.py --agent-name my-agent
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

load_dotenv()

ENDPOINT = os.environ["PROJECT_ENDPOINT"]
MODEL = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-5.4")
AGENT_NAME = os.environ.get("AGENT_NAME", "travel-expense-helpdesk")
EVAL_NAME = "travel-expense-accuracy-20260414"


def upload_dataset(project_client: AIProjectClient, dataset_path: str) -> str:
    name = Path(dataset_path).stem
    version = datetime.now().strftime("%Y%m%d%H%M%S")
    ds = project_client.datasets.upload_file(
        name=name,
        version=version,
        file_path=dataset_path,
    )
    print(f"Dataset uploaded: {ds.id} ({name})")
    return ds.id


def create_eval_and_run(client, data_id: str, agent_name: str, eval_name: str):
    data_source_config = {
        "type": "custom",
        "item_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "ground_truth": {"type": "string"},
                "context": {"type": "string"},
            },
            "required": ["query", "ground_truth"],
        },
        "include_sample_schema": True,
    }

    # response_completeness のみ
    testing_criteria = [
        {
            "type": "azure_ai_evaluator",
            "name": "response_completeness",
            "evaluator_name": "builtin.response_completeness",
            "initialization_parameters": {"deployment_name": MODEL},
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{sample.output_text}}",
                "ground_truth": "{{item.ground_truth}}",
            },
        },
    ]

    eval_obj = client.evals.create(
        name=eval_name,
        data_source_config=data_source_config,
        testing_criteria=testing_criteria,
    )
    print(f"Evaluation created: {eval_obj.id} ({eval_name})")

    input_messages = {
        "type": "template",
        "template": [
            {
                "type": "message",
                "role": "user",
                "content": {"type": "input_text", "text": "{{item.query}}"},
            }
        ],
    }

    data_source = {
        "type": "azure_ai_target_completions",
        "source": {"type": "file_id", "id": data_id},
        "input_messages": input_messages,
        "target": {"type": "azure_ai_agent", "name": agent_name},
    }

    eval_run = client.evals.runs.create(
        eval_id=eval_obj.id,
        name=f"{eval_name}-run",
        data_source=data_source,
    )
    print(f"Evaluation run created: {eval_run.id}, status: {eval_run.status}")

    return eval_obj, eval_run


def poll_run(client, eval_id: str, run_id: str, timeout: int = 600):
    start = time.time()
    while True:
        run = client.evals.runs.retrieve(run_id=run_id, eval_id=eval_id)
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] Status: {run.status}")

        if run.status in ("completed", "failed", "canceled"):
            return run

        if elapsed > timeout:
            print("Timeout waiting for evaluation run")
            sys.exit(1)

        time.sleep(10)


def print_results(client, eval_id: str, run):
    if run.status == "failed":
        print(f"\nEvaluation FAILED: {run.error}")
        return False

    print(f"\nReport URL: {run.report_url}")

    output_items = list(
        client.evals.runs.output_items.list(run_id=run.id, eval_id=eval_id)
    )

    evaluator_results = {}
    failed_queries = []

    for item in output_items:
        query = ""
        if hasattr(item, "datasource_item") and item.datasource_item:
            query = item.datasource_item.get("query", "")

        for result in getattr(item, "results", []):
            if hasattr(result, "name"):
                name = result.name or "unknown"
                passed = getattr(result, "passed", False)
                score = getattr(result, "score", None)
            else:
                name = result.get("name", "unknown")
                passed = result.get("passed", False)
                score = result.get("score")

            if name not in evaluator_results:
                evaluator_results[name] = {"passed": 0, "failed": 0, "total": 0}
            evaluator_results[name]["total"] += 1
            if passed:
                evaluator_results[name]["passed"] += 1
            else:
                evaluator_results[name]["failed"] += 1
                failed_queries.append(
                    {"evaluator": name, "query": query, "score": score}
                )

    print("\n=== Evaluation Results ===")
    all_pass = True
    for name, counts in sorted(evaluator_results.items()):
        rate = counts["passed"] / counts["total"] if counts["total"] > 0 else 0
        status = "PASS" if rate >= 0.8 else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  {name}: {counts['passed']}/{counts['total']} ({rate:.0%}) [{status}]")

    if failed_queries:
        print(f"\n  Failed items:")
        for fq in failed_queries:
            label = fq["query"][:60] or "(no query)"
            print(f"    [{fq['evaluator']}] score={fq['score']}: {label}")

    print(f"\nOverall: {'PASS' if all_pass else 'FAIL'}")

    results_dir = Path(".foundry/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{run.id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            [item.model_dump() if hasattr(item, "model_dump") else item for item in output_items],
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Results saved to {out_path}")

    return all_pass


def main():
    parser = argparse.ArgumentParser(description="Run response_completeness-only evaluation")
    parser.add_argument("--dataset", default="eval/data/accuracy-test.jsonl")
    parser.add_argument("--agent-name", default=AGENT_NAME)
    parser.add_argument("--eval-name", default=EVAL_NAME)
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        endpoint=ENDPOINT,
        credential=credential,
    )
    openai_client = project_client.get_openai_client()

    # 1. Upload dataset
    data_id = upload_dataset(project_client, args.dataset)

    # 2. Create eval + run (response_completeness only)
    eval_obj, eval_run = create_eval_and_run(
        openai_client, data_id, args.agent_name, args.eval_name,
    )

    # 3. Poll
    print("\nPolling for completion...")
    completed_run = poll_run(openai_client, eval_obj.id, eval_run.id)

    # 4. Results
    all_pass = print_results(openai_client, eval_obj.id, completed_run)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
