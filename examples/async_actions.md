# 非同期 Action の動作確認

A は最初の B を待つ。B は独立した Action で、A の待機を解除できる。A のキューは実行中を含めて2件まで。

入力ごとに通し番号が付く。`#1 A accepted` は1件目の A が受け付けられた時点、`#1 A done` はその A が完了した時点に出る。`rejected` の入力はその場で拒否される。

## N4 Pro

1. [セットアップ](../README.md#セットアップ)に従ってデバイス用の依存を入れ、リポジトリのルートで実行する。

   ```sh
   mise exec -- uv run python examples/async_actions.py --live
   ```

2. `Live: N4 Pro.` と表示されたら、A (ボタン 1) を1回ずつ押して離す。1・2回目は `accepted`、3・4回目は `rejected` が1行ずつ出る。
3. B (ボタン 2) を1回押して離す。B が完了すると、先に受け付けた A が `#1`、`#2` の順に完了する。

```text
Live: N4 Pro. Press and release A or B. Ctrl+C to exit.
#1 A accepted
#2 A accepted
#3 A rejected (action queue full)
#4 A rejected (action queue full)
#5 B accepted
#5 B done
#1 A done
#2 A done
```

この後に A を1回押して離すと、`#6 A accepted` と `#6 A done` が出る。最初の B で待機が解除され、その後の A は次の B を待たずに完了する。未完了の上限は引き続き2件。待機から試し直すには Ctrl+C で終了し、起動し直す。

ボタンを押して離した時点で入力番号が増えなければ、その入力はホストまで届いていない。ボタン名と操作順をログと一緒に記録する。

## リプレイ

リポジトリのルートで実行する。機器を接続せずに A、A、B の入力を1回処理して終了する。

```sh
mise exec -- uv run python examples/async_actions.py
```

```text
Replay: running A, A, B once.
#1 A accepted
#2 A accepted
#3 B accepted
#3 B done
#1 A done
#2 A done
```
