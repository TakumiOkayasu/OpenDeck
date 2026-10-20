# アプリケーション・拡張の実装ガイド

OpenDeckを利用するアプリや独自操作を、機器の詳細から独立して実装するための手引き。
現在の手動による組み立てを説明する。外部拡張ホストの次段階は[要件案](requirements/extensions.md)と[基本設計案](design/extensions.md)を参照する。

基盤はC++20で実装し、Pythonから公開契約を使う。
Python側はABCを明示的に継承して実装する。保証の範囲と公開能力・内部書込みの分離は
[詳細設計](implementation.md#cとpythonの境界)に従う。

契約の意味や整合条件は、次の正本を参照する。

- [理想入力とキーコンフィグ](design.md#理想入力とキーコンフィグ)
- [責務と契約](design.md#責務と契約)、[整合性の規約](design.md#整合性の規約)
- [契約の表現](implementation.md#契約の表現)
- [ボタン能力](design/buttons.md)
- [操作の生成と登録](implementation.md#操作の生成と登録)

## 公開契約をimportする

アプリ・拡張で使う共通契約は、パッケージルートから参照できる。

```python
from opendeck import (
    Action,
    Binding,
    Button,
    Change,
    Chord,
    Input,
    InputError,
    Observer,
    Read,
    Result,
    Slot,
    Status,
    Subject,
    input_view,
    read_view,
    subject_view,
)
```

このimportはnative extensionを必要とするが、設定処理、Device SDKやアダプタは読み込まない。
具体実装は組み立て側で明示的に選ぶ。Pythonで独自操作を書く場合は`class Record(Action):`のように
契約を継承し、すべての必須メソッドを実装する。欠けた実装は生成できない。
Pythonの署名や返却値をC++コンパイラが静的に保証するものではない。

## アプリ側で入力と割り当てを決める

仮想キーに相当する既存の識別は `Slot` を使う。
`Slot` は文字列を区別する名目的な型であり、別のKey型や固定コード一覧を追加しない。
例の `PRIMARY = Slot("primary")` は、上位が選んだデモ用の名前。
物理ボタン番号、操作名、OSのキーボードVKコードではない。

アプリの配送処理は `Input[Slot]` と `Binding` だけを受け取る形にする。
`take()` で成立済みの一回分を受け、`binding.select(slot)` で操作を選ぶ。
この`Input[Slot]`は成立したSlotを返し、空なら`None`、取得失敗なら`InputError`となる。
汎用の`Input[T]`の返却値はTで決まり、Buttonの履歴など別の値にも使える。
選んだ `Action.run()` にSlotや機器情報を渡す必要はない。

上位が所有する `Binding` の変更は、同じ入力へ別の操作を割り当てる変更。
物理入力からSlotへの適合変更は、同じ上位入力を別の機器や取得方式で実現する変更。
両者を分け、機器の交換に合わせて操作の実装やSlot名を書き換えない。
`Chord` を使う場合も、成立を検出するのは入力の実現側である。
詳しくは[理想入力とキーコンフィグ](design.md#理想入力とキーコンフィグ)を参照。

## 実行できる最小例

[examples/extension.py](../examples/extension.py)は、独自操作を登録し、
再生入力から実行する組み立ての例。リポジトリのルートで実行する。
環境の準備は[README](../README.md#セットアップ)を参照。

```sh
uv run python examples/extension.py
```

期待する標準出力は次の2行。

```text
primary: done
recorded by extension
```

SDK、実機、外部アプリの起動を必要としない。
再生による確認であり、実機の取得能力を検証する例ではない。

- `Record` は文字列と書き込み先のcallableを保持する独自Action。
  `run()` が書き込みを行い、`Result(Status.DONE)` を返す。
- `build(options)` は項目が `{"text"}` だけで、その値が文字列かを検証する。
  `messages.append` を書き込み先として取り込むが、生成時には呼ばない。
- `config.parse` に `{"record": build}` を渡し、`kind: record` を明示的に登録する。
  `remember` は構成した操作の名前で、Slotの `primary` とは別の識別である。
- `device.keys` の `"1"` を `PRIMARY` へ対応付け、`ReplayFactory` に渡す。
  `Edge(1, True)` と `Edge(1, False)` が押下・解放を再生する。
- `dispatch` が受け取るのは `Input[Slot]` と `Binding` だけ。
  接続の開始・解放は組み立て側に残し、配送処理へ機器情報を渡さない。

`primary: done` は配送結果の表示、続く行はリストへ記録された内容の表示。
標準CLIは引き続き `launch` だけを登録するため、この明示的な組み立てを実行する。
JSONに未知のkindを書くだけでは独自操作は登録されない。

## ボタンの現在状態と変化を使う

[examples/button_state.py](../examples/button_state.py)は、再生入力からボタンの開始・終了と現在状態を取得する例。

```sh
uv run python examples/button_state.py
```

期待する標準出力は次の3行。固定した時計を渡しているため、実時間の待機は必要ない。

```text
pressed=True at=1.0
pressed=False at=2.0
current=False
```

組み立て側は`factory.make_buttons()`で製品を作り、上位で選んだSlotからButtonを選ぶ。
現在状態を使う処理へは`Read[bool]`、開始・終了を使う処理へは`Input[Change]`を渡す。

```python
def receive(state: Read[bool], changes: Input[Change]) -> None:
    while (change := changes.take()) is not None:
        print(f"pressed={change.pressed} at={change.at}")
    print(f"current={state.read()}")


button = product.buttons[primary]
receive(read_view(button), input_view(button))
```

各helperは任意の`Read[T]`、`Input[T]`、Subjectの実装から、必要なメソッドだけを持つviewを作る。
このviewから受信や失敗を書き込むことはできない。接続の開始・終了は組み立て側で扱う。
短押し・長押しや同時押しの優先を解釈する場合は、取得した変化を使って拡張側で決める。

通知も必要ならSubjectだけを渡し、Observer登録を組み立て側で解除する。
同じ製品を開いて一度配送する部分は次の形になる。

```python
from opendeck.runtime import Wake

subject = subject_view(button)
wake = Wake()
subject.add(wake)
try:
    product.link.open()
    wake.wait()
    receive(read_view(button), input_view(button))
finally:
    try:
        subject.remove(wake)
    finally:
        product.link.close()
```

on_changeは起床を予約するだけとし、起床後にtakeで履歴を取り出す。
通知回数と変化数は対応させない。入力の利用不能はInputErrorで扱い、正常な解放に置き換えない。

## 追加する場所を選ぶ

- **実行内容を増やす**: 独自モジュールにActionを実装する。
  必要な引数と対象の能力を構成時に受け取り、入力元を知らずに実行できる形にする。
- **設定からその操作を作る**: 操作固有のbuilderを用意する。
  固有項目を検証し、必要な対象だけを渡してActionを返す。
  設定処理や機器用Factoryへ操作ごとの分岐を追加しない。
- **機器・SDK・OSとの接続を増やす**: 対応するアダプタを追加する。
  入力の取得・適合や対象への反映を担当し、Bindingの所有や操作選択を持ち込まない。
- **これらを接続する**: アプリの組み立て側で実装と登録表を選び、接続を所有する。
  既存配置の参考は[コードの配置と利用範囲](implementation.md#コードの配置と利用範囲)。

builderへ渡る項目やエラーの扱いは、
[操作の生成と登録](implementation.md#操作の生成と登録)に従う。
構成時に操作を実行したり、対象の現在状態を読み書きしたりしない。

## 入力を提供する拡張

下位の入力提供側は `Input[Slot]` と `Subject` を別の能力として提供する。
内部でSourceを使う場合も、利用側へはinput・subjectのviewを渡し、publishや失敗の書込み口を渡さない。
通知を利用する組み立てでは、`Subject.add` でObserverを登録する。
`Observer.on_change()` は処理側の起床を予約するだけにし、入力値や操作を運ばない。
登録した組み立て側がfinallyでremoveし、接続も解放する。
SDKのcallback内でBindingを適用したり、Actionを実行したりしない。

配送側は起床後に `take()` を繰り返し、通知回数を入力件数とみなさない。
初回配送、ロック、切断、失敗時の扱いを含め、
[整合性の規約](design.md#整合性の規約)と
[未処理入力と通知](implementation.md#未処理入力と通知)を満たす。

## このガイドの範囲外

公開importは永久的なABI互換を約束するものではない。
自動プラグイン探索、完全なプラグインローダー、sandboxは提供しない。
値を伴う入力、ノブ、表示、動的コンテキストの契約・実装は、この公開面では提供しない。
未確定事項を独自の共通数値やSlotのpayloadとして確定させず、
[設計の範囲](design.md#到達点と範囲)と
[今回の実装範囲](implementation.md#今回の実装範囲)を参照する。
