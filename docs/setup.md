# Setup

## 1. 前提

Mac版 Steam の Slay the Spire は次の場所に見つかっています。

```text
/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire
```

CommunicationMod を使うには、通常は以下が必要です。

- Slay the Spire
- ModTheSpire
- BaseMod
- CommunicationMod

CommunicationMod は、ゲーム状態が安定したタイミングでJSONを外部プロセスのstdinへ送り、外部プロセスから `PLAY`, `END`, `CHOOSE`, `PROCEED`, `RETURN`, `STATE` などのコマンドをstdoutで受け取ります。

## 2. Javaについて

このマシンでは、通常のターミナルからは `java` が見えていません。

```text
Unable to locate a Java Runtime.
```

ただし、Mac版Slay the Spire同梱のJava 8は見つかっています。

```text
/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app/Contents/Resources/jre/bin/java
```

このプロジェクトの `run_modded.sh` は、その同梱JavaでWorkshop版の `ModTheSpire.jar` を起動し、`basemod,CommunicationMod` を直接指定します。

## 3. Modの配置

Steam Workshopで BaseMod / ModTheSpire を入れてください。

- ModTheSpire: `https://steamcommunity.com/sharedfiles/filedetails/?id=1605060445`
- BaseMod: `https://steamcommunity.com/sharedfiles/filedetails/?id=1605833019`

CommunicationMod はWorkshopページが使えない可能性があるため、GitHub版のjarを使う想定です。

CommunicationMod のREADMEでは、jarを ModTheSpire の `mods` ディレクトリへコピーし、ModTheSpireで有効化する手順になっています。

現在、以下を配置済みです。

```text
/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app/Contents/Resources/mods/CommunicationMod.jar
```

GitHub版のModTheSpire/BaseModは古いため、退避済みです。実際の起動ではSteam Workshop版のModTheSpire/BaseModを使う前提です。

```text
/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app/Contents/Resources/mods/BaseMod.github-v5.5.0.jar.disabled
/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app/Contents/Resources/ModTheSpire.github-v3.6.3.jar
```

## 4. CommunicationModの設定

Macの SpireConfig は通常ここです。

```text
/Users/user/Library/Preferences/ModTheSpire/
```

CommunicationMod 用の設定ファイルに、起動したいAIプロセスを `command=` として書きます。

このリポジトリでは次で設定ファイルを作れます。

```bash
cd /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
python3 tools/configure_communication_mod.py
```

作成される想定のコマンド:

```text
python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start --use-openai-api --openai-model gpt-5.4-mini
```

同時に `runAtGameStart=true` を設定するため、Mod起動時にAIプロセスが自動起動します。
OpenAI API実行に失敗した場合、または `OPENAI_API_KEY` が未設定の場合は、ゲームを止めないためルールベース判断に戻ります。

OpenAI API版で実際にLLM判断させる場合は、Slay the Spireを起動するプロセスに `OPENAI_API_KEY` を渡してください。APIキーは `config.properties` やドキュメントには書かない方針です。

```bash
export OPENAI_API_KEY="..."
cd /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
./run_modded.sh
```

ランごとにログを分けたい場合は、起動前に `STS_AI_LOG_DIR` を設定します。

```bash
cd /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
RUN_ID="run-$(date +%Y%m%d-%H%M%S)"
export STS_AI_LOG_DIR="$PWD/logs/$RUN_ID"
mkdir -p "$STS_AI_LOG_DIR"
OPENAI_API_KEY="..." ./run_modded.sh
```

別モデルを試す場合は、設定作成時に `--command` で指定します。

```bash
python3 tools/configure_communication_mod.py --command 'python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start --use-openai-api --openai-model gpt-5-mini'
```

`ai-agent-game-streamer` のナレーション runtime UI と接続する場合は、先に relay/UI を起動してから、AIコマンドに `--narration-ui` を追加します。

```bash
cd /Users/user/WorkSpace/ai-agent-game-streamer
npm run narration:relay
npm run narration:dev

cd /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
python3 tools/configure_communication_mod.py --with-narration-ui
```

relay URL を変える場合は `--narration-url ws://localhost:3010/ws/narration` を指定します。デフォルトではUI側の再生完了通知を待ってからゲームコマンドを返します。進行速度を優先する場合はAIコマンドへ `--narration-no-wait` を付けてください。

このオプションが有効なときだけ、OpenAI / Codex へのプロンプトに短い実況用の `narration_mode` / `narration_text` / `narration_emotion` の生成指示を追加します。送信した本文は `actions.jsonl` に、モデルが生成した本文は `openai_decisions.jsonl` または `codex_decisions.jsonl` に記録されます。

ナレーション送信時は、価値の低い進行報告や同じ意味の反復文をスキップすることがあります。直近に送った実況文の履歴を使って重複を抑え、ナレーション runtime UI へは本文と一緒に公式 emotion の `neutral` / `happy` / `angry` / `sad` / `thinking` のいずれかを送ります。

更新後の narration runtime では、`pace` / `intensity` / `priority` / `queuePolicy` / `maxQueueMs` も送ります。リーサルや危険ターンは `replaceIfHigherPriority` で優先し、低価値な遷移は `dropIfBusy` でキューを詰まらせないようにします。発話しない判断も `narration:suppressed` として relay に通知し、`skipped` / `failed` の `reason` は `actions.jsonl` に記録します。

## 5. 起動手順

1. Slay the Spireを終了する
2. このプロジェクトから `OPENAI_API_KEY="..." ./run_modded.sh` を実行する
3. ModTheSpireが `basemod,CommunicationMod` 指定で起動する
4. CommunicationMod がAIプロセスを起動する
5. AIが `ready` を返し、`--auto-start` により `START IRONCLAD 0` を返す
6. `logs/session.log` に受信状態と返答コマンドが出ることを確認する

## 6. 最初の確認ポイント

うまく接続できている場合:

- ModTheSpireのログにAIプロセスの起動が出る
- `logs/session.log` が作成される
- `logs/states.jsonl` にゲーム状態JSONが追記される
- `logs/actions.jsonl` に返したコマンドが追記される
- OpenAI APIを使っている場合は `logs/openai_decisions.jsonl` に判断理由が追記される

接続に失敗する場合:

- CommunicationMod が `ready` を受け取れていない
- `command=` のパスが間違っている
- Pythonが見つからない
- Modのjar配置または有効化ができていない
- Java Runtimeがなく、ModTheSpireを起動できていない

OpenAI APIで401/403が出る場合:

- AIプロセスはその実行中のOpenAI API呼び出しを無効化し、ルールベース判断へフォールバックする
- APIキーの権限、期限、課金状態を確認する
- APIキーはCommunicationModの `config.properties` には保存せず、起動プロセスの環境変数で渡す

## 7. 現在のAI挙動

現在は、コード側が合法手一覧を作り、OpenAI Responses APIには `action_id` だけを選ばせます。API失敗時、未設定時、不正な判断時はルールベースfallbackを実行します。

主な対応済み画面:

- メインメニュー: `--auto-start` で Ironclad / Ascension 0 を開始
- 戦闘: カード、対象、ポーション、ターン終了を合法手化
- 戦闘報酬: レリック、カード、ゴールド、ポーションを回収
- カード報酬: Act 1の前のめりな攻撃、強カード、防御カードを簡易評価
- GRID: purge / upgrade / transform / selection を用途別に選択して確定
- MAP: HP、ゴールド、休憩所、将来エリートを見て評価
- REST: HP55%以下では休憩、それ以外はsmithを優先
- SHOP: 入退店ループを避け、削除や高評価カード/レリック/ポーションだけ購入
- FTUE: `KEY Confirm 30` でゲーム内Confirmを送る

OpenAI API判断には安全弁があります。

- 高被弾時に防御/ポーションfallbackを無視した攻撃を選んだ場合はfallbackへ戻す
- HPに余裕があるエリート/ボスで高打点攻撃を選んだ場合は過剰に潰さない
- 無被弾ターンに純ブロックカードを選んだ場合はfallbackへ戻す
- GRID / REST / EVENT / CARD_REWARD / MAP でルール評価より大きく劣る選択はfallbackへ戻す
- 同一戦闘ターンのポーション連打を抑制する

## 8. ログ分析

ラン別ログを要約するには:

```bash
python3 tools/summarize_run.py --log-dir logs/run-YYYYMMDD-HHMMSS --last 120
```

`states.jsonl` と `actions.jsonl` の末尾を並べ、floor / screen / room / HP / hand / monsters / choices / command を短く表示します。一定回数以上同じ画面とコマンドが繰り返される場合は `Potential loops` として表示します。

## 9. 次の拡張

疎通確認後、次の順で拡張します。

1. Sentries / Lagavulin / Gremlin Nob の専用戦闘ヒューリスティックを強化する
2. Large Slimeなど分裂敵のHP調整を追加する
3. Act 2以降の敵別判断を追加する
4. カード報酬、ショップ、イベントの長期評価を改善する
5. 1ラン単位の検証用に `--stop-on-game-over` や `--max-floor` を追加する
