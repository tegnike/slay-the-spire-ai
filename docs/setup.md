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

OpenAI API版で実際にLLM判断させる場合は、Slay the Spireを起動するプロセスに `OPENAI_API_KEY` を渡してください。APIキーは `config.properties` には書かない方針です。

```bash
export OPENAI_API_KEY="..."
cd /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
./run_modded.sh
```

別モデルを試す場合は、設定作成時に `--command` で指定します。

```bash
python3 tools/configure_communication_mod.py --command 'python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start --use-openai-api --openai-model gpt-5-mini'
```

## 5. 起動手順

1. Slay the Spireを終了する
2. このプロジェクトから `./run_modded.sh` を実行する
3. ModTheSpire画面で BaseMod と CommunicationMod を有効化して Play
4. CommunicationMod がAIプロセスを起動する
5. `logs/session.log` に受信状態と返答コマンドが出ることを確認する

## 6. 最初の確認ポイント

うまく接続できている場合:

- ModTheSpireのログにAIプロセスの起動が出る
- `logs/session.log` が作成される
- `logs/states.jsonl` にゲーム状態JSONが追記される
- `logs/actions.jsonl` に返したコマンドが追記される

接続に失敗する場合:

- CommunicationMod が `ready` を受け取れていない
- `command=` のパスが間違っている
- Pythonが見つからない
- Modのjar配置または有効化ができていない
- Java Runtimeがなく、ModTheSpireを起動できていない

## 7. 次の拡張

疎通確認後、次の順で拡張します。

1. 戦闘状態から合法手一覧を作る
2. OpenAI APIに合法手IDだけ選ばせる
3. カード報酬、マップ、焚き火、ショップを個別対応する
4. 1ランのログを保存して、負け筋を解析する
