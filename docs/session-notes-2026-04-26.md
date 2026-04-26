# Slay the Spire AI Play Session Notes

Date: 2026-04-26
Machine: Mac mini / macOS
Game: Steam版 Slay the Spire
Workspace:

```text
/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
```

## 目的

Slay the SpireをAIにプレイさせるため、画面認識ではなく、Mod経由でゲーム状態JSONを取得し、外部プロセスからコマンドを返して操作する構成を作った。

採用した方式:

```text
Slay the Spire
  -> ModTheSpire + BaseMod + CommunicationMod
  -> stdin/stdout
  -> Python AI process
  -> START / PLAY / END / CHOOSE / CONFIRM / PROCEED / RETURN / LEAVE / STATE / WAIT
```

## 参考にしたもの

- CommunicationMod: https://github.com/ForgottenArbiter/CommunicationMod
- spirecomm: https://github.com/ForgottenArbiter/spirecomm
- ModTheSpire: https://steamcommunity.com/sharedfiles/filedetails/?id=1605060445
- BaseMod: https://steamcommunity.com/sharedfiles/filedetails/?id=1605833019

CommunicationModは、ゲーム状態が安定したタイミングでJSONを外部プロセスへ送り、外部プロセスからコマンド文字列を受け取ってゲームを操作するMod。

代表的なコマンド:

```text
START IRONCLAD 0
PLAY 2 0
END
CHOOSE 0
CONFIRM
PROCEED
RETURN
LEAVE
STATE
```

## 作成したファイル

```text
slay-the-spire-ai/
  README.md
  run_modded.sh
  sts_ai_player.py
  docs/
    setup.md
    session-notes-2026-04-26.md
  tools/
    configure_communication_mod.py
  downloads/
    BaseMod.jar
    CommunicationMod.jar
    ModTheSpire.zip
    ModTheSpire/
      ModTheSpire.jar
      MTS.sh
      MTS.cmd
  logs/
    session.log
    states.jsonl
    actions.jsonl
```

重要なのは以下。

- `sts_ai_player.py`: CommunicationModから起動されるAIプロセス
- `tools/configure_communication_mod.py`: CommunicationModの設定ファイルを作るスクリプト
- `run_modded.sh`: Macアプリ本体経由でModTheSpireを起動するランチャー
- `logs/states.jsonl`: CommunicationModから受信したゲーム状態
- `logs/actions.jsonl`: AIが返したコマンド

## ローカル環境で確認したパス

Steam版Slay the Spire:

```text
/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire
```

Macアプリ内Resources:

```text
/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app/Contents/Resources
```

ゲーム同梱Java:

```text
/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app/Contents/Resources/jre/bin/java
```

確認したJavaバージョン:

```text
openjdk version "1.8.0_252"
OpenJDK Runtime Environment (AdoptOpenJDK)(build 1.8.0_252-b09)
OpenJDK 64-Bit Server VM (AdoptOpenJDK)(build 25.252-b09, mixed mode)
```

通常のターミナルでは `java` が見えていなかった。

```text
Unable to locate a Java Runtime.
```

そのため、Slay the Spire同梱JREを使う構成にした。

## Steam Workshopで導入したもの

ユーザー側で以下をSteam Workshopからサブスクライブした。

- ModTheSpire
- BaseMod

導入後、以下で確認できた。

```text
/Users/user/Library/Application Support/Steam/steamapps/workshop/content/646570/1605060445/ModTheSpire.jar
/Users/user/Library/Application Support/Steam/steamapps/workshop/content/646570/1605833019/BaseMod.jar
```

WorkshopInfo:

```text
/Users/user/Library/Preferences/ModTheSpire/WorkshopInfo.json
```

`WorkshopInfo.json` にはBaseModが入っていることを確認した。ModTheSpire自体はランチャーがSteam Workshopから見つけていた。

## CommunicationModの配置

GitHub Releaseから取得した `CommunicationMod.jar` を以下へ配置した。

```text
/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app/Contents/Resources/mods/CommunicationMod.jar
```

CommunicationMod release:

```text
https://github.com/ForgottenArbiter/CommunicationMod/releases/download/v1.2.1/CommunicationMod.jar
```

## 古いGitHub版ModTheSpire/BaseModについて

最初にGitHub Releaseから以下も取得した。

- ModTheSpire v3.6.3
- BaseMod v5.5.0

しかし、CommunicationModの `ModTheSpire.json` を見ると:

```json
{
  "modid": "CommunicationMod",
  "name": "Communication Mod",
  "version": "1.2.1",
  "sts_version": "11-30-2020",
  "mts_version": "3.18.1",
  "dependencies": ["basemod"]
}
```

GitHub ReleaseのModTheSpire v3.6.3では古すぎるため、そのまま使わないことにした。

退避したファイル:

```text
/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app/Contents/Resources/ModTheSpire.github-v3.6.3.jar
/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app/Contents/Resources/mods/BaseMod.github-v5.5.0.jar.disabled
```

最終的には、Workshop版のModTheSpire/BaseModを使う構成にした。

## CommunicationMod設定

設定ファイル:

```text
/Users/user/Library/Preferences/ModTheSpire/CommunicationMod/config.properties
```

現在の中身:

```properties
command=python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start
runAtGameStart=true
verbose=false
maxInitializationTimeout=10
```

ポイント:

- `command` にAIプロセスを指定
- `runAtGameStart=true` がないと、CommunicationModは起動しても外部AIプロセスを自動起動しなかった
- `--auto-start` がないと、AIはメインメニューで `STATE` だけ返してランを開始しなかった

設定作成コマンド:

```bash
cd /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
python3 tools/configure_communication_mod.py
```

## 起動コマンド

最終的な起動スクリプト:

```bash
cd /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
./run_modded.sh
```

`run_modded.sh` の意図:

```sh
APP="/Users/user/Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app"
MTS="/Users/user/Library/Application Support/Steam/steamapps/workshop/content/646570/1605060445/ModTheSpire.jar"

# launcher_opts.toml を一時的に ModTheSpire 起動へ差し替える
# Macアプリ本体 Contents/MacOS/SlayTheSpire 経由で起動する
```

直接 `jre/bin/java -jar ModTheSpire.jar` で起動すると、MacのLWJGL/OpenGL初期化で `SIGSEGV` が出ることがあった。そのため最新版の `run_modded.sh` は `launcher_opts.toml` を一時的に差し替え、Macアプリ本体 `Contents/MacOS/SlayTheSpire` からWorkshop版 `ModTheSpire.jar` を起動する。

## 起動時に確認できたログ

正常起動時:

```text
Version Info:
 - Java version (1.8.0_252)
 - Slay the Spire (12-18-2022)
 - ModTheSpire (3.30.3)
Mod list:
 - basemod (5.56.0)
 - CommunicationMod (1.2.1)
```

CommunicationModがAIプロセスと接続できた時:

```text
Communication Mod
communicationmod.CommunicationMod
Received message from external process: ready
```

AIプロセス側も `logs/session.log` にコマンドを記録する。

## AIプロセスの現在の仕様

`sts_ai_player.py` は標準入出力プロトコルで動く。

重要:

- stdoutにはCommunicationModへ返すコマンドだけを出す
- デバッグログはファイルに書く
- 起動時に `ready` をstdoutへ出す

起動時:

```python
print("ready", flush=True)
```

受信:

- stdinから1行JSONを読む
- `logs/states.jsonl` に保存
- `choose_command()` でコマンドを決定
- `logs/actions.jsonl` に保存
- stdoutへコマンドを出力

## AIの現在の判断ロジック

メインメニュー:

```text
START IRONCLAD 0
```

戦闘:

- 攻撃対象はHPが低い敵を選ぶ
- 攻撃カード優先
- 敵の攻撃があり、ブロック不足なら防御カード
- それ以外は対象不要のカード
- 何もできなければ `END`

現在の優先度:

```python
ATTACK_PRIORITY = {
    "Bash": 100,
    "Strike_R": 80,
    "Strike_G": 80,
    "Strike_B": 80,
    "Strike_P": 80,
    "Strike": 75,
}

BLOCK_PRIORITY = {
    "Defend_R": 90,
    "Defend_G": 90,
    "Defend_B": 90,
    "Defend_P": 90,
    "Defend": 85,
}
```

イベント/選択肢:

- `choice_list` または `screen_state.options` がある場合は `CHOOSE 0`
- これによりNeowイベントの `[Talk]` などを選べるようになった

カード報酬など:

- まだ賢く選べていない
- 基本的には `PROCEED`, `RETURN`, `CHOOSE 0`, `STATE` の単純処理

## 実際に動いたところ

最終的に以下まで確認した。

1. `./run_modded.sh` でMod付きSlay the Spire起動
2. ModTheSpireがWorkshop版BaseModとローカルCommunicationModを読み込み
3. CommunicationModがAIプロセスを起動
4. AIが `ready` を返す
5. AIが `START IRONCLAD 0` を返し、新規ラン開始
6. Neowイベントで `CHOOSE 0`
7. Neow's Lamentを取得
8. 最初の戦闘へ進む
9. Bash/Strikeなどをプレイ
10. 複数戦闘を突破

ログ上の例:

```text
MONSTER: Jaw Worm
publish on card use: Bash
publish post combat
MONSTERS SLAIN 1

MONSTER: 2 Louse
publish on card use: Strike_R
publish on card use: Strike_R
MONSTERS SLAIN 2

MONSTER: Cultist
publish on card use: Strike_R
MONSTERS SLAIN 3
```

`Neow's Lament` の効果で序盤の敵がかなり簡単に倒れている。

## 詰まった点と対応

### 1. 通常の `java` が見つからない

問題:

```text
Unable to locate a Java Runtime.
```

対応:

Slay the Spire同梱JREを使用。

```text
SlayTheSpire.app/Contents/Resources/jre/bin/java
```

### 2. GitHub Release版ModTheSpire/BaseModが古い

問題:

- GitHub ReleaseのModTheSpireはv3.6.3
- CommunicationModは `mts_version: 3.18.1` 以上を要求
- BaseModもGitHub Release版は古い

対応:

- Steam Workshop版のModTheSpire/BaseModを使う
- 古いGitHub版は退避

### 3. `runAtGameStart=true` が必要

問題:

CommunicationModは読み込まれていたが、AIプロセスが自動起動しなかった。

対応:

`config.properties` に追加。

```properties
runAtGameStart=true
```

### 4. `--auto-start` が必要

問題:

AIプロセスは起動していたが、メインメニューで `STATE` だけ返していた。

対応:

起動コマンドに `--auto-start` を追加。

```properties
command=python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start
```

### 5. Neowイベントの選択で `CHOOSE [Talk]` が通らなかった

問題:

最初は選択肢の表示テキストを使って:

```text
CHOOSE [Talk]
```

を返していたが、うまく進まなかった。

対応:

選択肢番号で:

```text
CHOOSE 0
```

を返すよう変更した。

### 6. 初回チュートリアル表示 `FTUE`

問題:

初回チュートリアル/説明ポップアップが出ると、CommunicationModの意味コマンドだけでは閉じられないことがある。

旧対応:

`CLICK` / `KEY` はユーザーのPC操作と干渉するため自動送信しない方針に変更した。FTUEでは `WAIT 60` に留め、ユーザー側で初回チュートリアル表示を手動で閉じる。

更新:

CommunicationModの `KEY` はOS操作ではなくゲーム内キーマッピング経由のコマンドであることを確認したため、`FTUE` では以下を返して自動確定するよう変更した。

```text
KEY Confirm 30
```

### 7. 現在止まりやすい画面

現在、AIは `GRID` 画面で止まりやすい。

最後に確認した状態:

```json
{
  "screen_type": "GRID",
  "screen_state": {
    "for_purge": true,
    "num_cards": 1,
    "confirm_up": true,
    "selected_cards": []
  },
  "room_phase": "COMPLETE",
  "floor": 4,
  "room_type": "ShopRoom"
}
```

これはカード削除/選択系の画面。現在は `CHOOSE <index>` が合法手として出ているGRIDではカード選択に対応し、`confirm_up: true` では `CONFIRM` / `PROCEED` を返す。`CHOOSE` が無いGRIDでは座標クリックせず待機する。

## 現在の到達点

できている:

- Mod付きSlay the Spire起動
- CommunicationMod接続
- JSON状態ログ保存
- AIコマンドログ保存
- 自動ラン開始
- Neowイベントの基本進行
- Act 1序盤戦闘の自動プレイ
- `PLAY`, `CHOOSE`, `CONFIRM`, `PROCEED`, `RETURN`, `LEAVE`, `STATE`, `WAIT` の送信
- `CHOOSE` が使えるGRIDのカード選択

未完成:

- `CHOOSE` が出ないGRID/FTUEの自動突破
- カード報酬のまともな選択
- マップ選択の戦略
- 焚き火、ショップ、イベントの個別判断
- 戦闘AIの本格化
- LLM統合
- 失敗時リカバリ

## 現在の起動方法

```bash
cd /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
./run_modded.sh
```

正常なら以下が出る。

```text
Mod list:
 - basemod (5.56.0)
 - CommunicationMod (1.2.1)

Received message from external process: ready
```

## 2026-04-26 追加デバッグと修正

実ゲームを起動しながら `logs/states.jsonl` と `logs/actions.jsonl` を追い、以下を修正した。

### 戦闘報酬の取り逃し

問題:

`COMBAT_REWARD` で `PROCEED` を優先していたため、ゴールドやカード報酬が残っていても次画面へ進むことがあった。その結果、floor 6 時点でもスターター中心のデッキになっていた。

対応:

- `COMBAT_REWARD` 専用の判断を追加
- 優先順は `RELIC > CARD > GOLD > POTION`
- カード報酬画面では既存のカード評価で取得/スキップを判断

実機確認:

```text
COMBAT_REWARD choices ['gold', 'card'] -> CHOOSE 1
CARD_REWARD choices ['searing blow', 'hemokinesis', 'anger'] -> CHOOSE 1
COMBAT_REWARD choices ['gold'] -> CHOOSE 0
COMBAT_REWARD rewards [] -> PROCEED
```

### 手札切れ戦闘の `STATE` ループ

問題:

戦闘中、手札を使い切ると `available_commands` が以下のように `play` なし、`end` ありになる。

```text
['end', 'potion', 'key', 'click', 'wait', 'state']
```

旧コードは `play` と `end` の両方がある時だけ戦闘処理に入っていたため、`STATE` を返し続けた。

対応:

戦闘状態で `end` があれば戦闘判断に入り、プレイ可能カードがなければ `END` を返すよう変更した。

### FTUE停止

問題:

floor 7 の戦闘中に `screen_name=FTUE` が出て、旧コードは `WAIT 60` を返し続けた。

対応:

CommunicationMod READMEの `KEY Keyname [Timeout]` 仕様に従い、`FTUE` では `KEY Confirm 30` を返すよう変更した。

### ショップ再入場/買いすぎ

問題:

旧ログでは `SHOP_ROOM` と `SHOP_SCREEN` で `CHOOSE 0` / `LEAVE` の高速ループが発生していた。また、削除後の少額で弱いカードを買う可能性があった。

対応:

- ショップ訪問済みキーを見て再入場しない
- 所持金75未満ではショップへ入らない
- ショップ購入は評価値60以上に制限
- カード削除対象は Strike / Curse を優先

実機確認:

```text
SHOP_ROOM gold 140 -> CHOOSE 0
SHOP_SCREEN purge -> CHOOSE 0
GRID for_purge -> CHOOSE Strike -> CONFIRM
SHOP_SCREEN gold 65 -> CHOOSE Shrug It Off
SHOP_SCREEN gold 12 -> LEAVE
SHOP_ROOM gold 12 -> PROCEED
```

### マップ/休憩所の改善

対応:

- `MAP` 専用判断を追加
- HPが65%未満なら休憩所を優先
- HPが高く、デッキがある程度強い場合だけエリートを許容
- 休憩所はHP45%未満なら `rest`、それ以外は `smith`

### 戦闘判断の改善

対応:

- 1枚で倒せる敵がいる場合は最優先で撃破
- 被ダメージがブロックを上回る場合は防御カードを優先
- 攻撃カードは推定ダメージ、コスト、過剰ダメージを見て選択
- `Bash` や `Strike` だけでなく、主要Ironcladカードの簡易ダメージ/ブロック表を追加

### 実機検証結果

設定を以下に変更し、Codex待ちなしのルールベースで検証した。

```properties
command=python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start
```

確認できた到達点:

- Mod付きゲーム起動
- 新規ラン開始
- Neow選択
- 戦闘報酬の複数回収
- ショップで削除/購入/退出
- エリート戦突破
- FTUE停止なし
- floor 10 の通常戦闘まで継続

残課題:

- ポーション使用判断はまだ未実装
- イベント固有判断は簡易キーワードベース
- Actボスや高難度戦闘向けの本格的なカード評価は未実装
- 低HP時のルート選択はさらに保守的にしてよい

## 2026-04-26 OpenAI API直接呼び出しへの変更

この節以降が現在の有効構成。これより前の `--auto-start` のみ、または `--use-codex` 前提の記述は当時の検証ログとして残している。

Codex CLI経由は1手あたり18〜25秒程度かかっていた。原因はモデル推論だけではなく、毎手 `codex exec --ephemeral` を新規起動しているエージェント実行のオーバーヘッドが大きいと見られる。

対応:

- `--use-openai-api` を追加
- OpenAI Responses APIへ直接POSTする経路を追加
- Structured OutputsのJSON Schemaで `action_id`, `rationale`, `confidence` を返させる
- `action_id` はコード側で生成した合法手IDのenumに制限
- API失敗時や `OPENAI_API_KEY` 未設定時はルールベースの `fallback_action` を実行
- Codex CLI経路 `--use-codex` は比較用に残す

現在のCommunicationMod設定:

```properties
command=python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start --use-openai-api --openai-model gpt-5.4-mini
```

OpenAI APIに渡す情報も拡張した。以前はHP、手札、敵、合法手程度だったが、現在は以下も含める。

- デッキ全体とカード枚数集計
- 手札、山札、捨て札、廃棄札
- カードの推定ダメージ/ブロック
- 敵のintent、攻撃回数、推定被ダメージ、powers
- プレイヤーpowers
- レリックとカウンター
- ポーション
- 報酬詳細
- GRID/SHOP/REST/MAPの画面状態
- ショップ候補と価格
- マップの現在ノード/次ノード
- ルールベースのfallback手

サンプル戦闘状態ではAPIペイロードは約6.2KBだった。

注意:

現在のシェルでは `OPENAI_API_KEY` が未設定だったため、実API呼び出しは未実行。未設定時はログに以下が出て、ゲームは止まらずルールベースで進む。

```text
OPENAI_API_KEY is not set; using rule command
```

### gpt-5.4-mini 実機確認

ユーザー指定で `gpt-5.4-mini` を使い、環境変数 `OPENAI_API_KEY` を起動プロセスにだけ渡して実ゲームで確認した。APIキーは設定ファイルには保存していない。

CommunicationMod設定:

```properties
command=python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start --use-openai-api --openai-model gpt-5.4-mini
```

確認結果:

- `openai_api elapsed=1.82〜4.16` 秒程度
- Codex CLIの18〜25秒より大幅に速い
- `logs/openai_decisions.jsonl` に判断理由が記録された
- floor 1 戦闘を突破し、カード報酬で `Feel No Pain` を選択
- floor 2イベント、floor 3戦闘まで進行

観察:

現在のプロンプトは survival を強く優先しているため、戦闘中にかなり防御寄りになる。次の改善では「Act 1序盤は敵を早く倒すこともHP保全である」「リーサル/準リーサル/敵の残HP」をより強く評価させる必要がある。

### 現在の有効設定まとめ

2026-04-26 14:04時点の有効設定:

```properties
command=python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start --use-openai-api --openai-model gpt-5.4-mini
runAtGameStart=true
verbose=false
maxInitializationTimeout=10
```

ドキュメント上の古い `--use-codex` 記述は、Codex CLI検証時の履歴として残している。現在の通常起動はOpenAI API直接呼び出し。

## 現在のログ確認方法

AIが返したコマンド:

```bash
tail -n 50 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/logs/actions.jsonl
```

最新のゲーム状態:

```bash
tail -n 1 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/logs/states.jsonl
```

セッションログ:

```bash
tail -n 80 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/logs/session.log
```

起動中プロセス確認:

```bash
ps aux | rg -i 'ModTheSpire|SlayTheSpire|sts_ai_player|CommunicationMod'
```

必要なら停止:

```bash
kill <ModTheSpireのJavaプロセスID>
```

## 次に実装すべきこと

### 1. GRID画面対応

最優先。

`screen_type == "GRID"` のとき、以下を処理する。

- `for_purge: true` の場合、Strikeを優先して削除
- `for_upgrade: true` の場合、Bashを優先してアップグレード
- `for_transform: true` の場合、Strikeを優先
- カードを選択したら `CONFIRM` または `PROCEED`

CommunicationModのREADME上は `CONFIRM` は `PROCEED` 相当。現在は `KEY Confirm` や座標クリックは使わない方針。

### 2. 報酬画面対応

カード報酬:

- 攻撃が少ない序盤は攻撃カード優先
- 防御が弱ければShrug It Offなどを優先
- 微妙ならスキップ

ポーション/ゴールド/レリック:

- `PROCEED` で取れるものは取る
- ポーション満杯時は注意

### 3. マップ選択

最初は単純でよい。

- HPが高ければエリート多め
- 低ければ休憩所優先
- ショップはゴールドがあるとき
- 不明なら左から最初の道

### 4. LLM統合

すぐLLMに全部任せるのではなく、以下の構成がよい。

```text
CommunicationMod JSON
  -> 状態要約
  -> 合法手一覧
  -> LLMに action_id だけ選ばせる
  -> コード側で検証
  -> CommunicationModコマンドへ変換
```

LLMに自由に `PLAY 999` などを書かせない。

### 5. ログの圧縮/分析

`states.jsonl` はすぐ大きくなるため、記事化や検証用には要約ログを追加するとよい。

例:

```json
{
  "floor": 3,
  "screen": "COMBAT",
  "player_hp": 80,
  "energy": 3,
  "hand": ["Strike", "Defend", "Bash"],
  "monsters": [{"name": "Jaw Worm", "hp": 44, "intent": "ATTACK"}],
  "command": "PLAY 3 0"
}
```

## 記事化する場合の流れ

記事にするなら以下の構成がよい。

1. 画面認識ではなく状態JSONを使う理由
2. Slay the Spire + CommunicationModの構成
3. Steam WorkshopでModTheSpire/BaseModを入れる
4. CommunicationMod.jarをローカルmodsへ置く
5. CommunicationModのconfigを書く
6. Pythonプロセスは `ready` を返す必要がある
7. `START IRONCLAD 0` でラン開始
8. JSON状態から `PLAY`, `CHOOSE`, `PROCEED` を返す
9. 実際にNeowから戦闘まで動いた
10. まだ難しい点: チュートリアル、GRID、報酬、マップ、LLM判断

## 最新引き継ぎまとめ

このセッションでは、Mac mini上のSteam版 Slay the Spire に対して、ModTheSpire / BaseMod / CommunicationMod を使うAIプレイ環境を構築した。CommunicationModがゲーム状態JSONを外部Pythonプロセスへ送り、`sts_ai_player.py` が `START`, `PLAY`, `END`, `CHOOSE`, `CONFIRM`, `PROCEED`, `RETURN`, `LEAVE`, `SKIP`, `STATE`, `WAIT` などの意味コマンドを返す。

現在の重要ファイル:

```text
/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/run_modded.sh
/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py
/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/tools/configure_communication_mod.py
/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/logs/states.jsonl
/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/logs/actions.jsonl
/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/logs/openai_decisions.jsonl
/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/logs/codex_decisions.jsonl
```

## 最新の起動方式

通常は以下で起動する。

```bash
cd /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
./run_modded.sh
```

直接 `jre/bin/java -jar ModTheSpire.jar --mods basemod,CommunicationMod --skip-intro` を実行すると、MacのLWJGL/OpenGL初期化で以下のクラッシュが出た。

```text
SIGSEGV
Problematic frame: libobjc.A.dylib objc_release
Java frames: org.lwjgl.opengl.MacOSXContextImplementation.setView
```

そのため最新版の `run_modded.sh` は、Macアプリ本体の `launcher_opts.toml` を一時的にModTheSpire起動へ差し替え、`Contents/MacOS/SlayTheSpire` 経由で起動する。終了時には `launcher_opts.toml` を元に戻す。

起動成功時に確認したこと:

```text
Mod list:
 - basemod (5.56.0)
 - CommunicationMod (1.2.1)

Communication Mod
communicationmod.CommunicationMod
Received message from external process: ready
```

## CommunicationMod設定

設定ファイル:

```text
/Users/user/Library/Preferences/ModTheSpire/CommunicationMod/config.properties
```

現在のコマンド:

```properties
command=python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start --use-openai-api --openai-model gpt-5.4-mini
runAtGameStart=true
verbose=false
maxInitializationTimeout=10
```

設定を作り直す場合:

```bash
cd /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
python3 tools/configure_communication_mod.py
```

## 最新のAI仕様

現在の通常構成ではOpenAI Responses APIを直接呼び出す。Codex CLI経路 `--use-codex` は比較用に残しているが、1手ごとの起動コストが大きいため通常起動では使わない。

- 戦闘、マップ、報酬、イベントなどでコード側が合法手一覧を作る
- OpenAI APIには合法手IDだけを選ばせる
- API失敗時や `OPENAI_API_KEY` 未設定時はルールベース判断へフォールバックする
- `FTUE` はLLMを呼ばずルールベースで `KEY Confirm 30` を返す
- stdoutにはCommunicationModへ返すコマンドだけ出し、ログは `logs/` に書く

LLMへ渡す方針:

```text
CommunicationMod JSON
  -> 状態要約
  -> コード側で合法手一覧を生成
  -> LLMには action_id だけ選ばせる
  -> action_id が合法手に一致した場合だけ実行
  -> 不正/失敗ならルールベースへフォールバック
```

## 最新の画面別処理

現在の主な処理:

- メインメニュー: `--auto-start` 付きなら `START IRONCLAD 0`
- Neow / イベント: 選択肢があれば基本 `CHOOSE <index>`
- 戦闘: プレイ可能カードと対象を合法手化。ルールフォールバックは攻撃、必要ならブロック、最後に `END`
- `CARD_REWARD`: 簡易スコアでカードを選び、弱い候補だけなら `SKIP`
- `COMBAT_REWARD`: レリック、カード、ゴールド、ポーションを優先順で回収し、残りがなければ `PROCEED`
- `GRID`: `CHOOSE <index>` が使える場合のみカード選択。`confirm_up` なら `CONFIRM` / `PROCEED`
- `SHOP_ROOM`: ショップ入室段階なので `CHOOSE 0` または `PROCEED`
- `SHOP_SCREEN`: 削除可能かつGoldが足りるなら `purge` 優先。有用な購入候補がなければ `LEAVE`
- `FTUE`: CommunicationModのゲーム内キーコマンドで `KEY Confirm 30`

自動送信しないもの:

```text
CLICK ...
```

理由は、座標クリックがユーザーのPC操作と干渉するため。`KEY Confirm` はOSキー入力ではなくCommunicationModのゲーム内キーマッピング経由なので使用する。

## 実プレイで確認済み

2026-04-26の実プレイで、以下を確認した。

1. `./run_modded.sh` でMacアプリ本体経由のModTheSpire起動に成功
2. CommunicationModが `sts_ai_player.py --auto-start --use-openai-api --openai-model gpt-5.4-mini` を起動
3. AIが `ready` を返した
4. `START IRONCLAD 0` で新規ラン開始
5. Neowイベントを進行
6. `Enemies in your next three combats have 1 HP` を選択
7. マップ選択を実行
8. Act 1 floor 1戦闘へ到達
9. `PLAY` コマンドで戦闘を進行
10. floor 2戦闘も突破し、ショップ部屋まで到達

ログ例:

```text
command=START IRONCLAD 0
command=CHOOSE 0
command=CHOOSE 0
command=CHOOSE 0
command=CHOOSE 1
command=PLAY 1 0
command=PROCEED
command=CHOOSE 0
command=PLAY 3 0
command=PLAY 3 1
command=PROCEED
```

## 最後に見つけた問題と修正

実プレイ中、Act 1 floor 3のショップ部屋で以下の状態になった。

```json
{
  "screen_type": "SHOP_ROOM",
  "room_type": "ShopRoom",
  "room_phase": "COMPLETE",
  "choice_list": ["shop"],
  "available_commands": ["choose", "proceed", "key", "click", "wait", "state"]
}
```

旧コードでは `SHOP_ROOM` を `SHOP_SCREEN` と同じ扱いにしていたため、候補購入がないと `STATE` ループになった。

この時点の暫定修正:

```text
SHOP_ROOM -> CHOOSE 0 または PROCEED
SHOP_SCREEN -> 購入/削除/LEAVE判断
```

この修正後に `python3 -m py_compile` と `SHOP_ROOM` サンプル確認を通した。

確認結果:

```text
SHOP_ROOM sample: CHOOSE 0
python compile: OK
run_modded.sh syntax: OK
```

ただし、この暫定修正だけでは後述の入退店ループが残った。

## 追加で見つけた問題と修正

その後の実ログで、floor 2のショップで以下の高速ループが発生していた。

```text
SHOP_SCREEN(gold=0, available=leave) -> LEAVE
SHOP_ROOM(choice_list=["shop"], available=choose/proceed) -> CHOOSE 0
SHOP_SCREEN(gold=0, available=leave) -> LEAVE
...
```

原因:

- `SHOP_SCREEN` で買える候補がないため `LEAVE`
- `SHOP_ROOM` に戻ると `choice_list: ["shop"]` を見て再び `CHOOSE 0`
- 結果としてショップ入退店を繰り返した

2026-04-26 追加修正:

- `SHOP_VISITED_KEYS` を追加し、`seed / act / floor` 単位で訪問済みショップを記録
- `SHOP_SCREEN` に入った時点でそのショップを訪問済みにする
- `SHOP_ROOM` では以下の場合 `PROCEED` する
  - 同じ floor のショップにすでに入った後
  - 所持金が `0`
  - 選択肢がない
- 未訪問かつ所持金がある `SHOP_ROOM` だけ `CHOOSE 0` で入店する

確認結果:

```text
python3 -m py_compile sts_ai_player.py: OK
python3 sts_ai_player.py --test: PLAY 2 0
first_shop_room: CHOOSE 0
shop_screen_no_buy: LEAVE
after_leave_shop_room: PROCEED
zero_gold_shop_room: PROCEED
```

## 追加修正後の実プレイ確認

2026-04-26 13:12頃に `./run_modded.sh` で実際にMod付きゲームを起動し、当時の `--auto-start --use-codex` 設定で新規ランを進めた。その後、通常構成はOpenAI API直接呼び出しへ変更した。

確認できた流れ:

```text
START IRONCLAD 0
Neow: talk -> enemies in your next three combats have 1 hp -> leave
MAP選択
floor 1 Jaw Worm: PLAY -> COMBAT_REWARD -> PROCEED
floor 2 Slimes: PLAY -> PLAY -> COMBAT_REWARD -> PROCEED
floor 3 EventRoom: event choice -> GRID -> CHOOSE 9 -> CONFIRM -> leave
floor 4 Cultist: PLAY -> COMBAT_REWARD -> PROCEED
floor 5 EventRoom: event choice -> leave
floor 6 RestRoom: smith -> GRID -> CHOOSE 0 -> CONFIRM -> PROCEED
```

実プレイで確認できたこと:

- CommunicationModがAIプロセスを起動し、`ready` と `START IRONCLAD 0` が正常に通った
- Neowイベント、マップ選択、戦闘、戦闘報酬、通常イベント、GRID、焚き火のsmith画面が停止せず進行した
- `GRID` 画面ではイベントのカード選択とsmith対象選択の両方で `CHOOSE` -> `CONFIRM` が通った
- floor 6のマップ画面まで高速ループや停止は見つからなかった
- 今回の実ランではショップ部屋を踏まなかったため、ショップ入退店ループ修正は上記のログ再現テストで確認した

実プレイ後、ゲームプロセス、`sts_ai_player.py`、`codex exec` は停止済み。`launcher_opts.toml.codex-backup` も残っていないことを確認した。

## 現在の注意点

- 実行中の `sts_ai_player.py` はコード変更を反映しない。修正後はSlay the Spire / ModTheSpire / AIプロセスを終了して再起動する
- `codex exec` は1手あたり約18-30秒かかる
- FTUEは現在 `KEY Confirm 30` で自動確定する。古い実機環境で止まる場合だけ手動で閉じる
- 直接Java起動はMacでクラッシュする可能性があるため、`./run_modded.sh` を使う

## 残課題

2026-04-26の実プレイ確認後に残っている課題。

1. `--use-codex` が遅い
   - 1手ごとに `codex exec` を起動しており、実測でおおむね17-21秒かかっていた
   - マップ選択、報酬、単純戦闘まで毎回Codexに渡すとプレイ速度がかなり遅い
   - 次は単純な場面をルールベースで処理し、Codex呼び出しを難しい判断だけに絞る

2. ショップ修正は実ランで未到達
   - ログ再現テストでは `SHOP_ROOM` で `PROCEED` になることを確認済み
   - 今回の実プレイ経路ではショップ部屋を踏まなかったため、実ゲーム上の確認はまだ残っている

3. 判断品質がまだ粗い
   - イベント、カード報酬、焚き火、ショップ購入の選択は最低限進行できる程度
   - 長期的に強い選択にはなっていない可能性が高い
   - 実ログを見ながらヒューリスティックを調整する必要がある

4. 失敗検知がない
   - 同じ画面で同じコマンドを繰り返す、一定時間floorが進まない、同一screen_typeが続くなどを自動検知できない
   - `states.jsonl` / `actions.jsonl` から停止・ループを検出する簡易チェッカーを作ると次のデバッグが楽になる

## 次にやるとよいこと

優先度順:

1. マップ選択をルールベース化してCodex呼び出しを減らす
2. 戦闘のルールフォールバックを強化する
3. ショップ購入スコアを調整する
4. カード報酬スコアを実プレイログから調整する
5. `states.jsonl` / `actions.jsonl` から要約ログを作る
6. Codex CLIの起動コストを下げる方法を検討する

## 2026-04-26 追加修正: Act 1突破確認

ユーザー依頼で、上記残課題のうち戦闘判断、カード報酬、ポーション使用、LLM向け合法手説明を追加修正した。

変更ファイル:

```text
/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py
```

主な修正:

- Act 1戦闘で `Defend` 偏重になりすぎないよう、リーサル、敵撃破、低被ダメージ時の攻撃継続を優先
- OpenAI APIに渡すpolicy文言を修正し、「HP保全 = 常にブロック」ではなく「早く倒すこともHP保全」と明示
- 合法手に `POTION Use <slot> [target]` を追加
- Fire / Explosive / Block / Weak / Skill / Attack / Power 系ポーションの簡易使用判断を追加
- カード報酬スコアを調整し、Act 1序盤では即戦力攻撃を高評価
- `Feel No Pain`、`Body Slam`、`Corruption` などのシナジー依存カードは、現デッキに支えがない場合は評価を下げる
- `Clash`、`Sword Boomerang`、`Searing Blow` などもデッキ状況に応じて減点
- MAP合法手の説明にノード記号、座標、ルートスコアを含めるよう改善

確認コマンド:

```bash
python3 -m py_compile sts_ai_player.py
python3 sts_ai_player.py --test
```

結果:

```text
py_compile: OK
--test: PLAY 1
```

### 実ゲーム検証

`./run_modded.sh` で実際にMod付きゲームを起動し、新規ランを進めた。

このシェルでは `OPENAI_API_KEY` / `STS_AI_OPENAI_API_KEY` が未設定だったため、OpenAI API経路ではなくルールベースfallbackのみで検証した。

確認できた流れ:

```text
START IRONCLAD 0
Neow選択
Act 1序盤戦闘
Act 1エリート Gremlin Nob 突破
RestRoomで Bash+ にsmith
TreasureRoomでRelic取得
Act 1エリート Sentries 突破
The Guardian 撃破
Act 2 floor 18 まで到達
```

停止時点:

```text
floor: 18
act: 2
room: MonsterRoom
screen: NONE
phase: COMBAT
HP: 73 / 80
gold: 384
act boss: Champ
enemy: Spheric Guardian, 20 HP
```

確認できた良い点:

- ルールベースだけでAct 1を突破できた
- `Bash+`、`Inflame`、`Shockwave`、複数 `Twin Strike` / `Pommel Strike` を含む攻撃寄りデッキになった
- Sentries戦で `Explosive Potion` を使用し、エリート戦を突破した
- `GRID`、焚き火、宝箱、戦闘報酬、カード報酬、マップ選択は停止せず進行した
- 実プレイ後、ゲームプロセスとAIプロセスを停止し、`launcher_opts.toml.codex-backup` が残っていないことを確認した

### 追加で見つかった残課題

1. OpenAI API込みの再検証
   - 今回はAPIキー未設定だったため、OpenAI判断は未検証
   - `OPENAI_API_KEY` を起動プロセスに渡した状態で、今回のpolicy変更後の判断品質を確認する必要がある

2. ボス戦でのポーション使用が遅い
   - The Guardian戦ではHP 13まで落ちた
   - その後勝てたが、`Skill Potion` をより早めに使う判断が必要
   - この観察後に、Skill / Attack / Power Potionを危険部屋や大ダメージ時に使うルールを追加した
   - 追加後の実ゲーム再検証はまだ

3. Act 2以降の戦闘評価が粗い
   - Spheric Guardianなど、Act 2敵の特殊行動やブロック/アーティファクトをまだ深く見ていない
   - SentriesやGuardianは突破できたが、Act 2エリートやボス向けには不足

4. Smoke Bombの扱い
   - Act 2到達時に `Smoke Bomb` を持っていた
   - 現状は使用判断なし
   - 死にそうな通常戦闘では逃走候補にしてよいが、エリート/ボスでは使えない・使うべきでない場面があるため注意

5. 報酬取り順とカード報酬のログ分析
   - 戦闘報酬ではカード、ゴールド、ポーションを回収できているが、ログ上は高速に複数 `CHOOSE` が並ぶ
   - 今後は状態と行動を同一タイムラインで要約するログを作ると、悪手分析がかなり楽になる

6. 実行中プロセスへのコード反映
   - 実行中の `sts_ai_player.py` にはコード修正が反映されない
   - ポーション判断などを変更した後は、必ずSlay the Spire / ModTheSpire / AIプロセスを再起動する

### 次にやるとよいこと更新

優先度順:

1. `OPENAI_API_KEY` を渡してOpenAI API込みでAct 1〜Act 2を再検証
2. Skill Potion / Smoke Bomb / Fairy in a Bottle周りの判断を実ログで確認
3. Act 2通常敵、エリート、ボス用の敵別ヒューリスティックを追加
4. `states.jsonl` と `actions.jsonl` を時系列で結合する要約ログ/ループ検知ツールを作る
5. ショップ購入、カード削除、イベント選択のログを実ランで確認して調整

## 2026-04-26 追加修正: API失敗耐性とマップ先読み

ユーザー指定の `OPENAI_API_KEY` と `gpt-5.4-mini` で実ゲーム起動を行った。

今回の実行ログ:

```text
logs/run-20260426-143822
logs/run-20260426-144140
```

確認結果:

- `gpt-5.4-mini` の直接API呼び出しは、最初のスモークテストでは応答した
- その後の実ゲーム起動では OpenAI API が `401 Unauthorized` を返した
- 連続で401を叩き続けないよう、401/403を受けたプロセスではOpenAI APIを無効化し、以降はルールベースfallbackへ即時切替するよう修正した
- 401発生後もゲームは停止せず、fallbackのみでランを継続できた

追加したファイル:

```text
tools/summarize_run.py
```

用途:

```bash
python3 tools/summarize_run.py --log-dir logs/run-YYYYMMDD-HHMMSS --last 80
```

`states.jsonl` と `actions.jsonl` を同じ件数だけ末尾から読み、floor / screen / room / HP / hand / monsters / choices / command を短く表示する。巨大な `states.jsonl` を全読みしないよう、ファイル末尾から必要行だけ読む実装にした。一定回数以上同じ signature が出ると `Potential loops` として表示する。

今回見つけた問題:

1. LLM判断の安全弁
   - APIスモークテストで、Jaw Worm 12点被弾に対して `Defend` ではなく `Strike` を選ぶケースがあった
   - 高被弾局面でfallbackが防御/ポーションを選んでいる場合、LLMが非リーサル攻撃を選んでもfallbackへ戻す安全弁を追加した

2. 低HPでの将来エリート
   - HP 46/80から、数部屋先で強制Lagavulinになるルートへ入り死亡した
   - `MAP` の評価にフルマップの `children` を使った先読みを追加し、近い将来のエリートを低評価、休憩所を高評価するようにした
   - 直近の再現ログでは、floor 3 の分岐が `M` 優先から `?` 優先へ変わることを確認した

3. イベント選択
   - カード記憶系イベントで `Pain` を選びやすい状態があった
   - `pain` / `curse` を低評価、匿名 `cardN` を控えめ評価にした

4. ポーション
   - Smoke Bombは通常戦闘で死亡級の被弾が見える場合だけ使用候補にした
   - エリート/ボスでは使わない

確認コマンド:

```bash
python3 -m py_compile sts_ai_player.py tools/summarize_run.py
python3 sts_ai_player.py --test
```

結果:

```text
--test: PLAY 1
py_compile: OK
```

注意:

- 2026-04-26 14:41時点では、指定APIキーがOpenAI APIから `401 Unauthorized` を返す
- APIキーが復旧/差し替えされるまでは、`--use-openai-api --openai-model gpt-5.4-mini` を指定していても初回401後はfallbackのみで進行する

### 追加で残っている課題

次回以降に優先して対応する。

1. エリート別の戦闘ヒューリスティック
   - Lagavulin / Gremlin Nob / Sentries の専用判断がまだ弱い
   - Lagavulinでは、起床前の準備、起床後のブロック/攻撃配分、デバフターンの扱いを分ける必要がある
   - Gremlin Nobでは、不要なSkill連打を避け、短期火力とポーション使用を優先する必要がある
   - Sentriesでは、中央/端の倒す順番、Dazed増加前の火力集中、AoE/ポーション評価を強める必要がある

2. カード報酬とショップ購入の長期評価
   - 現在のカード報酬はAct 1序盤の前のめりな攻撃評価が中心
   - デッキの防御、ドロー、スケーリング、エナジー、状態異常対策を見た評価はまだ浅い
   - ショップはカード削除と一部高評価カード/レリック購入に対応しているが、所持金、今後のショップ、ポーション枠、ボス対策を含む長期判断は未実装

3. 死亡後の自動再スタート制御
   - 現状は `--auto-start` のため、死亡後に自動で次ランへ入ることがある
   - 長時間連続検証には便利だが、1ラン単位の失敗分析では死亡時点で停止した方が扱いやすい
   - `--stop-on-game-over` のようなオプションを追加し、GAME_OVER時は `WAIT` / `STATE` / プロセス終了などを選べるようにするとよい

## 2026-04-26 追加修正: ポーション報酬停止とLLM安全弁

ユーザー指定の `OPENAI_API_KEY` と `gpt-5.4-mini` でAPI疎通を確認後、実ゲームを起動して検証した。

今回の実行ログ:

```text
logs/run-20260426-145905
logs/run-20260426-150532
```

API確認:

- 事前スモークテストで `gpt-5.4-mini` へのResponses API呼び出しは `200 OK`
- 実ゲーム中もOpenAI API判断が記録された
- 今回の検証中、401/403などのAPIエラーは発生しなかった

追加修正:

- `COMBAT_REWARD` のポーション報酬で、ポーション枠満杯時の処理を追加
  - `Fruit Juice` など報酬画面で使える非ターゲットポーションは `POTION Use <slot>` で先に使用
  - 使えるポーションがなければ、報酬ポーションの価値が手持ち最低価値より高い場合だけ `POTION Discard <slot>`
  - 捨てる価値がないポーション報酬だけが残った場合は `PROCEED`
- CommunicationMod仕様に合わせて `POTION Use|Discard PotionSlot [TargetIndex]` を使うようにした
- OpenAI判断の画面安全弁を強化
  - `CARD_REWARD` のモデル選択がルール評価より明確に低い場合はfallbackへ戻す
  - 無被弾ターンにモデルが純ブロックカードを選んだ場合は `END` へ戻す
  - `Disarm` / `Shockwave` / `Intimidate` は高被弾時の防御的プレイとして扱い、Defend安全弁で誤って潰さないようにした
- 実戦で見えた敵別/場面別の補強
  - Gremlin Nobでは不要なSkill防御を抑制
  - Lagavulinの睡眠/デバフターンを判定
  - setupカードとして `Inflame` / `Metallicize` / `Shockwave` / `Offering` などを評価
  - マップ先読みの子ノード処理を壊れにくくした

実ゲームで見つけた停止:

```text
floor: 4
screen_type: COMBAT_REWARD
reward: Heart of Iron potion
potions: Fear Potion, Fire Potion, Fruit Juice
available_commands: choose, potion, proceed, key, click, wait, state
```

旧挙動:

```text
CHOOSE 0
```

ポーション枠が満杯のため進まず、ゲーム側が待機した。

修正後の同状態でのルール判断:

```text
POTION Use 2
```

`Fruit Juice` を使って枠を空けるため、次状態で報酬ポーションを取得できる。

2回目の実ゲーム検証では以下を確認した。

```text
START IRONCLAD 0
Neow's Lament選択
floor 1-4突破
GRIDイベントでカード選択/CONFIRM
COMBAT_REWARD / CARD_REWARD / MAP進行
floor 5 Large Slime戦突破
floor 6 RestRoom手前まで到達
```

観察:

- OpenAIはNeowで `max hp +8` を選ぼうとしたが、画面スコア安全弁により `enemies in your next three combats have 1 hp` へ上書きされた
- Large Slime戦ではHP 80 -> 54まで減った。停止はしていないが、Act 1後半の大型敵に対してはまだ被弾が大きい
- 高被弾時のモデル攻撃選択は複数回fallbackへ戻せた
- 無被弾ターンに `Defend` を選ぶ無駄打ちがあったため、純ブロック安全弁を追加した

確認コマンド:

```bash
python3 -m py_compile sts_ai_player.py tools/summarize_run.py
python3 sts_ai_player.py --test
```

結果:

```text
py_compile: OK
--test: PLAY 1
```

残課題:

1. Act 1後半の大型通常敵とエリートでの被弾削減
   - Large Slime戦で被弾が大きい
   - `Disarm` や弱体化系カード/ポーションをより早く使う判断を実ログで調整する
2. `CARD_REWARD` の長期評価
   - `True Grit`、`Sever Soul`、`Disarm` などは取れているが、防御/ドロー/火力のバランスはまだ粗い
3. 1ラン単位の検証制御
   - `--stop-on-game-over` や `--max-floor` があると、実験ログの切り分けがしやすい

## 2026-04-26 追加修正: 実走デバッグによる安全弁強化

ユーザー指定どおり、`gpt-5.4-mini` のOpenAI API経路で疎通確認後、実ゲームを起動して検証した。APIキーは環境変数として起動プロセスに渡し、設定ファイルやノートには保存していない。

今回の実行ログ:

```text
logs/run-20260426-152248
logs/run-20260426-152714
```

API確認:

- 事前スモークテストで `gpt-5.4-mini` は正常応答
- 実ゲーム中も `openai_api elapsed=... model=gpt-5.4-mini` が継続記録された
- 401/403などのAPIエラーは発生しなかった

追加修正:

- `Disarm` のような対象指定デバフをfallbackルールでも使えるようにした
- Sentries戦では外側Sentryを少し優先するターゲット補正を追加
- GRID / REST 画面にもOpenAI判断の画面スコア安全弁を追加
  - Bashアップグレードより大きく劣るGRID選択をfallbackへ戻す
  - 低HP時にsmithを選ぶ判断をrestへ戻す
- 無被弾ターンに純ブロックカードを選ぶOpenAI判断をfallbackへ戻す
- 危険戦闘でHPに余裕があり、高打点攻撃を選んだ場合は安全弁で過剰に潰さないよう調整
- 同一戦闘ターンで `POTION Use` を連打しないよう、使用済みターンを記録する安全弁を追加
- `Duplication Potion` は危険戦闘や大ダメージ局面だけ使う候補にした
- 休憩所判断を保守化し、HP55%以下では `rest` を優先するよう修正

実ゲームで確認できたこと:

```text
run-20260426-152248:
  floor 7 Lagavulinまで到達
  API判断・安全弁・ポーション使用を確認
  同一ターンに複数ポーションを使う余地が見えたため停止して修正

run-20260426-152714:
  Neow's Lament選択
  GRIDイベント進行
  floor 5 Large Slime突破
  floor 6 Sentries突破
  floor 8 RestRoomまで到達
```

実走で見つけた問題と対応:

1. 同一ターンのポーション連打
   - Lagavulin戦でモデルがポーションを連続使用する余地があった
   - `POTION_USED_TURNS` を追加し、同一 `seed / act / floor / combat turn` で2本目を原則fallbackへ戻す

2. 低HP休憩所でsmithを選ぶ
   - Sentries突破後、HP40/80のRestRoomで旧ルールはsmithを選んだ
   - HP55%以下ではrestを強く優先するように変更
   - 同じログ状態で `CHOOSE 0`、OpenAIのsmith選択は `low_heuristic_screen_score` で上書きされることを確認

3. 安全弁の過剰防御
   - Lagavulin戦でモデルのBash+などの高打点攻撃を防御fallbackへ戻しすぎていた
   - エリート/ボスでHPに余裕があり、攻撃推定ダメージが十分ある場合はモデル攻撃を許容するよう調整

確認コマンド:

```bash
python3 -m py_compile sts_ai_player.py tools/summarize_run.py
python3 sts_ai_player.py --test
```

結果:

```text
py_compile: OK
--test: PLAY 1
```

残課題:

1. Sentries戦でHP73 -> 40まで削られたため、Sentries専用のターゲット順と防御/攻撃配分はまだ改善余地が大きい
2. Large SlimeなどのAct 1大型通常敵で、分裂前後のHP調整がまだ粗い
3. 休憩所の `rest` 修正は過去ログ状態で確認済みだが、修正後コードでの実ゲーム再走は未実施
4. `tools/summarize_run.py` は状態/行動の表示が一部ずれて見えることがあるため、時刻付き状態ログにするか、index検証を強化するとよい
