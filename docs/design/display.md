# 表示とタッチ入力

`View.draw(image)` は画像ファイルのバイト列を描画先へ渡す独立した能力である。PythonはABC、C++は公開headerの抽象クラスとして提供する。PythonとC++のViewを相互変換するbindingは提供しない。既存のAction、Button、Bindingに表示やタッチの責務は追加しない。

N4 Proでは `StreamDockFactory.make_surface(images)` が既存のボタン入力、タッチ入力、
画像描画を同じLinkで提供する。`images` は上位で決めたSlotから物理入力番号1〜14への対応である。
各 `product.images[slot]` は対応する表示先、`product.screen` は画面の背景を表す。
接続を開いている間に描画し、使用後は閉じる。

ボタンの保持状態と開始・終了も必要な場合は、
`StreamDockFactory.make_button_surface(images)` で `ButtonSurfaceProduct` を構成する。
`product.buttons[slot]` の Button とタッチ入力・描画先は同じ Link を共有する。
保持入力から操作を成立させる解釈は利用側に置く。
`make_buttons()` と `make_surface()` を別々に呼ぶと、それぞれの製品が接続口を持つ。

```python
from pathlib import Path

from opendeck import Slot
from opendeck.adapters.streamdock import StreamDockFactory

slot = Slot("primary")
factory = StreamDockFactory({1: slot}, (), Path("vendor/streamdock-sdk"))
product = factory.make_surface({slot: 1})
product.link.open()
try:
    product.images[slot].draw(Path("icon.png").read_bytes())
    product.screen.draw(Path("background.jpg").read_bytes())
finally:
    product.link.close()
```

保持入力を使う場合も接続を開く所有者は一つにする。
各拡張には組み立て側が選んだ Button の読取・履歴・通知や View を渡す。
Button の状態と履歴は[ボタン能力の整合条件](buttons.md#整合条件)に従い、
接続終了や入力失敗で利用不能になる。
初期画像と `prepare_display` は両方の surface 構成で利用でき、
初期描画や準備の失敗は接続・callback の解放を伴う。
別プロセスや純正ソフトとの USB 排他、
sleep・抜き差し後の再接続と希望出力の復元は実機を含む確認事項として残る。

fake では、所有側が閉じた同じ Link を明示的に開き、設定した初期画像が再送されることを確認した。
終了時点の未取得入力は、次の接続の Action 呼び出しには引き継がれない。
実行中に描いた画像の保持や、物理的な再接続後に同じ機器を開けるかは、別途確認する。

画像のデコード、サイズ変換、回転、転送形式は公式SDKに委譲する。形式とサイズの根拠は[画像表示とタッチ入力の調査](../research/n4pro-display-touch.md#機器とsdkの表示能力)に置く。SDKのボタン画像転送の非ゼロ結果は失敗として通知する。背景転送には完了応答がなく、呼び出しの正常終了は実機への描画完了を保証しない。起動画面を書き換えるSDKのAPIは使用しない。

`product.touch` は `Input[TouchPoint | Swipe]`、`product.touch_subject` は変更通知である。
`TouchPoint` のx・yはSDKの値をそのまま提供し、画面上の座標系や表示領域との対応を保証しない。
`Swipe.direction` は指の移動方向を表す。N4 Proアダプタは実機で確認されたSDKの方向を反転して提供する。
従来はSDKの方向をそのまま公開していたため、既存の拡張での左右の解釈が変わる。
`take()` は入力がなければNone、接続前・切断後や入力失敗時はInputErrorとなる。
通知は取り出しの契機であり、通知数とイベント数は一致しない。タップ開始・終了やスワイプ中の軌跡は推測しない。

アプリがLinkの管理と入力の配送を担当し、描画内容、タッチ位置の解釈や操作の実行は拡張側で決める。描画対象の対応はアプリが構成する。実機での表示形式と画像位置、タッチ座標との対応、入力の欠落の有無、表示完了は未検証である。
