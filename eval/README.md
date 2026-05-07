# 評価駆動サイクル（Eval-Driven Improvement）

AI エージェントの品質を CI で自動評価し、不合格なら Copilot Coding Agent が修正 PR を作成する。

## スクリプト

| ファイル | 内容 |
|----------|------|
| `run_evaluation.py` | バッチ評価（response_completeness + coherence） |
| `create_eval_completeness_only.py` | response_completeness のみの評価 |
| `dataset_eval_demo.py` | 架空データによるデータセット評価デモ（Agent 不要） |
| `data/accuracy-test.jsonl` | agent/ のテストケース（6件 + ground_truth + context） |

---

## ユースケース

このデモで紹介する「評価 → 検知 → 修正」の自動パイプラインは、以下のようなシーンで有効です。

| シーン | 何が起きるか | 評価パイプラインがあると |
|--------|-------------|----------------------|
| **Instructions / プロンプトの変更** | 意図しない回答品質の劣化 | 変更直後に CI で検知し、自動修正フローへ |
| **モデルの移行**（例: gpt-4o → gpt-5.4） | 同じプロンプトでも挙動が変わりうる | 同じテストケースを流すだけで回帰を定量検証 |
| **ナレッジ（社内規程等）の更新** | Agent が古い情報を返す可能性 | ground_truth を更新して評価すれば不整合を即検出 |

いずれも **同じ eval-data.json + 同じワークフロー** で対応でき、評価基盤を一度作れば継続的に品質を守れます。

---

## 概要

AI エージェントの品質を CI で自動評価し、不合格なら Copilot Coding Agent が自動で修正 PR を作成する——そんな **評価駆動の改善サイクル** を、旅費精算ヘルプデスク Agent を題材にデモします。

### このデモで見せること

| # | フェーズ | 主体 | 内容 |
|---|---------|------|------|
| 1 | 評価 | GitHub Actions | Agent に 6 件のテストケースを実行し、品質を自動評価 |
| 2 | 検知 | GitHub Actions | Pass Rate < 100% を検知し、GitHub Issue を自動作成 |
| 3 | 修正 | Copilot Coding Agent | Issue から原因を特定し、修正 PR を Draft で作成 |
| 4 | レビュー | 人間 (Human in the Loop) | PR の内容を確認し、マージ可否を判断 |

### 使用技術

- **Microsoft Foundry** — Prompt Agent + file_search + gpt-5.4
- **Foundry cloud evaluation** — response_completeness / coherence の 2 評価器
- **GitHub Actions** — `microsoft/ai-agent-evals@v3-beta` + OpenAI Evals API でスコア判定
- **Copilot Coding Agent** — Issue 自動アサインで修正 PR を自動生成

---

## シナリオ設定

架空の旅費精算システム「TravelExpense」の社内ヘルプデスク Agent に、意図的なバグを仕込んでいます。

### 仕込んだバグ（`agent/create_agent.py` の Instructions 内「緊急改定対応」セクション）

| 項目 | バグ入りの回答 | 正しい回答（ナレッジ準拠） |
|------|---------------|--------------------------|
| 一般社員の宿泊出張日当 | 2,500円/泊 | 3,000円/泊（第5条） |
| グリーン車利用条件 | 課長職以上・200km以上 | 部長職以上・300km以上（第4条4項） |
| 精算申請期限 | 5営業日以内 | 10営業日以内（第11条） |

### テストケース（6件）

| # | 質問 | 期待結果 | バグ影響 |
|---|------|---------|---------|
| 1 | 大阪出張（一般社員）の日当は？ | 3,000円/泊 | FAIL — 2,500円と誤回答 |
| 2 | 課長の東京→博多グリーン車は？ | 使えない | FAIL — 使えると誤回答 |
| 3 | 精算の提出期限は？ | 10営業日以内 | FAIL — 5営業日と誤回答 |
| 4 | タクシー利用の条件は？ | 終電後 or 荷物20kg超 | PASS |
| 5 | 領収書が必要な金額は？ | 1,000円以上 | PASS |
| 6 | 出張申請の承認者は？ | 所属部門の部長 | PASS |

→ **3/6 が FAIL（50%）** になることを前提としたデモです。

---

## デモ手順

### 1. 評価を実行する

GitHub リポジトリの **Actions** タブを開き:

1. 左メニューから **"Agent Evaluation"** を選択
2. **"Run workflow"** をクリック（branch: main、Agent ID はデフォルトのまま）
3. 評価が開始される（所要時間: 約 10 分）

> 評価が走っている間に、仕組みの説明やリポジトリ構成の紹介を行います。

### 2. 結果を確認する

評価完了後、以下が自動的に起きます:

1. **Check Pass Rate** ステップが OpenAI Evals API から結果を取得
   - `response_completeness`: 3/6 (50.0%)
   - `coherence`: 6/6 (100.0%)
   - → **FAIL: 3/6 passed, 3 failed**
2. **GitHub Issue が自動作成** される（タイトル: `Agent evaluation failed: travel-expense-helpdesk:1`）
3. **Copilot Coding Agent が Issue に自動アサイン** される

### 3. Copilot Coding Agent の修正を確認する

Copilot Coding Agent がアサインされると:

1. リポジトリのコードと評価データを分析
2. `agent/create_agent.py` の Instructions 内「緊急改定対応」セクションがバグの原因と特定
3. 該当セクションを削除する **修正 PR を Draft で作成**

### 4. Human in the Loop

> 「Coding Agent が修正を提案しましたが、最終的にマージするかどうかは人間が判断します。Agent の Instructions は業務ルールに直結するため、自動マージではなく人間のレビューを挟むのが実運用では重要です。」

---

## デモのリセット

PR をマージしない限り main は「バグ入り」のままなので、**リセットなしで何度でもデモ可能** です。

Issue/PR をきれいにしたい場合:
```bash
gh issue list --state open | awk '{print $1}' | xargs -I{} gh issue close {}
gh pr list --state open | awk '{print $1}' | xargs -I{} gh pr close {}
```

---

## 補足情報

### Foundry 環境

- デプロイごとに新環境が作成される（`rg-agent-eval-demo-{suffix}` / `ai-eval-{suffix}`）
- Vector Store: `.foundry/agent-metadata.yaml` に記録
- 評価結果: Foundry Portal の「評価」タブで一覧可能

### 評価器の選定理由

| 評価器 | 役割 | 採用理由 |
|--------|------|---------|
| **response_completeness** | ground_truth との照合（スコア 1-5 + 理由） | バグ検出のメイン。失敗理由が分かりやすい |
| **coherence** | 回答の論理性・構造の評価 | 品質の多角的評価。常に PASS になるため対比に使える |
| ~~similarity~~ | スコアのみ（理由なし） | 不採用: max_tokens:1 でスコアだけ返すためデモ映えしない |

---

## 参考リンク

### エバリュエーター リファレンス

| リンク | 内容 |
|--------|------|
| [組み込みエバリュエーター一覧](https://learn.microsoft.com/ja-jp/azure/foundry/concepts/built-in-evaluators) | 全カテゴリのエバリュエーター一覧。General Purpose / Textual Similarity / RAG / Risk & Safety / Agent / Azure OpenAI Graders |
| [RAG エバリュエーター](https://learn.microsoft.com/ja-jp/azure/foundry/concepts/evaluation-evaluators/rag-evaluators) | **response_completeness** が属するカテゴリ。ground_truth に対する recall（重要情報の欠落がないか）を測定。スコア 1-5 + reason |
| [汎用エバリュエーター](https://learn.microsoft.com/ja-jp/azure/foundry/concepts/evaluation-evaluators/general-purpose-evaluators) | **coherence** が属するカテゴリ。回答の論理的一貫性・構造を測定。スコア 1-5 + reason |
| [テキスト類似性エバリュエーター](https://learn.microsoft.com/ja-jp/azure/foundry/concepts/evaluation-evaluators/textual-similarity-evaluators) | **similarity** が属するカテゴリ。ドキュメント上は reason ありだが、実際は `max_tokens:1` の short モデルでスコアのみ返却 |

### 評価の実行方法

| リンク | 内容 |
|--------|------|
| [AI エージェントを評価する](https://learn.microsoft.com/ja-jp/azure/foundry/observability/how-to/evaluate-agent) | Foundry Agent の評価チュートリアル。エバリュエーター選択・データセット作成・評価実行・結果解釈の一連の流れ |
| [SDK から評価を実行する](https://learn.microsoft.com/ja-jp/azure/foundry/how-to/develop/cloud-evaluation?tabs=python) | Python SDK によるバッチ評価の詳細。データセット評価・エージェントターゲット評価・合成データ評価などのシナリオ別ガイド |
| [Foundry ポータルから評価を実行する](https://learn.microsoft.com/ja-jp/azure/foundry/how-to/evaluate-generative-ai-app) | ポータル UI での評価作成手順。エバリュエーター選択・データマッピング・結果確認の操作方法 |
| [GitHub Actions で評価を実行する](https://learn.microsoft.com/ja-jp/azure/foundry/how-to/evaluation-github-action) | `microsoft/ai-agent-evals` Action の使い方。CI/CD での自動評価ワークフロー構成・データファイル形式・出力レポート |

---

## 技術 FAQ

### Q. Actions から Foundry Eval はどうやって呼んでいる？

`.github/workflows/eval.yml` で `microsoft/ai-agent-evals@v3-beta` Action を使っている。

1. `azure/login@v2` で OIDC 認証（Federated Credential）
2. Action に `azure-ai-project-endpoint` / `deployment-name: gpt-5.4` / `agent-ids` / `data-path` を渡す
3. Action 内部が Foundry の Evaluation API を叩き、指定 Agent にテストケースを実行して評価結果を生成する

つまり **Actions 側のコードはパラメータを渡すだけ** で、実際の評価実行は Action + Foundry 側が担っている。

### Q. 評価は中身で何をやっている？

`.github/eval-data.json` に定義した 6 件の `query` + `ground_truth` を使い、2 つの built-in evaluator を実行する。どちらも **LLM-as-Judge**（指定した GPT モデルが採点者になる）方式で、各テストケースごとにスコア 1–5 + reason を返す。デフォルトのパスしきい値は **3** で、3 以上なら pass。

このリポジトリの評価は、現行 Foundry の cloud evaluation で `builtin.*` evaluator を指定して実行している。以下の `.prompty` は classic / ローカル実行向け Azure AI Evaluation SDK (`azure-ai-evaluation`) に含まれる OSS の参考情報であり、現行 Foundry cloud evaluation の `builtin.*` evaluator が同一のプロンプトを使っているという記載は確認していない。

#### `builtin.response_completeness`（応答の完全性）

- **カテゴリ**: RAG エバリュエーター > システム評価
- **何を測るか**: Agent の回答が `ground_truth` の **重要情報をどれだけ網羅しているか（recall）**
- **入力**: `response`（Agent の回答）、`ground_truth`（期待される正解）
- **仕組み**: LLM Judge が ground_truth に含まれるキーポイントをリストアップし、response がそれらをカバーしているかを照合する
- **このデモでの役割**: バグ検出のメイン。「日当 2,500 円」と回答すると ground_truth の「3,000 円」と食い違うため、recall が低くスコアが下がり fail になる

**参考: classic / ローカル SDK の OSS prompty（Definition 部分・原文）** — [response_completeness.prompty](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/evaluation/azure-ai-evaluation/azure/ai/evaluation/_evaluators/_response_completeness/response_completeness.prompty)

> **Completeness** refers to how accurately and thoroughly a response represents the information provided in the ground truth. It considers both the inclusion of all relevant statements and the correctness of those statements. Each statement in the ground truth should be evaluated individually to determine if it is accurately reflected in the response without missing any key information. The scale ranges from 1 to 5, with higher numbers indicating greater completeness.

> **翻訳**: **完全性**とは、回答が ground truth に含まれる情報をどれだけ正確かつ網羅的に表現しているかを指す。すべての関連する記述が含まれているか、それらが正しいかの両方を考慮する。ground truth の各記述を個別に評価し、重要な情報を見落とすことなく回答に正確に反映されているかを判定する。スケールは 1〜5 で、数が大きいほど完全性が高い。

**スコア定義（原文 → 翻訳）**

| Score | 原文 | 翻訳 |
|-------|------|------|
| **5** (Fully Complete) | A response that perfectly contains all the necessary and relevant information with respect to the ground truth. It does not miss any information from statements and claims in the ground truth. | ground truth に対して必要かつ関連するすべての情報を完璧に含む回答。ground truth の記述や主張から情報が一切欠落していない。 |
| **4** (Mostly Complete) | A response that contains most of the necessary and relevant information with respect to the ground truth. It misses some minor information, especially claims and statements, established in the ground truth. | ground truth に対して必要かつ関連する情報の大部分を含む回答。ground truth の主張や記述のうち、一部の軽微な情報が欠落している。 |
| **3** (Moderately Complete) | A response that contains half of the necessary and relevant information with respect to the ground truth. It misses half of the information, especially claims and statements, established in the ground truth. | ground truth に対して必要かつ関連する情報の半分を含む回答。ground truth の主張や記述のうち半分が欠落している。 |
| **2** (Barely Complete) | A response that contains only a small percentage of all the necessary and relevant information with respect to the ground truth. It misses almost all the information. | ground truth に対して必要かつ関連する情報のごくわずかしか含まない回答。ほぼすべての情報が欠落している。 |
| **1** (Fully Incomplete) | A response that does not contain any of the necessary and relevant information with respect to the ground truth. It completely misses all the information. | ground truth に対して必要かつ関連する情報を一切含まない回答。すべての情報が完全に欠落している。 |

**LLM への指示（Tasks 部分・原文）**

> - **ThoughtChain**: To improve the reasoning process, think step by step and include a step-by-step explanation of your thought process as you analyze the data based on the definitions. Keep it brief and start your ThoughtChain with "Let's think step by step:".
> - **Explanation**: a very short explanation of why you think the input data should get that Score.
> - **Score**: based on your previous analysis, provide your Score. The Score you give MUST be an integer score (i.e., "1", "2"...) based on the levels of the definitions.
>
> Please provide your answers between the tags: `<S0>your chain of thoughts</S0>`, `<S1>your explanation</S1>`, `<S2>your score</S2>`.

> **翻訳**: LLM に対して「まず段階的に思考し（ThoughtChain）、短い説明を付けた上で、定義に基づく整数スコアを出力せよ」と指示。出力は `<S0>`〜`<S2>` タグで構造化される。

#### `builtin.coherence`（一貫性）

- **カテゴリ**: 汎用エバリュエーター
- **何を測るか**: 回答の **論理的な流れとアイデアの構成**（事実の正確性は問わない）
- **入力**: `query`（質問）、`response`（Agent の回答）
- **仕組み**: LLM Judge が「質問に直接対応しているか」「文と文のつながりが論理的か」「適切な接続・遷移があるか」を採点する
- **このデモでの役割**: たとえバグ入りの誤った数値を回答しても、文としては筋が通っているため常に PASS になる。response_completeness との対比で「事実の正しさと文章の質は別軸」であることを示す

**参考: classic / ローカル SDK の OSS prompty（Definition 部分・原文）** — [coherence.prompty](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/evaluation/azure-ai-evaluation/azure/ai/evaluation/_evaluators/_coherence/coherence.prompty)

> **Coherence** refers to the logical and orderly presentation of ideas in a response, allowing the reader to easily follow and understand the writer's train of thought. A coherent answer directly addresses the question with clear connections between sentences and paragraphs, using appropriate transitions and a logical sequence of ideas.

> **翻訳**: **一貫性**とは、回答の中でアイデアが論理的かつ秩序立てて提示されていることを指し、読み手が筆者の思考の流れを容易に追い理解できることを意味する。一貫性のある回答は、文と段落の間に明確なつながりを持ち、適切な接続表現と論理的な順序を用いて質問に直接対応する。

**スコア定義（原文 → 翻訳）**

| Score | 原文 | 翻訳 |
|-------|------|------|
| **5** (Highly Coherent) | The response is exceptionally coherent, demonstrating sophisticated organization and flow. Ideas are presented in a logical and seamless manner, with excellent use of transitional phrases and cohesive devices. The connections between concepts are clear and enhance the reader's understanding. The response thoroughly addresses the question with clarity and precision. | 回答が極めて一貫しており、洗練された構成と流れを示す。アイデアが論理的かつシームレスに提示され、接続表現と結束装置が効果的に使われている。概念間のつながりが明確で読み手の理解を高め、質問に対して明晰かつ正確に応えている。 |
| **4** (Coherent) | The response is coherent and effectively addresses the question. Ideas are logically organized with clear connections between sentences and paragraphs. Appropriate transitions are used to guide the reader through the response, which flows smoothly and is easy to follow. | 回答が一貫しており質問に効果的に対応している。アイデアが論理的に整理され、文と段落の間に明確なつながりがある。適切な接続表現が使われ、滑らかで追いやすい。 |
| **3** (Partially Coherent) | The response partially addresses the question with some relevant information but exhibits issues in the logical flow and organization of ideas. Connections between sentences may be unclear or abrupt, requiring the reader to infer the links. | 回答が質問に部分的に対応し関連情報も含むが、論理的な流れと構成に問題がある。文間のつながりが不明確または唐突で、読み手が推測する必要がある。 |
| **2** (Poorly Coherent) | The response shows minimal coherence with fragmented sentences and limited connection to the question. It contains some relevant keywords but lacks logical structure and clear relationships between ideas. | 回答のまとまりが最小限で、断片的な文と質問への関連が限定的。関連キーワードはあるが論理構造やアイデア間の明確な関係がない。 |
| **1** (Incoherent) | The response lacks coherence entirely. It consists of disjointed words or phrases that do not form complete or meaningful sentences. There is no logical connection to the question. | 回答にまとまりが全くない。まとまりのない語やフレーズの羅列で、完全または有意味な文を構成していない。質問との論理的つながりもない。 |

**LLM への指示（Tasks 部分）** は response_completeness と同一構造（ThoughtChain → Explanation → Score を `<S0>`〜`<S2>` タグで出力）。

#### 合否判定の流れ

評価完了後、ワークフローの `Check Pass Rate` ステップが Python で **OpenAI Evals API**（`client.get_openai_client().evals`）を呼び、最新 run の `result_counts` と `per_testing_criteria_results` を取得して pass/fail を判定する。fail が 1 件でもあれば `result=fail` を後続に出力する。

### Q. Actions でどうやって Copilot をアサインしている？

2 ステップ構成:

1. **Issue 作成** — `actions/github-script@v7` で評価結果を本文に含む Issue を自動作成（ラベル `evaluation`）
2. **Copilot アサイン** — `gh api --method POST /repos/{owner}/{repo}/issues/{number}/assignees` で `copilot-swe-agent[bot]` を assignee に追加

ポイントは `agent_assignment` フィールド:
```json
{
  "assignees": ["copilot-swe-agent[bot]"],
  "agent_assignment": {
    "target_repo": "<owner>/<repo>",
    "base_branch": "main"
  }
}
```
この API を叩くには `issues: write` 権限に加え、**Fine-grained PAT**（`REPO_FG_TOKEN`）が必要。GITHUB_TOKEN では Copilot Coding Agent のアサインはできない。
