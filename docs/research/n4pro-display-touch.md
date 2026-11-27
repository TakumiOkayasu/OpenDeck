# N4 Proの画像表示とタッチ入力の調査

固定SDK `fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb` のPython実装、メーカーの説明、
[実機のRaw Input記録](https://github.com/TakumiOkayasu/OpenDeck/wiki/RawInput-Test-Values)を照合した。
SDKのコードから分かることと、実機で確認できたことは分けて扱う。

## 機器とSDKの表示能力

| 対象 | SDKの出力形式 | SDKが使う入力キャンバス | 根拠 |
| --- | --- | --- | --- |
| 通常ボタン | PNGまたはJPEG | 112 x 112 | [形式と画像スロット](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDockN4Pro.py#L13-L29)・[画像形式](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDockN4Pro.py#L233-L249) |
| 副画面の4画像スロット | PNGまたはJPEG | 176 x 112 | 同上 |
| 背景のフレーム | JPEG | 800 x 480 | [画像形式](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDockN4Pro.py#L251-L265)・[フレーム送信](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDock.py#L355-L366) |

SDKのサイズは画像変換の入力キャンバスであり、上記だけでタッチ座標系や実際の表示位置を確定できない。
画像キーの1から4は副画面、6から15は通常ボタン用。通常ボタンの入力番号1から5は画像スロット11から15に対応する。
入力番号、SDKの入力キー、画像スロット番号は独立して扱い、SDKの画像番号を基盤の入力識別へ持ち込まない。

[Pillowによる変換](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/ImageHelpers/PILHelper.py)は、
サイズを合わせ、180度回転し、静止画をエンコードする。
ボタン画像はPNG対応設定でも、アルファ情報がなければJPEG、あればPNGを選ぶ。
透過を含む画像をJPEGへ変換する場合は黒背景へ合成する。動的背景のフレームはJPEGである。
ファイルとして読み込める形式はPillowのデコーダーに依存するため、入力形式の全種類をハードウェアの対応形式とは扱わない。
アニメーションは別の機構であり、静止画の描画だけでアニメーションを提供したとはしない。

`set_touchscreen_image`は名前に反して起動ロゴのROM書込みであり、SDK自身が繰り返しの描画に使用しないよう説明している。
背景の動的表示には `set_frame_background` が呼ぶ `set_background_frame_stream` を使う。
[SDKの実装](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDock.py#L324-L366)
と[ROM書込みの注意](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDock.py#L505-L521)を参照。

## 画像とLEDの出力結果

固定SDKのC APIは各出力から `TransportResult` を返す。
ヘッダーは成功を0とし、通信書込み失敗、書込みのタイムアウトなどのエラーを定義する。
N4 Proの機種設定ではRGB LEDを4個とし、個別色指定を有効にしている。
[C APIの結果コード][transport-results]・[出力関数][transport-output]・[機種設定][device-options]

| 出力 | C API | Python SDKが呼び出し元へ返す結果 |
| --- | --- | --- |
| 通常ボタン・副画面の画像 | `transport_set_key_image_stream` | C APIの結果 |
| 背景フレーム | `transport_set_background_frame_stream` | C APIの結果を破棄し、`None` |
| LEDの明るさ | `transport_set_led_brightness` | C APIの結果を破棄し、`None` |
| LEDの一括色指定 | `transport_set_led_color` | C APIの結果を破棄し、`None` |
| LEDの個別色指定 | `transport_set_single_led_color` | C APIの結果 |
| LED効果のリセット | `transport_reset_led_color` | C APIの結果 |

表は機器ハンドルがあり、各関数がC APIを呼んだ場合の結果を示す。
画像の変換やキーの検証でSDKが所定の例外を捕捉した場合は `-1` が返る。
個別のLED色指定は色リストが空なら送信せずに戻る。
C++ SDKのラッパーは表のすべての出力からC APIの結果を返さない。
[画像の変換と例外処理][device-output]・[Pythonの画像転送][python-images]・
[LEDの機種別分岐][device-leds]・[PythonのLED転送][python-leds]・[C++ラッパー][cpp-output]

現行OpenDeckは通常ボタン・副画面の画像で0以外をエラーにし、背景ではSDKが返す `-1` をエラーにする。
背景のC APIが非ゼロを返してもPython SDKで失われるため、現行の描画経路ではその値を検出できない。
LEDの制御はSDKにあり、現行OpenDeckの表示能力には接続していない。
[描画の実装](../../src/opendeck/adapters/streamdock.py#L273-L290)・[表示の契約](../design/display.md)

### 受付・USB転送・応答・実機反映

- `can_write()` は現在の書込み可否、`get_last_error_info()` はtransportの直近のエラー情報を返す。
  いずれも個々の出力要求に対応する転送結果や、表示・LEDの現在状態を取得するAPIではない。
  [書込み可否][python-can-write]・[エラー情報][python-last-error]
- C APIの成功が受付、USB転送の完了、機器ACKのどこまでを表すかは、公開ヘッダーから確定できない。
  Python SDKの入力経路は `ACK ARX` をタッチ座標として解釈し、描画やLED出力のリクエストには対応付けていない。
  [出力関数と読取り関数][transport-output]・[タッチの解析][touch-ack]
- 画像・LEDの現在状態を照会する公開契約や、要求ごとの完了通知は、調査した固定SDKの公開APIでは確認できなかった。
  SDKの返り値やUSB転送の観測だけで、画面への表示やLEDの発光が完了したとは判断できない。

[#41](https://github.com/TakumiOkayasu/OpenDeck/issues/41) では、この調査をもとに、
出力ごとの返り値とUSBの観測、対応する機器応答、目視結果を照合する。
アダプタが取得できる失敗を呼び出し側へ届ける方法と試験、および物理的な反映を確認できる範囲は引き続き検討する。

[transport-results]: https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/CPP-SDK/src/Transport/TransportDLL/transport_c.h#L25-L77
[transport-output]: https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/CPP-SDK/src/Transport/TransportDLL/transport_c.h#L125-L163
[device-options]: https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDockN4Pro.py#L259-L267
[device-output]: https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDock.py#L324-L366
[device-leds]: https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDock.py#L188-L206
[python-images]: https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Transport/LibUSBHIDAPI.py#L649-L704
[python-leds]: https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Transport/LibUSBHIDAPI.py#L719-L773
[cpp-output]: https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/CPP-SDK/src/Transport/TransportCWrapper.cpp#L147-L224
[python-can-write]: https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Transport/LibUSBHIDAPI.py#L521-L536
[python-last-error]: https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Transport/LibUSBHIDAPI.py#L991-L1028
[touch-ack]: https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDockN4Pro.py#L53-L85

## タッチとスワイプ

[固定SDK](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDockN4Pro.py#L53-L119)は、
`ACK ARX`形式の座標をタッチ用callbackから通知する。
別の入力callbackでは左右のスワイプを通知する。
2026-11-12の実機ログでは、指を左へ動かした3回でSDKがright、右へ動かした5回でleftを通知した。SDKの方向名が何を意味するか、その設計意図は未確認である。これはタッチの開始・終了や座標範囲を保証するものではない。
座標列から押下・解放・タップを推測して合成しない。

[メーカーの利用ガイド](https://mirabox.net/fr/blogs/tutorial/how-to-set-up-the-touchscreen-function-of-n4-pro?constraint=beginner-guides)は、
純正ソフトでノブ用表示とタッチバーの操作を説明している。
純正ソフトでの操作説明は、OpenDeckの描画・入力APIの実機動作を検証した証拠ではない。

## 実装前の確認とテストリスト

- 描画の公開契約は表示先に内容を渡す能力として分け、入力・描画・拡張の処理を混ぜない。
- 通常ボタンと副画面のスロットの対応をSDKアダプタ内で扱う。
- 機器を開く前、切断後、終了後の描画を失敗として扱う。SDK側の失敗と結果を確認できない送信を区別する。
- タッチ座標とスワイプを、機器固有型を利用側へ漏らさず取得できるようにする。
- 登録・解除、開始中のイベント、切断、終了後の遅れた通知をfakeで検証する。
- 再生やfakeでの成功と、N4 Proの実機で画像が表示されること・タッチ座標と表示位置が一致することを区別する。

入力データの型、表示先の識別、画像の受け渡しと出力結果の型、描画の所有期間は、利用例から最小限に定める。
