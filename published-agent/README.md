# 発行済み Agent Application 調査

Foundry Agent の「発行（Publish）」機能に関する調査・検証メモ。

---

## 1. 発行（Publish）の仕組み

- エージェントを「発行」すると **Agent Application** という ARM 子リソースが作成される
  - `Microsoft.CognitiveServices/accounts/{account}/projects/{project}/applications/{app}`
- 発行時点の Instructions・ツール設定がスナップショットとして **バージョン固定**（v1, v2...）
- 専用の **Entra ID マネージド ID** が生成される
  - Principal ID: `<agent-app-principal-id>`
  - Entra ID → Enterprise applications → **Application type を "Managed Identities" に変更**して検索
  - `App registrations` には表示されない

## 2. エンドポイントの違い

| | 開発エンドポイント | 発行済みエンドポイント |
|---|---|---|
| プロトコル | Agents API（Conversations + Responses） | **Responses API のみ** |
| クライアント | `project.get_openai_client()` | 素の `OpenAI()` |
| エージェント指定 | `agent_reference` で名前指定 | URL に含まれる |
| 会話管理 | `conversations.create()` → ID を渡す | なし（ステートレス） |
| API コール | `responses.create(conversation=..., input=...)` | `responses.create(input=...)` |
| 使える API | `/conversations`, `/files`, `/vector_stores` 等 | `/responses` のみ |
| バージョン | 常に最新の開発中定義 | 発行時のスナップショット |

## 3. Conversations API は OpenAI 標準

当初 Foundry 固有と誤解していたが、**OpenAI 標準の API**。

OpenAI が提供する会話ステート管理は3つ:

1. **手動管理（input 配列に全履歴を渡す）** — 完全ステートレス
2. **`previous_response_id`** — サーバー側の保存済み応答を参照してチェーン
3. **Conversations API** — `conversations.create()` で永続会話オブジェクトを作成、セッション・デバイスをまたいで利用

Foundry 固有なのは `agent_reference`（どのエージェントに投げるかの指定）の部分のみ。
発行済みエンドポイントでは Foundry が Conversations API のサポートを意図的に無効化している。

## 4. ステートレスの理由と背景

### なぜステートレスなのか

Foundry Agent Service のマネージド会話履歴は、同一プロジェクト内で**エンドユーザー間の分離ができていない**。
`conv_` ID を知っていれば他人の会話履歴を読めてしまう（混ざるのではなく「覗ける」問題）。

- 開発環境（Agents API）→ プロジェクト開発者同士だから許容 → `conv_` ID あり
- 発行済みアプリ → 組織のユーザーや顧客向け → プライバシー必須
  → **会話を持たせない（ステートレス）ことでデータ漏洩を構造的に不可能にする**

ドキュメントに「一時的な制限（temporary limitation）」と明記。ユーザー分離の実装が完了次第解除予定。

### 背景：Teams / M365 直接公開

発行の主な想定ユーザーは **バックエンドなしでエージェントを公開したい人**。

- Teams / M365 連携ではユーザーが直接エージェントと会話する（バックエンド不在）
- 各ユーザーが自分の Azure AD トークンで直接 API を叩く構図
- プラットフォーム側でユーザー分離が必須だが、まだできていない → ステートレス

発行の2つのプロトコル:

| プロトコル | 用途 | クライアント |
|---|---|---|
| **Responses API** | 自前アプリ・API 連携 | 開発者のコード |
| **Activity Protocol** | Teams / M365 | Microsoft のインフラ |

### 自前バックエンドがある場合

- アプリ層で `conv_` ID とユーザーの紐付けを管理 → **発行は必須ではない**
- DB と同じ構造。認可はアプリ側の責務
- 発行済みエンドポイントのメリットは「バージョン固定」「API サーフェスの縮小」
- アプリの MID に Azure AI ユーザーロールを付ければ、エンドユーザー個別の RBAC は不要

### Foundry Agent Service の位置付け

- 「評価のためだけ」ではなく、**定義から評価から本番運用まで全部やるプラットフォーム**を目指している
- 現状はユーザー分離・OBO フロー等が未実装のため、本番アプリには制約がある
- ユーザー分離が実装されれば、バックエンドなしで本番利用が成立する見込み

## 5. input ロールの制約と検証

### 使えるロール

`agent_reference` でエージェントを指定している場合（開発・発行 共通）:

| ロール | 使える？ | 備考 |
|--------|---------|------|
| `user` | ✅ | ユーザーの発言 |
| `assistant` | ✅ | モデルの過去の出力 |
| `developer` | ❌ 400 エラー | input 配列の後続要素の解析が壊れる |
| `system` | ❌ 400 エラー | 同上（developer のレガシーエイリアス） |

`instructions` パラメータも ❌ — `"Not allowed when agent is specified."`

**開発・発行どちらのエンドポイントでも同じ制約**（test_input_roles, test_dev_roles で検証済み）。

### サポートされていない機能の検証（test_unsupported_features）

発行済みエンドポイントに対して:

| テスト | 結果 | エラーメッセージ |
|--------|------|-----------------|
| `previous_response_id` | ❌ 400 | `"Application-scoped response APIs are stateless and do not support previous response references."` |
| `conversations.create()` | 会話自体は作れた（`conv_` ID 返却）が、`conversation=` を渡すと ❌ 400 | `"...do not support conversation context."` |

### マルチターンは input 配列で実現可能（verify_conversation_state, test_input_roles）

```python
# 発行済みエンドポイントで動作確認済み
response = client.responses.create(
    input=[
        {"role": "user", "content": "私の名前は田中です。"},
        {"role": "assistant", "content": "承知しました、田中さん。"},
        {"role": "user", "content": "私の名前は何ですか？"},  # ← 「田中さんです」と回答
    ],
)
```

## 6. コンテキスト注入パターン

### user vs assistant どちらにコンテキストを載せるか

`developer` ロールが使えない制約下で、アプリがユーザー固有のデータ（過去の申請履歴等）を注入する場合。

| 方式 | モデルの解釈 | インジェクション耐性 | トレースログ |
|------|-------------|---------------------|-------------|
| `user` に全部載せる | 「ユーザーの指示」→ 命令として従おうとする | 低い（指示として実行される恐れ） | コンテキストとユーザー入力が混在、区別不能 |
| `assistant` にコンテキスト + `user` に質問 | 「自分の過去の出力」→ 参照データとして扱う | 高い（命令として解釈されにくい） | 明確に分離、デバッグ・評価に有利 |

**推奨: `assistant` ロールにコンテキスト、`user` ロールにユーザー入力**

```python
response = client.responses.create(
    input=[
        {"role": "assistant", "content": "あなたの経費精算履歴:\n- 2026/03/05 大阪 日帰り 承認済\n- 2026/04/01 福岡 2泊 差戻し"},
        {"role": "user", "content": "福岡出張が差し戻されたのですが、どうすればいいですか？"},
    ],
)
```

### 検証結果（test_assistant_context, test_context_injection_comparison）

- テスト1（user に履歴）: ✅ 動作。履歴を参照して回答
- テスト2（assistant に履歴）: ✅ 動作。同等品質で回答の構造がよりきれい
- テスト3/4（インジェクション試行）: ✅ Azure コンテンツフィルターが jailbreak を検出してブロック

### Conversation ID との相性

| | ステートレス + assistant | Conversation ID + assistant |
|---|---|---|
| トレースでの分離 | ✅ 明確（assistant=注入、user=入力） | ❌ エージェントの実際の応答と注入コンテキストが混在 |
| コンテキスト更新 | ✅ 毎回最新に差し替え可能 | ❌ 会話に固定される |
| マルチターン | アプリが履歴を管理 | サーバーが自動管理 |

**assistant コンテキスト注入パターンはステートレス運用と相性が良い。**
Conversation ID を使う場合は、ツール経由で取得させるか、Conversation ID を使わず毎回 input を自前構築する方がクリーン。

## 7. 検証結果（会話ステート・RBAC）

### 会話ステート保持の検証（verify_conversation_state）

| エンドポイント | 1回目: 「田中です」 | 2回目: 「名前は？」 | ステート |
|---------------|--------------------|--------------------|---------|
| 発行前（Conversations API） | 覚えた | 「田中さんです」 | ✅ 保持 |
| 発行後（Responses API） | 覚えた風に返答 | 「確認できません」 | ❌ なし |

### Agent Application の RBAC

```
az role assignment list --assignee <agent-app-principal-id> --all
→ [] （空配列 = ロール割り当てなし）
```

- file_search は動作する → Agent Service 内部パスで解決（ARM RBAC 不要）
- 外部 Azure リソース（Blob Storage, SQL 等）へのアクセスには明示的な RBAC 割り当てが必要

## 8. セキュリティ

### 発行済みエンドポイントで防げること

| リスク | 開発エンドポイント | 発行済みエンドポイント |
|--------|--------------------|-----------------------|
| 他人の会話履歴を覗ける | ⚠️ conv_ ID を知れば可能 | ✅ 会話自体が存在しない |
| /files, /vector_stores への直接アクセス | ⚠️ API 経由で可能 | ✅ ブロック |
| エージェント定義の書き換え | ⚠️ Agents API で可能 | ✅ Responses API のみ |
| 意図しないバージョンの利用 | ⚠️ 常に最新 | ✅ スナップショット固定 |
| Instructions の外部上書き | ⚠️ 未検証 | ✅ developer/system/instructions すべて拒否 |

### インジェクション対策（多層防御）

1. **Foundry 側**: `developer`/`system` ロール・`instructions` パラメータを拒否 → Instructions の上書き不可
2. **Azure 側**: コンテンツフィルターが jailbreak パターンを検出・ブロック
3. **設計側**: `assistant` ロールでコンテキスト注入 → ユーザー入力と構造的に分離

## 9. 認証の注意点

- `get_bearer_token_provider()` だと 404 `WorkspaceNotFound` エラー
- `credential.get_token("https://ai.azure.com/.default")` で直接トークン取得 → 動作する
- 呼び出し元には Agent Application リソースに対する **Azure AI ユーザー** ロールが必要

## 10. 価格モデル

- **発行元支払い（publisher-pays）** モデル
- プロジェクト所有者がインフラコストを負担（呼び出しごとの従量課金ではない）
- エンドユーザーには既定でコストなし
- 従量課金にしたい場合は自前の測定/課金レイヤーを構築

## 11. 検証スクリプト一覧

| スクリプト | 内容 |
|-----------|------|
| `test_published_agent.py` | 発行済みエンドポイントの基本呼び出し |
| `verify_conversation_state.py` | 会話ステート保持の比較（開発 vs 発行済み） |
| `test_unsupported_features.py` | `previous_response_id` / `conversations` の拒否確認 |
| `test_input_roles.py` | 発行済みでの input ロール制約検証 |
| `test_dev_roles.py` | 開発エンドポイントでの developer / instructions 拒否確認 |
| `test_assistant_context.py` | assistant ロールのコンテキスト注入 + インジェクション耐性 |
| `test_context_injection_comparison.py` | user vs assistant の実用ケース比較（経費精算履歴） |
