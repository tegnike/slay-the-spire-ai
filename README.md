# Slay the Spire AI Player

CommunicationMod から Slay the Spire のJSON状態を受け取り、コマンドを返す最小AIプレイヤーです。

現時点の目的は「ゲームと外部AIプロセスを接続し、LLMまたはルールベースで合法手から行動を選ばせる」ことです。ゲームへ送るコマンドは必ずコード側で生成した合法手に限定し、LLMが不正な手を返した場合はルールベース判断へフォールバックします。OpenAI API自体の失敗時は、エラーを見落とさないよう停止します。

## 構成

- `sts_ai_player.py`: CommunicationMod 用のAIプロセス
- `run_modded.sh`: Macアプリ本体経由でModTheSpireを起動するランチャー
- `tools/configure_communication_mod.py`: Mac用のCommunicationMod設定ファイル作成補助
- `tools/summarize_run.py`: `states.jsonl` / `actions.jsonl` の簡易要約とループ検知
- `docs/setup.md`: Mod導入と起動手順
- `logs/`: 実行時ログの出力先

## 使い方

まず疎通テストだけ行います。

```bash
cd /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai
python3 sts_ai_player.py --test
```

CommunicationMod 側に設定するコマンドは次の形です。

```bash
python3 /Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/sts_ai_player.py --auto-start --use-openai-api --openai-model gpt-5.4-mini
```

設定ファイルを作る場合は:

```bash
python3 tools/configure_communication_mod.py
```

Mod付きで起動する場合は:

```bash
OPENAI_API_KEY="..." ./run_modded.sh
```

APIキーを渡さない場合も停止はせず、ルールベース判断だけで進みます。
ランごとにログを分けたい場合は `STS_AI_LOG_DIR` を指定します。

```bash
RUN_ID="run-$(date +%Y%m%d-%H%M%S)"
export STS_AI_LOG_DIR="$PWD/logs/$RUN_ID"
mkdir -p "$STS_AI_LOG_DIR"
OPENAI_API_KEY="..." ./run_modded.sh
```

Macでは `jre/bin/java -jar ModTheSpire.jar` の直接起動でLWJGL/OpenGLのクラッシュが出ることがあるため、このスクリプトは `launcher_opts.toml` を一時的に差し替えて `SlayTheSpire.app` 本体から起動します。

詳細は [docs/setup.md](/Users/user/WorkSpace/local-tasks-repository/slay-the-spire-ai/docs/setup.md) を見てください。

## 現在のAI

通常はOpenAI Responses APIで判断します。現在の起動設定は `gpt-5.4-mini` です。`OPENAI_API_KEY` が未設定、またはAPI呼び出しに失敗した場合は停止してエラーを出します。`--use-codex` を付けた場合は、比較用にCodex CLI経由でも同じ合法手選択を試せます。

OpenAI APIへ渡す状態には、HP/ゴールド/レリック/ポーションだけでなく、デッキ、手札、山札、捨て札、廃棄札、敵intent、powers、報酬、ショップ候補、マップ候補などの要約を含めます。

- メインメニューでは `--auto-start` を付けた場合だけ Ironclad / Ascension 0 を開始
- 戦闘では、プレイ可能なカード、対象、ターン終了を合法手にする
- `GRID` 画面では、カード選択と確定を合法手にする
- 戦闘報酬はカード/レリック/ゴールド/ポーションを優先順で回収する
- カード報酬は簡易スコアで選び、通常報酬では進行安定のため最善候補を取得する
- ショップはカード削除や有用な購入候補を選び、候補がなければ `LEAVE` する
- マップは通常戦闘とイベントを優先し、低HP時は休憩所、高HPかつ強化済みならエリートも許容する
- 休憩所は低HPや直近の強制Elite/Bossを考慮し、危険なら休憩、それ以外は smith を選ぶ
- 報酬やイベントは原則 `PROCEED` / `RETURN` / 先頭選択で進める
- すべての入力JSONと返したコマンドを `logs/` に保存
- OpenAI APIの判断は `logs/openai_decisions.jsonl` に保存
- Codex CLIの判断は `logs/codex_decisions.jsonl` に保存

OpenAI API判断には安全弁を入れています。高被弾時に防御/ポーションfallbackを無視した場合、無被弾ターンに純ブロックを選んだ場合、GRID/REST/イベントなどでルール評価より大きく劣る選択をした場合は、ルールベースのfallbackへ戻します。同一戦闘ターンのポーション連打も抑制します。

設定スクリプトが書き込むOpenAI APIモデルは `gpt-5.4-mini` です。変える場合は `--openai-model` または `STS_AI_OPENAI_MODEL` を使います。

デフォルトのCodexモデルは `gpt-5.3-codex` です。変える場合は `--codex-model` または `STS_AI_CODEX_MODEL` を使います。Codex実行ファイルは通常 `/Applications/Codex.app/Contents/Resources/codex` を自動検出します。

## ログ確認

セッションログ:

```bash
tail -f logs/session.log
```

ラン別ログを要約する場合:

```bash
python3 tools/summarize_run.py --log-dir logs/run-YYYYMMDD-HHMMSS --last 120
```

現時点では、OpenAI API込みでNeow選択、戦闘報酬、カード報酬、GRID、休憩所、マップ、Act 1エリート突破まで実走確認済みです。勝率を狙う段階ではなく、Act 1大型敵やAct 2以降の敵別判断にはまだ改善余地があります。
