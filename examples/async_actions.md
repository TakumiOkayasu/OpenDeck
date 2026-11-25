# 非同期 Action の動作確認

A は最初の B を待つ。B は独立した Action で、A の待機を解除できる。A のキューは実行中を含めて2件まで。枠は Action の完了時に空く。

`A received` はボタンを押して離した入力がサンプルに届いたことを示す。表示直後にホストが実行またはキューへの追加を判断する。`A done` は Action の完了、`A failed (action queue full)` は満杯による受付拒否を示す。拒否された入力はその場で破棄される。

## N4 Pro

1. [セットアップ](../README.md#セットアップ)に従ってデバイス用の依存を入れ、リポジトリのルートで実行する。

   ```sh
   mise exec -- uv run python examples/async_actions.py --live
   ```

2. `Live: N4 Pro.` と表示されたら、A (ボタン 1) を1回ずつ押して離す。`A received` が1回ずつ出ることを確かめながら4回繰り返す。最初の2回は未完了のまま待機する。3・4回目は満杯で拒否される。
3. B (ボタン 2) を1回押して離し、手を止める。B が完了し、受け付けた A 2件が順に完了する。

起動メッセージに続く出力は次の順になる。

```text
A received
A received
A received
A failed (action queue full)
A received
A failed (action queue full)
B received
B done
A done
A done
```

この後に A を1回押して離すと、`A received` と `A done` が1行ずつ増える。最初の B で待機が解除され、その後の A は次の B を待たずに完了する。未完了の上限は引き続き2件。待機から試し直すには Ctrl+C で終了し、起動し直す。

`Live: N4 Pro.` が出てからボタンを押して離しても `A received` が出ない場合は、どのボタンを何回押したかをログと一緒に記録する。

## リプレイ

リポジトリのルートで実行する。接続なしで A、A、B の入力を1回処理して終了する。

```sh
mise exec -- uv run python examples/async_actions.py
```

```text
Replay: running A, A, B once.
A received
A received
B received
B done
A done
A done
```
