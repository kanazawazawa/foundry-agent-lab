# TravelExpense ヘルプデスク AI エージェント

架空の旅費精算システム「TravelExpense」の社内ヘルプデスク AI エージェント。
社員からの旅費規程・システム操作・FAQ に関する質問に、ナレッジドキュメントを検索して回答します。

> **注意**: このエージェントは Foundry の各種機能を検証するためのサンプルです。
> 検証目的に応じて Instructions やナレッジを変更する可能性があります。

## 構成

| ファイル | 役割 |
|----------|------|
| `create_agent.py` | Vector Store 作成 → ナレッジアップロード → Prompt Agent 作成 |
| `test_agent.py` | 対話モード / 単発質問で動作確認 |
| `knowledge/` | ナレッジドキュメント（旅費規程・操作マニュアル・FAQ） |

## アーキテクチャ

- **Microsoft Foundry** Prompt Agent（`PromptAgentDefinition`）
- **file_search** ツールで Vector Store 内のナレッジを検索
- **gpt-5.4** モデル（`MODEL_DEPLOYMENT_NAME` で変更可）

## 使い方

```bash
# エージェント作成（Vector Store + ナレッジアップロード + エージェント）
python agent/create_agent.py

# 動作確認（単発質問）
python agent/test_agent.py -q "大阪出張の日当はいくら？"

# 動作確認（対話モード）
python agent/test_agent.py
```

## 現在の仕込みバグ

評価デモ用に、Instructions 内「緊急改定対応」セクションで意図的に誤った値を設定しています。

| 項目 | バグ入りの値 | 正しい値（ナレッジ準拠） |
|------|-------------|--------------------------|
| 一般社員の宿泊出張日当 | 2,500円/泊 | 3,000円/泊（第5条） |
| 課長職の宿泊出張日当 | 3,500円/泊 | 4,000円/泊（第5条） |
| グリーン車利用条件 | 課長職以上・200km以上 | 部長職以上・300km以上（第4条4項） |
| 精算申請期限 | 5営業日以内 | 10営業日以内（第11条） |

このバグは [eval/](../eval/) の評価で検出されます。
