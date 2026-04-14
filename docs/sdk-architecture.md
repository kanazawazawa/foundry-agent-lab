# SDK アーキテクチャと発行前エージェントの呼び出し方法

> 2026-04-14 検証結果

## SDK の関係性

```
azure-ai-projects (v2.0.1)
├── AIProjectClient                  ← Azure Foundry 固有機能
│   ├── .agents.create_agent()        ← エージェント作成
│   ├── .evaluations                  ← 評価
│   ├── .connections                  ← 接続管理
│   └── .get_openai_client()         ← ★ OpenAI クライアントを返すだけ
│
openai (Python SDK)                  ← LLM 呼び出しの本体
├── responses.create()                ← Response API
├── responses.parse()                 ← Structured Outputs
├── conversations.create()            ← 会話管理
└── ...
```

`azure-ai-projects` は `openai >= 1.60.0` に依存しており、LLM との通信は完全に OpenAI SDK に委譲している。

## get_openai_client() の正体

`AIProjectClient.get_openai_client()` が返すのは `openai.OpenAI`（`AzureOpenAI` ではない）のインスタンス。内部でやっているのは以下の 3 点のみ：

```python
from openai import OpenAI

client = OpenAI(
    base_url=f"{ENDPOINT}/openai/v1/",   # 1. エンドポイントに /openai/v1/ を付加
    api_key=token,                        # 2. Entra ID トークンを api_key に設定
)                                         # 3. OpenAI() インスタンスを生成
```

## 検証: azure-ai-projects なしで発行前エージェントを呼べるか

**結論: 呼べる。**

```python
from azure.identity import DefaultAzureCredential
from openai import OpenAI

# azure-ai-projects は import していない

credential = DefaultAzureCredential()
token = credential.get_token("https://ai.azure.com/.default").token

client = OpenAI(
    base_url=f"{ENDPOINT}/openai/v1/",
    api_key=token,
)

conversation = client.conversations.create()

response = client.responses.create(
    conversation=conversation.id,
    input="タクシーは使えますか？",
    extra_body={
        "agent_reference": {"name": "travel-expense-helpdesk", "type": "agent_reference"},
    },
)
print(response.output_text)  # → 正常に回答が返る
```

実行結果（2026-04-14）:
```
Conversation: conv_3fb7e4c9792e8daa00WKF21tAA6bbqXf2Ib9zUrMEEz7Rltuqa
Answer: はい、タクシーは原則利用できません。ただし...（正常応答）
```

## 発行前 vs 発行後のエージェント呼び出し

| 観点 | 発行前 | 発行後 (Agent Application) |
|------|--------|---------------------------|
| 専用 HTTP エンドポイント | なし | あり (`BASE_URL`) |
| 呼び出し方 | プロジェクトの Response API + `agent_reference` | 専用エンドポイントに POST |
| 認証 | プロジェクトの Entra ID トークン | Agent Application の Entra ID |
| OpenAI SDK だけで呼べるか | ✅ 可能（上記の通り） | ❌ 専用 API のため別プロトコル |
| azure-ai-projects が必須か | ❌ 不要（便利なだけ） | ❌ 不要（HTTP で直叩き） |

**「発行前は SDK 経由でしか使えない」は不正確。** 正確には「発行前のエージェントには専用エンドポイントがなく、プロジェクトの Response API（`/openai/v1/responses`）に `agent_reference` を付けて呼ぶ必要がある。SDK は必須ではないが、接続設定を楽にする便利ツール」。

## Response API の JSON mode とエージェントの制約

| パターン | `text.format` 指定 | 結果 |
|----------|-------------------|------|
| エージェントなし + `json_object` | ✅ | 有効な JSON を返す |
| エージェントなし + `json_schema` | ✅ | スキーマ準拠の JSON を返す |
| エージェントなし + `responses.parse()` | ✅ | Pydantic オブジェクトで返る |
| **エージェントあり** + `text.format` | ❌ | `Not allowed when agent is specified.` |

エージェント経由では `text` パラメータが使えない（API が明示的に拒否）。  
回避策: エージェントの回答を取得後、別途 `responses.parse()` で構造化する 2 段構え。

## agent_reference 使用時の input ロール制約

`agent_reference` を指定した場合、input に渡せるロールは制限される。

| ロール / パラメータ | 併用可否 | エラーメッセージ |
|---------------------|---------|-----------------|
| `user` | ✅ | — |
| `assistant` | ✅ | — （マルチターン文脈の注入に使える） |
| `developer` | ❌ | `Invalid value` |
| `system` | ❌ | `Invalid value` |
| `instructions` パラメータ | ❌ | `Not allowed when agent is specified.` |
| `text.format` パラメータ | ❌ | `Not allowed when agent is specified.` |

検証コード（2026-04-14 実行）:
```python
# user + assistant → OK
r = client.responses.create(
    conversation=c.id,
    input=[
        {"role": "user", "content": "私の名前は田中です。覚えてください。"},
        {"role": "assistant", "content": "承知しました、田中さん。"},
        {"role": "user", "content": "私の名前は何ですか？"},
    ],
    extra_body={"agent_reference": {"name": "travel-expense-helpdesk", "type": "agent_reference"}},
)
# → "田中さんです。"  ✅ 文脈保持

# developer → NG
# instructions → NG
# system → NG
# text.format → NG
```

**まとめ**: エージェントの振る舞いを上書きするパラメータ（developer / system / instructions / text.format）はすべてサーバー側でブロックされる。クライアントから制御できるのは会話履歴（user / assistant のペア）の注入のみ。エージェントの Instructions を変えたい場合は Foundry Portal または agents API で定義を更新する必要がある。

## Function Calling（関数呼び出し）

エージェントに `FunctionTool` を登録すると、エージェントが必要と判断した時にクライアント側に関数実行を要求する。
これにより、ユーザー固有データの取得や外部システム連携をエージェントに組み込める。

参考: [Microsoft Foundry エージェントで関数呼び出しを使用する](https://learn.microsoft.com/ja-jp/azure/foundry/agents/how-to/tools/function-calling?pivots=python)

### 処理フロー

```
[クライアント] → responses.create(質問)
[エージェント] → output に function_call（テキスト応答なし）
[クライアント] → 関数をローカル実行 → 結果を function_call_output で返送
                  responses.create(input=結果, previous_response_id=...)
[エージェント] → output_text に最終回答
```

### FunctionTool 定義

```python
from azure.ai.projects.models import FunctionTool

GET_USER_HISTORY_TOOL = FunctionTool(
    name="get_user_history",
    description="ユーザーの過去の問い合わせ履歴・申請履歴を取得する。...",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "取得する履歴件数"},
        },
        "required": [],
    },
    strict=False,
)
```

- `parameters` は JSON Schema 形式（OpenAI の Function Calling と同じ）
- `strict=True` にすると厳密検証（`additionalProperties: False` が必須、全パラメータ required）
- **ポータルからは関数の追加・削除・更新不可**。SDK/REST API のみ

### クライアント側の実行（セキュリティ設計）

```python
SESSION_USER_ID = "emp-12345"  # 認証済みセッションから取得

def execute_function(name, arguments):
    args = json.loads(arguments)
    if name == "get_user_history":
        # エージェントは user_id を知らない。セッションから取る
        history = db.get_history(user_id=SESSION_USER_ID)
        return json.dumps(history, ensure_ascii=False)
```

- **エージェントの引数を信用しない** — 認証済みセッションのユーザー ID を使う
- パラメータに user_id を含めないことで、エージェントに他人の ID を指定する手段を与えない

### function_call 結果の返送

```python
response = openai.responses.create(
    input=tool_outputs,                    # function_call_output のリスト
    previous_response_id=response.id,      # 前のレスポンスとチェーン
    extra_body={"agent_reference": {...}},
)
```

- `previous_response_id` でチェーン（**`conversation` とは併用不可** — 400 エラー）
- 複数の function_call が返る場合は、全結果をまとめて1回で返送
- **10分タイムアウト**: function 実行結果を10分以内に返す必要あり

### ポータルとの互換性

| 操作 | 結果 |
|------|------|
| ポータルで Instructions を編集 → 保存 | FunctionTool は **残る**（消えない） ✅ |
| ポータルのプレイグラウンドでテスト | **❌ エラー**: `No tool output found for function call call_...` |
| ポータルで FunctionTool の表示 | **❌ 非表示**（存在は認識するが UI に出ない） |

検証結果（2026-04-14）:
- SDK で FunctionTool 付きエージェント作成（version 2）
- ポータルで Instructions を編集 → 保存（version 3, 4）
- SDK テスト → FunctionTool は全バージョンで正常動作
- ポータルのプレイグラウンド → `No tool output found` エラー（クライアント実行ハンドラがないため）

**FunctionTool を使うエージェントのテストは SDK スクリプト経由のみ。ポータルのプレイグラウンドは使えない。**

### 検証スクリプト

| スクリプト | 内容 |
|-----------|------|
| `agent/create_fc_agent.py` | file_search + FunctionTool(get_user_history) 付きエージェント作成 |
| `agent/test_fc_agent.py` | function_call → クライアント実行 → 結果返送 → 最終回答の一連フロー |

### 補足: function_call_output の事前注入（実験的）

通常の Function Calling は最低2往復かかるが、`function_call` と `function_call_output` を input 配列に事前に含めることで**1往復で完結する**ことが確認できた。
さらに、**エージェント側に FunctionTool の登録は不要**。FunctionTool を持たないエージェント（file_search のみ）でも動作する。

#### 仕組み

input 配列に3つの要素を順番に渡す:

```python
input=[
    # ① function_call — 「こういう関数呼び出しがあった」という事実
    {"type": "function_call",
     "name": "get_user_history",     # 関数名（任意の文字列でよい）
     "arguments": "{}",              # 引数（JSON 文字列）
     "call_id": "preloaded_001"},    # ②と紐付ける ID（任意の文字列）

    # ② function_call_output — 「その結果がこれだった」という事実
    {"type": "function_call_output",
     "call_id": "preloaded_001",     # ①と同じ ID
     "output": json.dumps(history)}, # 結果（JSON 文字列）

    # ③ user メッセージ — ユーザーの質問
    {"role": "user",
     "content": "前回の大阪出張の精算はどうなりましたか？"},
]
```

エージェントから見ると「過去に関数が呼ばれて結果が返ってきた」という会話履歴として扱われる。
エージェント定義に FunctionTool があるかどうかは関係ない — input はあくまで「過去に起きたこと」の記録。

#### コード例（FunctionTool 未登録エージェント）

```python
import os, json
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

load_dotenv()
project = AIProjectClient(
    endpoint=os.environ["PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
)
openai = project.get_openai_client()

# クライアント側でデータを取得（認証済みセッションの user_id を使う）
history = {
    "user_id": "emp-12345",
    "history": [
        {"date": "2026-03-22", "type": "精算申請",
         "summary": "大阪出張（3/15-3/17）旅費精算。金額: 85,000円。ステータス: 承認済み。"},
    ],
}

conv = openai.conversations.create()

response = openai.responses.create(
    conversation=conv.id,
    input=[
        # 「関数が呼ばれた」事実を注入
        {"type": "function_call", "name": "get_user_history",
         "arguments": "{}", "call_id": "preloaded_001"},
        # 「結果が返ってきた」事実を注入
        {"type": "function_call_output", "call_id": "preloaded_001",
         "output": json.dumps(history, ensure_ascii=False)},
        # ユーザーの質問
        {"role": "user", "content": "前回の大阪出張の精算はどうなりましたか？"},
    ],
    extra_body={
        # ↓ FunctionTool を登録していない通常のエージェント
        "agent_reference": {"name": "travel-expense-helpdesk", "type": "agent_reference"},
    },
)
print(response.output_text)
# → 「大阪出張（3/15-3/17）の旅費精算は承認済み、85,000円です。
#     旅費規程 第11条 および操作マニュアル 3.3 に...」
```

検証結果（2026-04-14）:
- `travel-expense-helpdesk`（file_search のみ、FunctionTool なし）→ ✅ 動作
- `travel-expense-helpdesk-fc`（FunctionTool あり）→ ✅ 動作
- どちらも file_search の知識と function_call_output のデータを組み合わせて回答

#### 比較

| | 通常 FC（2往復） | **FC 事前注入（1往復）** | assistant 注入 |
|---|---|---|---|
| 往復数 | 2+ | **1** | 1 |
| エージェント側の FunctionTool 登録 | **必要** | **不要** | 不要 |
| エージェントの自律判断 | ✅ 必要時だけ呼ぶ | ❌ 毎回渡す | ❌ 毎回渡す |
| データの扱い | ツール結果 | ツール結果 | プロンプト内テキスト |

#### ポータル互換性の利点

**FC 事前注入はエージェント定義を変更しない**ため、ポータルの全機能がそのまま使える。
これが通常の Function Calling（FunctionTool 登録）との最大の違い。

| ポータル機能 | FunctionTool 登録あり | FC 事前注入（登録なし） |
|-------------|---------------------|----------------------|
| プレイグラウンド | ❌ `No tool output found` | ✅ 通常通り使える |
| ポータル評価 | ❌ 同上 | ✅ 通常通り使える |
| Red Teaming | ❌ 同上 | ✅ 通常通り使える |
| SDK テスト | ✅（2往復） | ✅（1往復） |

エージェント自体は file_search だけのシンプルな構成で、ポータルからの操作・テスト・評価に一切支障がない。
ユーザー固有データが必要な場面では、クライアント側で FC 事前注入を使って input を組み立てる。
**エージェント定義とデータ注入の責務が完全に分離される**のが設計上のメリット。

#### assistant 注入との違い

どちらも1往復・エージェント定義の変更不要という点は同じ。違いはデータの「ロール」:

- **assistant 注入**: データが「エージェント自身の過去の発言」として扱われる
- **FC 事前注入**: データが「ツール実行結果」として扱われる → file_search の結果等と同列の参照データ

後者の方が「エージェントの発言を捏造する」感覚がなく、セマンティクスとして正直。

#### 注意事項

- 公式ドキュメントに記載のないパターン。将来の API 変更で動かなくなる可能性がある
- `call_id` は任意の文字列で、①と②が一致していればよい
- `name` も任意の文字列。エージェントに FunctionTool が登録されていなくても受け入れられる
- **本番での採用は、公式ドキュメントでの言及を待つか、十分なテストの上で判断すべき**

## Responses API input に渡せる全タイプの検証

> 2026-04-14 検証

FC 事前注入パターンの発見を受け、「input 配列に渡せるのはメッセージだけではなく、type ベースの多様なアイテムがある」ことを体系的に検証した。

### OpenAI Python SDK の ResponseInputItemParam

OpenAI Python SDK（`openai/types/responses/response_input_item_param.py`）で定義される `ResponseInputItemParam` は **28 種類の Union 型**:

| カテゴリ | 型名 | type 値 |
|---------|------|---------|
| メッセージ | EasyInputMessage | *(role ベース、type なし)* |
| メッセージ | Message | `message` |
| メッセージ | ResponseOutputMessage | `message` (output) |
| ツール呼び出し | ResponseFunctionToolCallParam | `function_call` |
| ツール結果 | FunctionCallOutput | `function_call_output` |
| ツール呼び出し | ResponseCustomToolCallParam | `custom_tool_call` |
| ツール結果 | ResponseCustomToolCallOutputParam | `custom_tool_call_output` |
| ツール呼び出し | ResponseFileSearchToolCallParam | `file_search_call` |
| ツール呼び出し | McpCall | `mcp_call` |
| ツール管理 | McpListTools | `mcp_list_tools` |
| MCP 承認 | McpApprovalRequest | `mcp_approval_request` |
| MCP 承認 | McpApprovalResponse | `mcp_approval_response` |
| Web 検索 | ResponseFunctionWebSearchParam | `web_search_call` |
| コード実行 | ResponseCodeInterpreterToolCallParam | `code_interpreter_call` |
| コンピュータ操作 | ResponseComputerToolCallParam | `computer_call` |
| コンピュータ結果 | ComputerCallOutput | `computer_call_output` |
| シェル | LocalShellCall / ShellCall | `local_shell_call` / `shell_call` |
| シェル結果 | LocalShellCallOutput / ShellCallOutput | `local_shell_call_output` / `shell_call_output` |
| パッチ | ApplyPatchCall | `apply_patch_call` |
| パッチ結果 | ApplyPatchCallOutput | `apply_patch_call_output` |
| 画像生成 | ImageGenerationCall | `image_generation_call` |
| 推論 | ResponseReasoningItemParam | `reasoning` |
| 圧縮 | ResponseCompactionItemParamParam | `compaction` |
| 参照 | ItemReference | `item_reference` |
| 検索 | ToolSearchCall | `tool_search_call` |

### Foundry Agent Service が受け入れる type 値

Foundry にサポート外の type を送ると、エラーメッセージに有効値の一覧が返る。確認されたのは **26 種類**:

```
apply_patch_call, apply_patch_call_output, code_interpreter_call, compaction,
computer_call, computer_call_output, custom_tool_call, custom_tool_call_output,
file_search_call, function_call, function_call_output, image_generation_call,
item_reference, local_shell_call, local_shell_call_output, mcp_approval_request,
mcp_approval_response, mcp_call, mcp_list_tools, message, reasoning,
shell_call, shell_call_output, tool_search_call, tool_search_output, web_search_call
```

### 経費精算シナリオでのデータ注入テスト

「ユーザー固有の過去データ（大阪出張、85,000 円、承認済み）をエージェントに渡して回答に反映させる」というシナリオで、利用可能な 7 パターンを検証した。

#### テスト条件
- エージェント: `travel-expense-helpdesk`（file_search のみ、FunctionTool 未登録）
- 注入データ: `{"user_id": "emp-12345", "history": [{"date": "2026-03-22", "type": "精算申請", "summary": "大阪出張（3/15-3/17）旅費精算。金額: 85,000円。ステータス: 承認済み。"}]}`
- 質問: 「前回の大阪出張の精算はどうなりましたか？」
- データ反映チェック: 回答に「大阪」「85,000」「承認」の 3 つが含まれるか

#### 結果一覧

| パターン | 方式 | HTTP | データ反映 | 備考 |
|----------|------|------|-----------|------|
| **0: FC 事前注入** | `function_call` + `function_call_output` | ✅ | ✅ 3/3 | **唯一の完全動作パターン** |
| A: developer ロール | `{"role": "developer", ...}` | ❌ 400 | — | `Invalid value` — Foundry が developer/system ロールを拒否 |
| A2: instructions パラメータ | `instructions="..."` | ❌ 400 | — | `Not allowed when agent is specified` |
| A3: assistant ロール | `{"role": "assistant", ...}` | ✅ | ❌ 0/3 | HTTP OK だがエージェントがデータを無視 |
| B: item_reference | `{"type": "item_reference", ...}` | ✅ | △ 2/3 | 「大阪」「承認」は反映、「85,000」は欠落 |
| C: file_search_call | `{"type": "file_search_call", ...}` | ✅ | ❌ 0/3 | 「個人情報は開示できません」と拒否 |
| D: mcp_call | `{"type": "mcp_call", ...}` | ✅ | ❌ 0/3 | エージェントがデータを無視 |

#### 各パターンの詳細

**パターン 0: FC 事前注入（function_call + function_call_output）** ✅

```python
input = [
    {"type": "function_call", "name": "get_user_history",
     "arguments": "{}", "call_id": "preloaded_001"},
    {"type": "function_call_output", "call_id": "preloaded_001",
     "output": json.dumps(history, ensure_ascii=False)},
    {"role": "user", "content": question},
]
```
エージェントはデータを「ツール実行結果」として認識し、file_search の知識と組み合わせて回答する。

**パターン A: developer / system ロール** ❌

```python
input = [
    {"type": "message", "role": "developer",
     "content": [{"type": "input_text", "text": context}]},
    {"role": "user", "content": question},
]
```
Foundry は `agent_reference` 使用時に developer/system ロールをブロックする。EasyInputMessage 形式でも typed Message 形式でも結果は同じ。

**パターン A2: instructions パラメータ** ❌

```python
response = client.responses.create(
    conversation=conv.id,
    input=question,
    instructions="以下のユーザーデータを参照してください: ...",
    extra_body={"agent_reference": {...}},
)
```
エージェント指定時は `instructions` パラメータ自体が禁止。

**パターン A3: assistant ロール** ⚠️

```python
input = [
    {"role": "assistant", "content": f"ユーザーの過去データ:\n{context}"},
    {"role": "user", "content": question},
]
```
HTTP は成功するが、エージェントはこのデータを「過去の自分の発言」として扱いつつ、実際の回答では参照しない。「個別の精算状況は開示できません」等の汎用回答を返す。

**パターン B: item_reference** △

```python
# 1. 別の会話でデータを含むレスポンスを作成
setup_response = client.responses.create(
    input=[
        {"role": "user", "content": "以下を記録してください: " + context},
    ],
)
# 2. その結果を item_reference で新会話に注入
input = [
    {"type": "item_reference", "id": setup_response.output[0].id},
    {"role": "user", "content": question},
]
```
部分的にデータが反映されるが、全項目が安定して含まれるわけではない。参照先のコンテキストが完全には展開されない。

**パターン C: file_search_call** ❌

```python
input = [
    {"type": "file_search_call", "id": "fs_preload_001",
     "status": "completed",
     "queries": ["経費精算履歴"],
     "results": [{"file_id": "virtual_001", "filename": "user_history.json",
                  "text": context, "score": 0.99}]},
    {"role": "user", "content": question},
]
```
HTTP は成功するが、エージェントは注入された検索結果を参照せず、自身の file_search を実行して回答する。

**パターン D: mcp_call** ❌

```python
input = [
    {"type": "mcp_call", "id": "mcp_preload_001",
     "name": "get_user_history", "server_label": "user_data_api",
     "arguments": "{}", "output": context},
    {"role": "user", "content": question},
]
```
HTTP は成功するが、エージェントは MCP 結果を無視して汎用回答を返す。

### 結論

Foundry Agent Service でユーザー固有データを確実にエージェントへ注入できるのは **`function_call` + `function_call_output` の事前注入パターンのみ**。

他のアプローチは以下の 3 カテゴリに分類される:

1. **HTTP レベルで拒否**: developer ロール、system ロール、instructions パラメータ → エージェントの振る舞いを上書きするパラメータは Foundry がブロック
2. **HTTP OK だがデータ無視**: assistant ロール、file_search_call、mcp_call → エージェントがデータの存在を認識しても回答に反映しない
3. **部分的に動作**: item_reference → 一部のデータは反映されるが不安定

FC 事前注入が唯一動作する理由は、`function_call_output` がエージェントにとって「ツールが返した確定データ」という最も明確なセマンティクスを持つため。file_search の結果と同じレイヤーで処理され、回答生成の参照データとして扱われる。

### 検証スクリプト

| スクリプト | 内容 |
|-----------|------|
| `agent/test_input_patterns.py` | 全 7 パターンのテスト。パターン選択実行、データ反映チェック、結果サマリ出力 |
