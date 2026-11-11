# 表示とタッチ入力

`View.draw(image)` は画像ファイルのバイト列を描画先へ渡す独立した能力である。PythonはABC、C++は公開headerの抽象クラスとして提供する。PythonとC++のViewを相互変換するbindingは提供しない。既存のAction、Button、Bindingに表示やタッチの責務は追加しない。

N4 Proでは `StreamDockFactory.make_surface(images)` が既存のボタン入力、タッチ入力、画像描画を同じLinkで提供する。`images` は上位で決めたSlotから物理入力番号1〜14への対応である。各 `product.images[slot]` は対応する表示先、`product.screen` は画面の背景を表す。接続を開いている間に描画し、使用後は閉じる。

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

画像のデコード、サイズ変換、回転、転送形式は公式SDKに委譲する。形式とサイズの根拠は[画像表示とタッチ入力の調査](../research/n4pro-display-touch.md#機器とsdkの表示能力)に置く。SDKのボタン画像転送の非ゼロ結果は失敗として通知する。背景転送には完了応答がなく、呼び出しの正常終了は実機への描画完了を保証しない。起動画面を書き換えるSDKのAPIは使用しない。

`product.touch` は `Input[TouchPoint | Swipe]`、`product.touch_subject` は変更通知である。`TouchPoint` のx・yはSDKの値をそのまま提供し、画面上の座標系や表示領域との対応を保証しない。`Swipe` はSDKが通知した方向を提供する。`take()` は入力がなければNone、接続前・切断後や入力失敗時はInputErrorとなる。通知は取り出しの契機であり、通知数とイベント数は一致しない。タップ開始・終了やスワイプ中の軌跡は推測しない。

アプリがLinkの管理と入力の配送を担当し、描画内容、タッチ位置の解釈や操作の実行は拡張側で決める。描画対象の対応はアプリが構成する。実機での表示形式と画像位置、タッチ座標との対応、入力の欠落の有無、表示完了は未検証である。
