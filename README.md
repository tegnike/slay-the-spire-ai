# Slay the Spire AI Player

Slay the Spire を Mod 経由で外部 AI プロセスにつなぎ、ゲーム状態 JSON から合法手を選んで操作する実験用プレイヤーです。

画面認識やキーボードマクロではなく、CommunicationMod が出す状態を Python が受け取り、`PLAY` / `END` / `CHOOSE` / `CONFIRM` / `PROCEED` などのコマンドを返します。

```text
Slay the Spire
  -> ModTheSpire + BaseMod + CommunicationMod
  -> stdin/stdout
  -> sts_ai_player.py
  -> OpenAI API or rule-based policy
```

現在の主目的は、勝率最適化ではなく「ゲームと AI 判断ループを安定して接続し、ランを自動進行させる」ことです。

## 主要ファイル

- `sts_ai_player.py`: CommunicationMod から起動される AI プロセス
- `_sts_ai_player/`: AI 本体の実装
- `run_modded.sh`: Mac アプリ本体経由で ModTheSpire を起動するランチャー
- `tools/configure_communication_mod.py`: CommunicationMod の `config.properties` 作成補助
- `tools/summarize_run.py`: ランログの要約とループ検知
- `docs/setup.md`: Mod 導入と起動の詳細
- `docs/session-notes-2026-04-26.md`: 初回構築時の作業メモ
- `logs/`: 実行時ログの出力先

## 前提

このリポジトリは、Mac 版 Steam の Slay the Spire でのみ動作確認しています。

Windows は現時点では未対応・未検証です。AI 本体は CommunicationMod の stdin/stdout プロトコルなので移植できる可能性はありますが、`run_modded.sh`、CommunicationMod 設定パス、Steam / Mod の配置パスは macOS 前提です。

確認済みのゲーム配置:

```text
/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire
```

必要な Mod:

- ModTheSpire
- BaseMod
- CommunicationMod

この環境では ModTheSpire / BaseMod は Steam Workshop 版を使い、CommunicationMod は GitHub Release の jar をゲーム側 `mods` ディレクトリへ置く構成で確認しています。詳しい配置は [docs/setup.md](/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/docs/setup.md) を見てください。

## プレイ手順

### 1. 疎通テスト

まず AI プロセス単体でルールベース判断が動くことを確認します。

```bash
cd /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
python3 sts_ai_player.py --test
```

OpenAI API まで含めて確認する場合:

```bash
OPENAI_API_KEY="..." python3 sts_ai_player.py --test --use-openai-api --openai-model gpt-5.4-mini
```

### 2. CommunicationMod 設定を作る

通常プレイでは、CommunicationMod が起動する AI コマンドを設定ファイルに書きます。

```bash
python3 tools/configure_communication_mod.py
```

作成される主な内容:

```properties
command=python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start --use-openai-api --openai-model gpt-5.4-mini
runAtGameStart=true
```

`runAtGameStart=true` により Mod 起動時に AI プロセスが自動起動します。`--auto-start` により、メインメニューから Ironclad / Ascension 0 のランを開始します。

ルールベースだけで動かしたい場合は、`--use-openai-api` を外したコマンドで設定します。

```bash
python3 tools/configure_communication_mod.py \
  --command 'python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start'
```

### 3. Mod 付きで起動する

OpenAI API 版でプレイする場合:

```bash
OPENAI_API_KEY="..." ./run_modded.sh
```

ランごとにログを分ける場合:

```bash
RUN_ID="run-$(date +%Y%m%d-%H%M%S)"
export STS_AI_LOG_DIR="$PWD/logs/$RUN_ID"
mkdir -p "$STS_AI_LOG_DIR"
OPENAI_API_KEY="..." ./run_modded.sh
```

`run_modded.sh` は `launcher_opts.toml` を一時的に差し替え、Mac アプリ本体 `Contents/MacOS/SlayTheSpire` 経由で Workshop 版 ModTheSpire を起動します。直接 `jre/bin/java -jar ModTheSpire.jar` すると Mac の LWJGL/OpenGL 初期化でクラッシュすることがあったため、この起動方法にしています。

### 4. 動作確認

接続できている場合、ModTheSpire 側に `CommunicationMod` が表示され、AI プロセスから `ready` が返ります。

AI 側では以下のログが増えます。

```bash
tail -f logs/session.log
```

主なログ:

- `states.jsonl`: CommunicationMod から受信したゲーム状態
- `actions.jsonl`: AI が返したコマンド
- `openai_requests.jsonl`: OpenAI API へ送った判断 payload
- `openai_decisions.jsonl`: OpenAI API の判断結果
- `codex_decisions.jsonl`: Codex CLI 判断を使った場合の結果

ラン別ログを要約する場合:

```bash
python3 tools/summarize_run.py --log-dir logs/run-YYYYMMDD-HHMMSS --last 120
```

## AI の判断方式

コード側が現在画面で実行可能な合法手リストを作り、OpenAI API にはその中の `action_id` だけを選ばせます。ゲームへ送るコマンドは、コード側が生成した合法手に限定します。

OpenAI API 判断では、ルールベースの fallback action を候補として提示しません。合法な `action_id` を選べた場合はそのまま実行し、不正な `action_id` など LLM 出力エラー時だけルールベース判断へ戻します。API キー未設定、認証エラー、API 呼び出し失敗などは見落とさないよう停止します。

比較用に Codex CLI を使う場合は `--use-codex` を指定できます。デフォルトの Codex モデルは `gpt-5.3-codex` です。

主な対応済み画面:

- メインメニュー: `--auto-start` で Ironclad / Ascension 0 を開始
- 戦闘: カード、対象、ポーション、ターン終了を合法手化
- 戦闘報酬: レリック、カード、ゴールド、ポーションを回収
- カード報酬: 序盤攻撃、強カード、防御カードを簡易評価
- GRID: 削除、強化、変化、選択系画面を用途別に処理
- MAP: HP、ゴールド、休憩所、将来エリートを見て評価
- REST: 低 HP や直近の強制 Elite/Boss を見て休憩か smith を選択
- SHOP: 入退店ループを避け、削除や高評価候補だけ購入
- FTUE: 必要に応じてゲーム内 Confirm を送る

## よく使うオプション

```bash
# 指定キャラクター / アセンションで開始
python3 sts_ai_player.py --auto-start --character IRONCLAD --ascension 0

# 指定 floor 到達後に待機
python3 sts_ai_player.py --auto-start --max-floor 10

# 死亡画面で次ランを自動開始せず待機
python3 sts_ai_player.py --auto-start --stop-on-game-over

# OpenAI モデル変更
python3 sts_ai_player.py --auto-start --use-openai-api --openai-model gpt-5-mini
```

設定ファイルに反映する場合は `tools/configure_communication_mod.py --command '...'` で上記コマンドを指定します。

## 確認済みの到達点

2026-04-26 時点では、OpenAI API 込みで Neow 選択、戦闘、戦闘報酬、カード報酬、GRID、休憩所、マップ、Act 1 エリート突破まで実走確認済みです。

まだ勝率を狙う段階ではありません。特に Act 1 大型敵、分裂敵、Act 2 以降の敵別判断、長期的なカード報酬 / ショップ / イベント評価には改善余地があります。

## トラブルシュート

CommunicationMod が AI プロセスを起動しない場合:

- `config.properties` の `command=` のパスを確認する
- `runAtGameStart=true` が入っているか確認する
- ModTheSpire で `basemod,CommunicationMod` が有効になっているか確認する
- `python3` が実行できるか確認する

OpenAI API 版が止まる場合:

- `OPENAI_API_KEY` または `STS_AI_OPENAI_API_KEY` が起動プロセスに渡っているか確認する
- API キーの権限、期限、課金状態を確認する
- まず `python3 sts_ai_player.py --test --use-openai-api --openai-model gpt-5.4-mini` を実行する

ModTheSpire の直接起動でクラッシュする場合:

- `./run_modded.sh` から起動する
- Mac アプリ同梱 Java と Workshop 版 ModTheSpire / BaseMod を使う

## 詳細資料

- [docs/setup.md](/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/docs/setup.md): Mod 配置、CommunicationMod 設定、起動確認の詳細
- [docs/session-notes-2026-04-26.md](/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/docs/session-notes-2026-04-26.md): 初回構築時に確認したパス、ログ、判断メモ
