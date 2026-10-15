# OpenDeck

Mirabox N4 Proの入力を、機器から独立した操作へ割り当てる個人用ソフトウェア。
Windowsでの利用を先行し、OSと機器に接する実装を交換できる構成にする。

現在の実装範囲は、通常ボタンの単独・同時押しから設定したアプリの起動要求まで。
音量、マクロ、管理者権限での起動、割り当て切替、設定画面と機器への描画は未実装。
N4 Pro実機、WindowsとmacOSでの動作確認は未実施。

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
起動するプログラムは `actions` の引数列で設定する。
シェルのコマンド文字列へ組み直さない。
複数のN4 Proを接続した場合は `--device-index` で選ぶ。

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

## ドキュメント

各文書は担当する内容の正本とし、同じ仕様を複数のファイルに複製しない。

- [全体仕様](docs/requirements.md)
- [音量仕様](docs/requirements/volume.md)
- [アプリ起動仕様](docs/requirements/launch.md)
- [マクロ実行仕様](docs/requirements/macro.md)
- [割り当て切替仕様](docs/requirements/contexts.md)
- [ボタン操作の基本設計](docs/design.md)
- [実装設計・SDKの適合・実機確認](docs/implementation.md)

## ライセンス

MIT。SDKはsubmodule内のライセンスに従う。
