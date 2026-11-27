# 非同期 Action の動作確認

A (ボタン 1) は実行を始めてから4秒後に完了する。待機中も B (ボタン 2) はすぐに完了する。A は実行中の1件を含めて2件まで受け付け、1件完了するたびに次の入力を1件受け付けられる。

入力ごとに通し番号が付く。`#1 A accepted` は1件目の A の受付、`#1 A done` は同じ A の完了を示す。`rejected` は受付拒否を示す。

## N4 Pro

[セットアップ](../README.md#セットアップ)に従ってデバイス用の依存を入れ、リポジトリのルートで実行する。
検証する場合は起動前に `git rev-parse HEAD` も記録する。

```sh
mise exec -- uv run python examples/async_actions.py --live --debug
```

起動中は `Preparing N4 Pro. Wait for INPUT OK.` が出る。
SDK の接続準備中に、割り当て先の `View` を通して A と B のラベルを描画する。
ラベル描画を終え、SDK reader の稼働を確認してからボタン入力の受理を開始する。
ホストが入力通知を購読し、入力キューに対する最初の `take()` が成功した時点で `INPUT OK` が出る。
キューが空でも合図は出るため、実機の押下が届いたことを示すものではない。
ラベル描画中に SDK に届いたボタン入力は受け付けない。合図までボタンから手を離しておく。

`accepted` は、押下と解放がそろい、ホストが Action を受け付けた時点で出る。実機の入力が届いたかは、合図の後に押して離し、受付までのログを照合して確認する。

1. **A の単独完了**。`INPUT OK` の直後に A を1回押して離す。すぐに `#1 A accepted` が出る。
   B に触れずに待つと約4秒で `#1 A done` が出る。
2. **B の完了**。Ctrl+C で終了し、同じコマンドで再起動する。
   `INPUT OK` の後に A を1回押して離し、`#1 A accepted` を確認したらすぐに B を押して離す。
   `#2 B accepted` と `#2 B done` が `#1 A done` より先に出る。
3. **満杯と回復**。Ctrl+C で終了し、`--live --debug --a-delay 15` で再起動する。
   この確認では A を押す時間を取るため、A の実行時間を15秒にする。`INPUT OK` の後に A を3回押して離す。
   `#1 A accepted`、`#2 A accepted`、`#3 A rejected (action queue full)` が出る。
   `#1 A done` が出たら、`#2 A done` が出る前に A をもう1回押して離す。
   `#4 A accepted` が `#2 A done` より先に出て、その後に `#4 A done` が出る。

`--debug` を付けると、SDK の `SDK raw input` と `SDK decoded input`、変換・認識、ホストの受付・完了が時刻付きで出る。入力が抜けた場合は、実際の押下・解放とこれらの行を照合する。起動時の表示が説明と異なる場合は、この説明書と同じリビジョンのサンプルを実行しているか確認する。

## リプレイ

リポジトリのルートで実行する。
機器を接続せずに A、A、A、A、B を処理し、受け付けた Action がすべて完了したら終了する。
3回目と4回目の A が拒否され、B、1回目の A、2回目の A の順に完了する。

```sh
mise exec -- uv run python examples/async_actions.py
```
