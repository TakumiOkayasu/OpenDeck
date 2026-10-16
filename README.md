# OpenDeck

Mirabox N4 Proの入力を、機器から独立した操作へ割り当てる個人用ソフトウェア。
Windowsでの利用を先行し、OSと機器に接する実装を交換できる構成にする。

現在の実装範囲は、通常ボタンの単独・同時押しから設定したアプリの起動要求まで。
音量、マクロ、管理者権限での起動、割り当て切替、設定画面と機器への描画は未実装。
WindowsのN4 Pro実機では、通常ボタンの単独入力からアプリのプロセス生成までを確認済み。
同時押しの実機動作とmacOSでの動作は未確認。

## セットアップ

Python 3.14と[uv](https://docs.astral.sh/uv/)を使用する。
実行と開発はWindowsネイティブ環境で行え、WSLは必要ない。

```sh
git clone --recurse-submodules https://github.com/TakumiOkayasu/OpenDeck.git
cd OpenDeck
uv sync --locked --extra device
uv run opendeck --help
```

既にcloneしている場合は `git submodule update --init --recursive` を実行する。
SDKは [MiraboxSpace/StreamDock-Device-SDK](https://github.com/MiraboxSpace/StreamDock-Device-SDK)
の固定したcommitを参照する。SDKのソースとnative libraryの配置は変更しない。

## ボタン操作

```sh
uv run opendeck devices
uv run opendeck run examples/buttons.json
```

`examples/buttons.json` はWindows向けのサンプル。
`inputs` は機器から独立した入力の識別、`device.keys` は実機との対応、
`bindings` は入力と操作の対応を指定する。
サンプルの `device.keys` の `1`・`2` は通常ボタンの入力レポートのコード1・2を指し、
SDKの画像配置用インデックスではない。
起動するプログラムは `actions` の引数列で設定する。
シェルのコマンド文字列へ組み直さない。
複数のN4 Proを接続した場合は `--device-index` で選ぶ。
`run` は接続成功後に入力待機をstderrへ表示し、フォアグラウンドでCtrl+Cまで動作する。
サンプルの対象はボタン1・2のみで、ノブへの操作の割り当ては未実装。

入力が反応しない場合は、次のコマンドで起動と入力のDEBUGログをstderrへ出す。

```sh
uv run opendeck run examples/buttons.json --debug
```

起動ログと入力ログを分けて確認する。デコーダーのフィルター前の全SDK rawイベントと
デコードした入力を記録するため、ボタンやノブの操作とログを照合できる。

今回の暫定規則では、単独操作と同時押しは解放時に確定する。
同時押しが成立した場合、その構成入力による単独操作は実行しない。
詳細は[実装設計](docs/implementation.md)を参照。

## 実機なしの確認

```sh
uv run opendeck replay examples/buttons.json examples/button-events.json
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

replayはSDKを読み込まず、記録した入力を同じ認識・割り当て・実行経路へ渡す。
設定された操作は実際に実行するので、サンプルの起動先を自分の環境に合わせる。
認識と境界の検証であり、本体の同時入力の取得を確認するものではない。

## 操作の拡張

操作種別ごとの設定検証とActionの生成処理を、組み立て側から登録できる。
追加した操作も、機器入力・キーコンフィグの選択・実行処理を変更せずに割り当てられる。
標準CLIが登録する操作は引き続き `launch` のみで、既存のJSON設定はそのまま利用できる。
外部プラグインの自動探索や、ノブなど値を伴う入力への対応は含めない。
生成処理の契約と追加箇所は[操作の生成と登録](docs/implementation.md#操作の生成と登録)を参照。

アプリや拡張は、公開された `Input[Slot]` から仮想キーの発生を受け取る。
物理入力との対応は下位で適合し、操作の割り当ては上位の `Binding` で扱う。
公開import、責務と追加手順は[アプリケーション・拡張の実装ガイド](docs/extensions.md)を参照。
SDK・実機・外部アプリの起動を必要としない例も実行できる。

```sh
uv run python examples/extension.py
```

## ドキュメント

各文書は担当する内容の正本とし、同じ仕様を複数のファイルに複製しない。

- [全体仕様](docs/requirements.md)
- [音量仕様](docs/requirements/volume.md)
- [アプリ起動仕様](docs/requirements/launch.md)
- [マクロ実行仕様](docs/requirements/macro.md)
- [割り当て切替仕様](docs/requirements/contexts.md)
- [ボタン操作の基本設計](docs/design.md)
- [音量の基本設計](docs/design/volume.md)
- [実装設計・SDKの適合・実機確認](docs/implementation.md)
- [アプリケーション・拡張の実装ガイド](docs/extensions.md)

開発エージェントの作業規約と文書の読み順は[AGENTS.md](AGENTS.md)に置く。

## ライセンス

MIT

SDKは `submodule` 内のライセンスに従う。
