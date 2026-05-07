# Foundry Agent Lab

Microsoft Foundry の Agent 機能を検証するためのラボ環境です。
検証対象のエージェント（旅費精算ヘルプデスク）を題材に、評価・発行・監視など各種機能を試します。

> **このリポジトリは個人の検証・学習用です。**
> 検証の過程で得られた知見やフィードバックを含みます。
> 公式のベストプラクティスやリファレンス実装ではありません。

## リポジトリ構成

```
agent/          検証対象の AI エージェント（定義・ナレッジ・テスト）
eval/           評価駆動サイクル（バッチ評価 → CI → 自動修正 PR）
published-agent/  発行済み Agent Application の調査・検証
infra/          Azure インフラ（Bicep テンプレート）
.github/        GitHub Actions ワークフロー
docs/           トピック横断のドキュメント
```

## トピック

| トピック | 概要 | ドキュメント |
|----------|------|-------------|
| **エージェント** | 旅費精算ヘルプデスク Agent（Prompt Agent + file_search） | [agent/README.md](agent/README.md) |
| **評価駆動サイクル** | CI で品質評価 → Issue 自動作成 → Copilot Coding Agent が修正 PR | [eval/README.md](eval/README.md) |
| **Agent Application** | 発行済みエンドポイントの挙動・ロール制約・コンテキスト注入パターン | [published-agent/README.md](published-agent/README.md) |
| **プロダクトフィードバック** | Foundry Portal の UI に関するフィードバック | [docs/product-feedback.md](docs/product-feedback.md) |

## セットアップ

### 前提条件

- Python 3.11+
- Azure CLI でログイン済み（`az login`）

### Azure リソースのデプロイ

Bicep テンプレートでリソースグループ・AI Services アカウント・Foundry プロジェクト・モデルデプロイメントをまとめて作成します。
同じ `environmentName` では同じリソース名に再デプロイされます。別環境を作る場合は `-p environmentName=<name>` を追加してください。

```bash
az deployment sub create \
  -l swedencentral \
  -f infra/main.bicep \
  -p deployerPrincipalId=$(az ad signed-in-user show --query id -o tsv) \
  --query properties.outputs -o json
```

出力例:
```json
{
  "projectEndpoint": { "value": "https://ai-eval-xxxxx.services.ai.azure.com/api/projects/foundry-agent-eval" },
  "resourceGroupName": { "value": "rg-agent-eval-demo-xxxxx" },
  "modelDeploymentName": { "value": "gpt-5.4" }
}
```

### 環境変数の設定

```bash
pip install -r requirements.txt
cp .env.sample .env
# .env を編集: PROJECT_ENDPOINT にデプロイ出力の projectEndpoint を設定
```

### エージェント作成 & 動作確認

```bash
python agent/create_agent.py
python agent/test_agent.py -q "大阪出張の日当はいくら？"
```

### CI/CD（GitHub Actions）

手動トリガー（`workflow_dispatch`）で評価を実行します。
詳細は [eval/README.md](eval/README.md) を参照してください。

#### 事前設定（GitHub リポジトリ）

Settings → Secrets and variables → Actions:

**Variables:**

| Variable | 値 |
|----------|-----|
| `AZURE_CLIENT_ID` | App Registration のクライアント ID |
| `AZURE_TENANT_ID` | テナント ID |
| `AZURE_SUBSCRIPTION_ID` | サブスクリプション ID |
| `AZURE_AI_PROJECT_ENDPOINT` | デプロイ出力の `projectEndpoint` |

**Secrets:**

| Secret | 値 |
|--------|-----|
| `REPO_FG_TOKEN` | Fine-grained PAT（権限: Metadata:read, Issues:rw） |

## モデル

gpt-5.4 を使用しています。アクセスには登録が必要です（2026 年 4 月時点）。
詳細は [Models sold directly by Azure](https://learn.microsoft.com/ja-jp/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure?tabs=global-standard-aoai%2Cglobal-standard&pivots=azure-openai#gpt-54) を参照してください。

## トピックの追加

新しい検証テーマは、トピック単位のフォルダとして追加します。

1. ルート直下にフォルダを作成（例: `monitoring/`）
2. `README.md` + スクリプト + データを自己完結で配置
3. CI が必要なら `.github/workflows/{topic}.yml` を追加
4. このファイルのトピック一覧に1行追加

`REPO_FG_TOKEN` は Copilot Coding Agent を Issue に自動アサインするために必要です。GitHub App トークン（`GITHUB_TOKEN`）では Copilot のアサインができないため、ユーザー PAT を使用します。

Azure 側で App Registration に OIDC フェデレーション資格情報と Azure AI User ロールを設定してください。

#### 実行

Actions タブ → "Agent Evaluation" → "Run workflow" で手動実行します。
実行のたびに Foundry に新しい Evaluation Run が作成され、ポータルの評価タブで時系列の品質推移を確認できます。

## ナレッジドキュメント

| ファイル | 内容 |
|----------|------|
| `agent/knowledge/travel-expense-policy.md` | 旅費規程（17条） |
| `agent/knowledge/system-manual.md` | TravelExpense 操作マニュアル |
| `agent/knowledge/faq.md` | よくある質問（18問） |

## スクリプト

| ファイル | 役割 |
|----------|------|
| `agent/create_agent.py` | Vector Store 作成 + ナレッジアップロード + エージェント作成 |
| `agent/test_agent.py` | エージェントに質問を送って動作確認 |
| `eval/run_evaluation.py` | バッチ評価（2 評価器） |

## 評価データセット

| ファイル | 内容 |
|----------|------|
| `eval/data/accuracy-test.jsonl` | 正確性テスト（6件、query + ground_truth + context） |
