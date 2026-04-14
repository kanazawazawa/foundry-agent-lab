# Foundry Portal — プロダクトフィードバック

報告日: 2026-04-13

## 1. Built-in Evaluator に不要な「カスタムプロンプト」入力が必須

**対象**: Foundry Portal > 評価の作成 > モデルの構成

**現象**:
- `builtin.coherence` や `builtin.response_completeness` 等の built-in evaluator を選択した場合でも、「カスタムプロンプトの追加」ダイアログで**開発者メッセージの入力が必須**になっている
- 入力しないと「保存」して次のステップに進めない

**期待動作**:
- Built-in evaluator には内部の prompty テンプレート（例: [coherence.prompty](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/evaluation/azure-ai-evaluation/azure/ai/evaluation/_evaluators/_coherence/coherence.prompty)）が組み込まれているため、開発者プロンプトは**任意（optional）であるべき**
- SDK/API 経由（OpenAI Evals API）で同じ evaluator を作成する場合、`deployment_name` のみで構成でき、プロンプトの明示指定は不要

**影響**:
- ユーザーが意味のないダミー値（例: "Nothing"）を入れて回避する必要がある
- Built-in の定義が上書きされるのか無視されるのかが不明で、混乱を招く

**再現手順**:
1. Foundry Portal → 評価 → 新しい評価の作成
2. ターゲット・データ・フィールドマッピングを設定
3. 「モデルの構成」で built-in evaluator（例: coherence）の「構成」ボタンをクリック
4. 「カスタムプロンプトの追加」ダイアログが表示され、「プロンプト > 開発者」が必須（*）になっている
5. 空欄のまま「保存」できない

---

## 2. 「カスタムプロンプト」のダミー値が Agent の回答品質を破壊する

**対象**: Foundry Portal > 評価の作成 > モデルの構成 > カスタムプロンプトの追加

**現象**:
- Issue #1 の回避策として開発者メッセージに「Nothing」と入力して評価を実行した
- 結果、Agent が**質問と無関係な回答を返す**ようになり、6件中6件が score=1（FAIL）となった
- 同じ Agent・同じデータセットで SDK から評価した場合は正常動作（期待通りの 3/6 FAIL）

**具体的な症状**:
| Row | 質問 | Agent の回答 | 
|-----|------|-------------|
| 1 | 日当はいくら？ | 緊急改定値を羅列（金額は間違い） |
| 2 | グリーン車は使える？ | 精算期限の話を回答（無関係） |
| 3 | タクシー条件は？ | 緊急改定値4点を羅列（無関係） |
| 4 | 精算期限は？ | 「知りたい内容を教えて」と聞き返し |
| 5 | 領収書の添付方法は？ | 緊急改定値4点を羅列（無関係） |
| 6 | 承認者不在の対処は？ | 緊急改定値4点を羅列（無関係） |

**原因（確定）**:
- 「モデルの構成」の「カスタムプロンプトの追加」ダイアログは **Agent に送る会話テンプレートビルダー** であった（Judge モデル用ではない）
- ダイアログ内のロール:
  - **開発者** = Agent の System prompt / Instructions（必須 *）
  - **ユーザー** = User メッセージ（`+ メッセージ` → `ユーザー` で追加可能）
  - **アシスタント** = Assistant メッセージ（few-shot 例など、`+ メッセージ` → `アシスタント` で追加可能）
- 「Nothing」と入力したことで、Agent の Instructions が実質無効化され、正しく file_search でナレッジを参照できなくなった
- Agent に設定してある Instructions をそのままコピーすれば正常動作する（スクリーンショットで確認済）

**問題点**:
1. **Agent の Instructions が自動反映されない**: ポータルは Agent を選択しているのに、Agent 側で管理されている Instructions を自動取得せず、手動でコピー＆ペーストさせる
2. **ラベルが紛らわしい**: 「カスタムプロンプトの追加」というラベルから、Judge モデル用のカスタマイズと誤認しやすい。実際は Agent への入力テンプレート
3. **開発者メッセージが必須**: Agent の Instructions をそのまま使いたい場合でも空欄にできない
4. **同期漏れリスク**: Agent の Instructions を変更するたびに評価設定も手動更新が必要。SDK では不要

**期待動作**:
- Agent を選択した時点で、開発者メッセージに Agent の Instructions を**自動プリフィル**すべき（編集可能で良い）
- または、「Agent の設定をそのまま使う」オプションを設けて開発者メッセージを任意にすべき
- ダイアログのラベルを「Agent への入力テンプレート」等に変更し、Judge 用ではないことを明示すべき

**比較**:
| 手段 | 開発者メッセージ | Agent 応答品質 | 評価結果 |
|------|-----------------|---------------|---------|
| SDK (`05_create_eval_completeness_only.py`) | 指定なし | 正常 | 3/6 FAIL（期待通り） |
| Portal（ダミー値 "Nothing"） | "Nothing" | 破壊的に劣化 | 6/6 FAIL（全滅） |

---

## 3. FunctionTool 付きエージェントがポータルのプレイグラウンドで動作しない

**報告日**: 2026-04-14

**対象**: Foundry Portal > エージェント > チャット（プレイグラウンド）

**現象**:
- SDK で `FunctionTool` を登録したエージェントに対し、ポータルのプレイグラウンドで Function Calling を発火させる質問を送信
- エージェントは `get_user_history` を呼ぶ判断をするが、ポータル側にクライアント実行ハンドラがない
- 結果: `No tool output found for function call call_dJTRtvHVURonoAREzC0bHuN3.` エラーで会話が停止

**影響**:
- FunctionTool を持つエージェントは**ポータルのプレイグラウンドでテストできない**
- Function Calling を発火しない質問（例: 「こんにちは」）も、エージェントが予防的に関数を呼ぶ場合がある
- **テストは SDK スクリプト経由のみ**に限定される

**関連する確認事項**:
- ポータルで FunctionTool の定義は**表示されない**（存在は認識している — メタデータに `get_user_history` と表示）
- ポータルで Instructions を編集・保存しても FunctionTool は**消えない**（version 2 → 3 → 4 で検証済み）
- 公式ドキュメントには「ポータルでは関数定義の追加、削除、更新はサポートされていません」と記載があるが、**実行不可の記載はない**

**期待動作**（いずれか）:
1. プレイグラウンドで FunctionTool のモックレスポンスを入力できる UI を提供
2. または、FunctionTool が登録されたエージェントに対し「この機能はプレイグラウンドでテストできません。SDK をご利用ください」と明示的に案内
3. または、プレイグラウンドでは FunctionTool を無視して file_search 等のサーバーサイドツールのみで回答するフォールバック

**再現手順**:
1. SDK で `FunctionTool` 付きエージェントを作成（`agent/create_fc_agent.py`）
2. ポータルでエージェントを開く → チャットタブ
3. 「過去の履歴を10件取ってきてほしい」と入力
4. → `No tool output found for function call call_...` エラー
