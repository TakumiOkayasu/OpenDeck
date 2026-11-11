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
動的表示は`set_frame_background` / `set_background_frame_stream`の経路を調べる。
フレーム送信はPython wrapperから成否を取得できず、呼び出しが戻っただけでは実機の表示完了を保証できない。
[SDKの実装](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDock.py#L324-L366)
と[ROM書込みの注意](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDock.py#L505-L521)を参照。

## タッチとスワイプ

[固定SDK](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDockN4Pro.py#L53-L119)は、
`ACK ARX`形式の座標をタッチ用callbackから通知する。
別の入力callbackでは左右のスワイプを通知する。
Wikiには座標列と右スワイプが記録されているが、左スワイプ、タッチの開始・終了や座標範囲の保証を実機で確認した証拠ではない。
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
