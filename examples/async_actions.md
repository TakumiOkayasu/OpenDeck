# 非同期 Action の動作確認

A (ボタン 1) は実行を始めてから4秒後に完了する。待機中も B (ボタン 2) はすぐに完了する。A は実行中の1件を含めて2件まで受け付け、1件完了するたびに次の入力を1件受け付けられる。

入力ごとに通し番号が付く。`#1 A accepted` は1件目の A の受付、`#1 A done` は同じ A の完了を示す。`rejected` は受付拒否を示す。

## N4 Pro

1. [セットアップ](../README.md#セットアップ)に従ってデバイス用の依存を入れ、リポジトリのルートで実行する。

   ```sh
   mise exec -- uv run python examples/async_actions.py --live
   ```

2. 起動中は `Preparing N4 Pro. Wait for INPUT OK.` が出る。ボタンのラベルが出ても、入力の監視を開始したことを示す `INPUT OK` まで待つ。表示されたら A を1回押して離す。すぐに `#1 A accepted`、B を押さずに待つと約4秒で `#1 A done` が出る。
3. キュー満杯も確認するには Ctrl+C で終了し、起動し直す。`INPUT OK` が出てから A を押し始める。最初の A から4秒以内に A を4回、B を1回、順に押して離す。

手順3の出力は次の順になる。B の完了後、先に受け付けた A が1件ずつ完了する。

```text
#1 A accepted
#2 A accepted
#3 A rejected (action queue full)
#4 A rejected (action queue full)
#5 B accepted
#5 B done
#1 A done
#2 A done
```

`#1 A done` の後に A をもう1回押して離すと、`#6 A accepted` が出る。#2 の実行が終わると #6 が始まり、約4秒後に `#6 A done` が出る。

`Live: N4 Pro.` と出る場合は旧版が実行されている。PR #55 の最新コミットをチェックアウトして再実行する。

## リプレイ

リポジトリのルートで実行する。機器を接続せずに手順3と同じ入力を1回処理し、最後の A が完了したら終了する。

```sh
mise exec -- uv run python examples/async_actions.py
```
