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

## 6. ユーザー固有データの注入パターン

`developer` ロールが使えない制約下で、アプリがユーザー固有のデータ（過去の申請履歴等）をエージェントに渡す方法は3つある。
**ただし検証の結果、確実にデータが反映されるのは Function Calling 系のみ**（詳細は `docs/sdk-architecture.md` 参照）。

### パターン比較

| | ① Function Calling（推奨） | ② assistant ロール注入 | ③ user ロール注入（非推奨） |
|---|---|---|---|
| 仕組み | エージェントが必要時に `get_user_history` 等を呼ぶ → クライアントが実行して結果を返送 | `assistant` ロールにデータを載せて毎回送信 | `user` ロールにデータを詰め込む |
| トークン効率 | ✅ 必要な時だけ取得 | ❌ 毎回全データ送信 | ❌ 毎回全データ送信 |
| セキュリティ | ✅ **クライアントが実行を制御** — 認証済みユーザーのデータのみ返す。エージェントの引数は信用不要 | ⚠️ 命令として解釈されにくいが、データ内容がプロンプトに入る | ❌ 「ユーザーの指示」として解釈されうる |
| インジェクション耐性 | ✅ データはツール結果として渡される（会話コンテキスト外） | ⚠️ 中（参照データとして扱われる） | ❌ 低（命令として実行される恐れ） |
| エージェントの自律性 | ✅ エージェントが「何の情報が必要か」を判断 | ❌ アプリが「何を渡すか」を事前に決める | ❌ 同左 |
| レイテンシ | ⚠️ 2往復以上（function_call → 結果返送） | ✅ 1往復 | ✅ 1往復 |
| 利用条件 | エージェント定義に FunctionTool の登録が必要 | どのエージェントでも可 | どのエージェントでも可 |

### ① Function Calling（推奨）

エージェントに `FunctionTool` を登録し、必要時にクライアント経由でデータを取得させる。

```python
# エージェント側: get_user_history ツールを定義
# クライアント側: function_call を受け取って実行
def execute_function(name, arguments, session_user_id):
    if name == "get_user_history":
        # エージェントが渡す user_id は無視し、認証済みセッションの ID を使う
        history = db.get_history(user_id=session_user_id)
        return json.dumps(history, ensure_ascii=False)
```

**セキュリティ上の最大の利点**: エージェントは「データが欲しい」と言うだけ。実際のDB問い合わせはクライアントコードが認証済みユーザーIDで実行する。エージェントの引数を信用する必要がない。

検証スクリプト: `agent/create_fc_agent.py`, `agent/test_fc_agent.py`

### ② assistant ロール注入（代替）

Function Calling が使えない場合（既存エージェントを変更できない等）のフォールバック。

```python
response = client.responses.create(
    input=[
        {"role": "assistant", "content": "あなたの経費精算履歴:\n- 2026/03/05 大阪 日帰り 承認済\n- 2026/04/01 福岡 2泊 差戻し"},
        {"role": "user", "content": "福岡出張が差し戻されたのですが、どうすればいいですか？"},
    ],
)
```

- モデルは `assistant` を「自分の過去の出力」と解釈 → 参照データとして扱う
- `user` ロール注入より安全だが、データがプロンプト内に直接入る点は同じ

### ③ user ロール注入（非推奨）

データを「ユーザーの指示」として解釈するため、プロンプトインジェクションのリスクが高い。トレースログでもユーザー入力とコンテキストが区別できない。

### 検証結果

- Function Calling: ✅ エージェントが `get_user_history` を自律的に呼び出し、モック履歴を踏まえて回答（`test_fc_agent.py`）
- **FC 事前注入**: ✅ `function_call` + `function_call_output` を input に事前注入。FunctionTool 登録不要で 1 往復完結。データ反映 3/3 チェック通過（`test_input_patterns.py` パターン 0）
- assistant 注入: ⚠️ HTTP は成功するが、**Foundry エージェントはデータを回答に反映しない**（`test_input_patterns.py` パターン A3）。`test_assistant_context.py` での「動作」は回答の品質差によるもので、データ反映の信頼性は低い
- user 注入: ✅ 動作するが推奨しない（`test_context_injection_comparison.py`）
- インジェクション試行: ✅ Azure コンテンツフィルターが jailbreak を検出してブロック
- **その他の input type**: developer ロール・instructions パラメータは HTTP 400。file_search_call・mcp_call は HTTP OK だがデータ無視。item_reference は部分的動作のみ。詳細は `docs/sdk-architecture.md` の「Responses API input に渡せる全タイプの検証」セクション参照

### 選定ガイド

```
エージェント定義を変更できる？
  ├─ Yes → ① Function Calling（推奨・エージェントが自律的にデータ要求）
  └─ No
       └─ ユーザー固有データの注入が必要？
            ├─ Yes → FC 事前注入（function_call + function_call_output を input に事前構築）
            │        ※ FunctionTool 登録不要、1往復、ポータル互換性維持
            │        ※ 詳細は docs/sdk-architecture.md 参照
            └─ No → エージェントをそのまま使用
```

> **注意**: ② assistant ロール注入は HTTP レベルでは受け入れられるが、Foundry エージェントが注入データを回答に反映しないことが検証で判明した（`test_input_patterns.py`）。信頼性の高いデータ注入には FC 事前注入を使うこと。

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
3. **設計側（推奨）**: Function Calling でデータ取得 → クライアントが認証済みユーザーのデータのみ返す。エージェントの引数は信用不要
4. **設計側（代替）**: `assistant` ロールでコンテキスト注入 → ユーザー入力と構造的に分離

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
| `agent/create_fc_agent.py` | Function Calling 付きエージェント作成（file_search + get_user_history） |
| `agent/test_fc_agent.py` | Function Calling の一連フロー検証（function_call → 実行 → 結果返送 → 最終回答） |
