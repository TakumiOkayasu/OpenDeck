# 既定出力の音量操作を入力へ割り当てる

[output_volume.py](output_volume.py) は, `OutputVolume` を受け取る音量設定・ミュート設定の
Action を, 既存の設定読込み・Binding・入力配送に接続する例.
OS の既定出力機器の全体音量を対象にする. DAW で利用する場合は,
DAW の出力先も同じ既定出力機器に設定する.
DAW が別の出力機器や専用ドライバーを選んでいる場合は, その DAW の音量を変更できない.

Action は入力機器や SDK を参照せず, 注入された出力能力へ設定を要求する.
DAW 別・トラック・バス別の操作を加える場合も, 対応する能力を受け取る独自 Action と
builder を組み立て側で登録する. 基盤の入力配送や既定出力の契約へ個別操作を追加しない.

## 実機なしで実行する

[README のセットアップ](../README.md#セットアップ)を済ませ, リポジトリのルートで実行する.

```sh
mise exec -- uv run python examples/output_volume.py
```

既定の実行は再生入力とメモリ上の出力を使用する.
OS の音量・ミュートを変更せず, SDK や OS の音量アダプターを読み込まない.
1 から 4 の押下・解放を順番に再生し, 各操作と結果を表示する.

```text
SIMULATION: output changes are recorded locally.
volume=0.25
quiet: done
volume=0.50
loud: done
muted=True
mute: done
muted=False
unmute: done
```

## N4 Pro で実際の既定出力を操作する

Windows または macOS の端末で N4 Pro を接続し,
N4 Pro を利用するほかのアプリを閉じて実行する.
このモードは実際の出力音量とミュートを変更する.
終了後も設定した状態が残るため, 再生中の音と現在の音量を確認してから操作する.

```sh
mise exec -- uv run --extra device python examples/output_volume.py --live
```

`INPUT OK` の表示後, 次のボタンを単独で押して解放する.

| 入力レポートのボタン番号 | 設定の入力名 | 操作 |
| --- | --- | --- |
| 1 | `quiet` | 既定出力の音量を 25% に設定 |
| 2 | `loud` | 既定出力の音量を 50% に設定 |
| 3 | `mute` | 既定出力をミュート |
| 4 | `unmute` | 既定出力のミュートを解除 |

百分率は OS の出力レベルの相対位置を表す. 各 OS の音量曲線と機器により実際の音は変わる.
設定は[output-volume.json](output-volume.json)で変更できる.
音量の `level` は 0 から 1, `muted` は真偽値を指定する.
複数機器がある場合は `--device-index 0` のように対象を明示する.

Ctrl+C で待機を終え, 入力の購読と機器の接続を解放する.
音量の購読はこの例では開始しない. OS のエラーは `failed` と理由を表示し,
後続の入力を受け付ける. 入力接続自体が失敗した場合は解放後に例外を伝える.
`done` は OS が設定要求を受け付けたことを示す. 物理出力への反映完了を表さない.

## 確認範囲

自動テストは, fake の出力を注入した入力再生, 設定時の I/O 不在,
エラー結果, 既定実行での実機への非接続, 終了時の登録・接続解放を確認する.
N4 Pro から実際の音量変更までを通した Windows/macOS 実機試験は未実施.
各アダプターの対応条件と検証範囲は[Windows](../docs/windows-volume.md)と
[macOS](../docs/macos-volume.md)を参照する.
