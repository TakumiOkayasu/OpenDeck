# OpenDeck

Mirabox N4 Proの入力を、機器から独立した操作へ割り当てる個人用ソフトウェア。
Windowsでの利用を先行し、OSと機器に接する実装を交換できる構成にする。

このプロジェクトは、ハードウェアの情報を抽象化した入力データとAPI・インターフェースを提供する。
拡張作者はキー入力監視や機器との接続を実装せず、公開契約に従って操作の振る舞いを実装できる。
個別の拡張機能と、基盤を利用する拡張ホストの検討は、基盤のAPI提供と分けて扱う。

現在は、入力の認識・状態・履歴と、割り当てた操作の実行を提供する。アプリ起動は基盤を使う具体例として同梱する。
外部拡張の読み込みと開始・終了の管理、設定画面はまだ提供していない。
N4 Proのボタン画像・画面背景の描画とタッチ入力は[表示とタッチ入力](docs/design/display.md)を参照する。
個別操作の仕様と開発予定は、それぞれの拡張側で管理する。
従来のPython経路では、WindowsのN4 Pro実機で通常ボタンの単独入力からアプリのプロセス生成までを確認済み。
C++基盤への移行後も、Windowsで操作できたことを2026-10-20のユーザー報告で確認した。
同時押し、保持状態、切断・再接続など個別の条件とmacOS実機の確認範囲は別途扱う。
Windows・macOS・LinuxのビルドとテストはCIで検証する。

## 構成

小さな抽象契約、入力の認識・状態・FIFOと操作の選択・配送をC++で実装し、pybind11でPythonへ接続する。
CLI、設定、既存SDKアダプタと拡張の具体処理はPythonを使う。
拡張はボタンの開始・継続・終了も利用でき、短押し・長押しの分類は拡張側で決める。
Pythonとの保証の違いと公開能力の境界は[詳細設計](docs/implementation.md#cとpythonの境界)に置く。

## セットアップ

C++23、Python 3.15、[uv](https://docs.astral.sh/uv/)と[mise](https://mise.jdx.dev/)を使用する。
uvとmiseを先にインストールし、C++コンパイラ・CMake・Ninjaはリポジトリの固定設定から取得する。
言語モードとツールチェーン、対象architectureは[詳細設計](docs/implementation.md#言語とビルドツール)を参照する。
実行と開発はWindowsネイティブ環境で行え、WSLは必要ない。

```sh
git clone --recurse-submodules https://github.com/TakumiOkayasu/OpenDeck.git
cd OpenDeck
mise trust
mise install --locked
mise exec -- uv sync --locked --extra device
mise exec -- uv run opendeck --help
```

既にcloneしている場合は `git submodule update --init --recursive` を実行する。
SDKは [MiraboxSpace/StreamDock-Device-SDK](https://github.com/MiraboxSpace/StreamDock-Device-SDK)
の固定したcommitを参照する。SDKのソースとnative libraryの配置は変更しない。
Pythonは `.python-version` に従ってuvが選択する。初回はツール、Pythonと依存パッケージのダウンロードが必要になる。
以下のコマンドも `mise exec --` を通し、固定したコンパイラとビルド環境を使用する。
`mise exec -- uv sync` はscikit-build-coreを通じてnative extensionをビルドする。
native配下やCMakeLists.txtも再ビルド判定に含めているため、C++の変更後も同じsyncを実行する。

### C++エディタの設定

セットアップ後、clangd用のcompile_commands.jsonを生成する。

```sh
mise exec -- uv run python tools/configure_clangd.py
```

[.clangd](.clangd)が `build/clangd/compile_commands.json` を参照する。
言語モードもCMakeが生成した各targetのコマンドに従い、エディタだけの設定で上書きしない。
core・テスト・Python bindingを含めてconfigureし、プロジェクトのincludeと、
開発用 `.venv` のpybind11・Pythonのheader検索pathを取得する。
`build/core` はPythonを無効にしているため、binding用のdatabaseには使わない。
CMake設定・依存・Python環境を変えた後は上記コマンドを再実行する。
生成ファイルは環境固有なのでcommitしない。

エディタが使うclangdもLLVM 23以上を指定し、言語サーバーを再起動する。
Project Diagnosticsで公開headerが見つからない場合も、まずdatabaseを生成・更新する。
設定済みでも古い診断が残る場合は、Zedの `editor: restart language server` を実行する。
Pythonの依存をsyncした後にimportの古い診断が残る場合も、対象の言語サーバーを再起動する。
`mise exec -- clangd --version` はターミナル側の確認であり、エディタの実行pathも確認する。
診断確認は `mise exec -- clangd --check=native/src/runtime.cpp` と
`mise exec -- clangd --check=native/python/module.cpp` で行える。

## ボタン操作

```sh
mise exec -- uv run opendeck devices
mise exec -- uv run opendeck run examples/buttons.json
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
mise exec -- uv run opendeck run examples/buttons.json --debug
```

起動ログと入力ログを分けて確認する。デコーダーのフィルター前の全SDK rawイベントと
デコードした入力を記録するため、ボタンやノブの操作とログを照合できる。

今回の暫定規則では、単独操作と同時押しは解放時に確定する。
同時押しが成立した場合、その構成入力による単独操作は実行しない。
詳細は[実装設計](docs/implementation.md)を参照。

## 実機なしの確認

```sh
mise exec -- uv run opendeck replay examples/buttons.json examples/button-events.json
mise exec -- uv run pytest
mise exec -- uv run ruff check .
mise exec -- uv run ruff format --check .
```

replayはSDKを読み込まず、記録した入力を同じ認識・割り当て・実行経路へ渡す。
設定された操作は実際に実行するので、サンプルの起動先を自分の環境に合わせる。
認識と境界の検証であり、本体の同時入力の取得を確認するものではない。

SDK・Pythonを使わず、C++基盤だけをビルドして確認できる。

```sh
mise exec -- cmake -S . -B build/core -DOPENDECK_BUILD_PYTHON=OFF \
    -DCMAKE_BUILD_TYPE=Release
mise exec -- cmake --build build/core --config Release
mise exec -- ctest --test-dir build/core -C Release --output-on-failure
```

既存の `build/core` に古いgeneratorやcompilerが保存されている場合は、
最初のconfigureコマンドの `cmake` の直後へ `--fresh` を追加する。

## 操作の拡張

操作種別ごとの設定検証とActionの生成処理を、組み立て側から登録できる。
追加した操作も、機器入力・キーコンフィグの選択・実行処理を変更せずに割り当てられる。
標準CLIが登録する操作は引き続き `launch` のみで、既存のJSON設定はそのまま利用できる。
外部プラグインの自動探索や、ノブなど値を伴う入力への対応は含めない。
押下・回転・押しながら回転を独立して割り当てる要求と、現行APIとの差分は
[入力APIの対応計画](docs/plans/input-api.md)を参照。
生成処理の契約と追加箇所は[操作の生成と登録](docs/implementation.md#操作の生成と登録)を参照。

アプリや拡張は、公開された `Input[Slot]` から仮想キーの発生を受け取る。
物理入力との対応は下位で適合し、操作の割り当ては上位の `Binding` で扱う。
公開import、責務と追加手順は[アプリケーション・拡張の実装ガイド](docs/extensions.md)を参照。
SDK・実機・外部アプリの起動を必要としない例も実行できる。

```sh
mise exec -- uv run python examples/extension.py
mise exec -- uv run python examples/button_state.py
```

前者は独自Actionの登録と実行、後者は現在状態と開始・終了の履歴を別の能力として取得する例。

## ドキュメント

各文書は担当する内容の正本とし、同じ仕様を複数のファイルに複製しない。

- [全体仕様](docs/requirements.md)
- [拡張利用の要件案](docs/requirements/extensions.md)
- [拡張ホストの基本設計案](docs/design/extensions.md)
- [拡張ホストの設計・実装プラン](docs/plans/extension-host.md)
- [配布拡張の互換性調査](docs/compatibility/streamdock.md)
- [ボタン操作の基本設計](docs/design.md)
- [ボタン入力の要件](docs/requirements/buttons.md)
- [回転入力の要件](docs/requirements/rotation.md)
- [ボタン能力の基本設計](docs/design/buttons.md)
- [入力APIの対応計画](docs/plans/input-api.md)
- [実装設計・SDKの適合・実機確認](docs/implementation.md)
- [アプリケーション・拡張の実装ガイド](docs/extensions.md)

開発エージェントの作業規約と文書の読み順は[AGENTS.md](AGENTS.md)に置く。

## ライセンス

[MIT](./LICENSE)

SDKは `submodule` 内のライセンスに従う。
