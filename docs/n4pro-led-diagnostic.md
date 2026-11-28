# N4 Pro の LED 要求を記録する

この診断は, 指定した4個分の RGB 色を一度だけ SDK へ渡し, 要求内容と戻り値を JSONL に記録する.
N4 Pro を使う他のアプリを終了し, [README のセットアップ](../README.md#セットアップ)を済ませてから実行する.

```powershell
git -C vendor/streamdock-sdk rev-parse HEAD
mise exec -- uv run python tools/n4pro_led_diagnostic.py --colors FF0000 00FF00 0000FF 204080 --output logs/led-colors.jsonl
```

`--colors` は `RRGGBB` 形式の色を必ず4個受け取る. 例は赤, 緑, 青, 暗い青緑の順で SDK に渡す.
各 RGB 成分は0から255までの整数になる. SDK の配列順と機器上の物理位置との対応は実機で記録する.
不正な色や個数は機器の選択・接続を始める前に拒否する.
既存の出力ファイルを指定した場合は上書きせずに終了する.

複数台の場合は `--device-index 0` などで選ぶ. `--sdk` で SDK の checkout を指定できる.
実行後は `--output` に指定したパスから記録を確認する.
既定の保存先は `logs/led-YYYYMMDD-HHMMSS.jsonl` である.

機器は SDK の `open()` で接続し, `set_device()` でレポートサイズと対応機能を設定する.
`open()` は reader と heartbeat を開始する. `set_device()` は transport のレポートサイズ設定を呼ぶ.
接続後の準備は `set_device()` によるレポートと対応機能の設定を使う.
終了時は `close(notify=False)` を呼ぶ. LED の以前の色は取得できないため, 終了後も要求した色が残る可能性がある.

## JSONL と実機観察

各行の `time` は書き出し時の壁時計, `monotonic_ns` は同じプロセスの単調時計である.
`session` に指定した機器 index と SDK のパスを記録する. index未指定時の値は `null` となる.
SDK の revision は SDK checkout の Git HEAD から取得し, `sdk_revision` へ保存する.
Git の実行は各2秒で打ち切り, Git が利用できない場合や SDK 自体の checkout を確認できない場合は `null` になる.
`device` は接続と対応機能の設定後に, SDK オブジェクトのクラス名, VID/PID, 取得済みの firmware 文字列を記録する.
VID/PID や firmware が取得できない場合は `null` になる. この記録のための追加の機器問い合わせは行わない.

| type | 記録する内容 |
| --- | --- |
| `device` | SDK のクラス名, VID/PID, SDK が保持する firmware |
| `led_request` | SDK へ渡す順番どおりの RGB 色の4要素配列 |
| `led_result` | SDK の戻り値, `outcome`, 色設定呼び出しに要した `elapsed_ms` |
| `led_failed` | 色設定が投げた例外の型とメッセージ, 呼び出しの所要時間 |
| `closed` | SDK の終了処理が正常に復帰し, reader/heartbeat の停止を確認したこと |
| `close_failed` | 終了処理の例外 |
| `error` | 選択・接続・送信・終了を含む診断の例外 |

`outcome` は SDK の戻り値0で `sdk_success`, 非ゼロで `sdk_failed`, 戻り値 `None` で `unconfirmed` となる.
CLI の終了コード0は `sdk_success` の場合だけで, それ以外は非ゼロになる.
例外が起きても終了処理を試み, 診断と終了が両方失敗した場合は両方を例外グループで報告する.
SDK の終了処理が正常に戻っても reader や heartbeat が生きている場合は, native 資源の解放を未確認として `close_failed` にする.
記録自体の書き込みが失敗すると欠損するため, 標準エラーと終了コードも確認する.

SDK の成功と LED の発光を対応付けるため, 実行前後を目視または撮影し, 配列のどの色がどこに現れたかを記す.
ほかの色が保持されるかを調べる場合は, 次の実行で一つの RGB 値だけを変え, 同じ4要素配列を送って比較する.
このツールは全4色の希望値を渡すため, 単独 LED の更新命令が存在することまでは示さない.
輝度の単位, モード・光連動・reset の優先順位, sleep や切断後の保持は #39 の実機調査に残る.

拡張へLEDを提供する初回案では、全体設定と4色の出力を機器の接続所有者に集める。
拡張ごとに個別LEDを割り当てる案では、所有者が割り当てられた色の要求を合成してから4色を送る。
個別割り当ての採用は、配列と物理位置の対応、全体モードの影響、他の色を維持できる条件を実機で確認した後に判断する。

## 固定 SDK と自動検証

固定 revision `fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb` では N4 Pro に4個の LED と個別色設定の対応がある.
`set_single_led_color()` は各要素を RGB の3成分として transport へ渡し, transport の C API は結果コードを返す.
API の戻り値から機器の ACK や物理的な発光完了を判定できる範囲は未確認である.
[N4 Pro の設定](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDockN4Pro.py#L259-L267)・[LED の SDK 経路](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Transport/LibUSBHIDAPI.py#L744-L766)

[自動テスト](../tests/test_led_diagnostic.py)は fake を使い, 色の検証, 一度の送信, SDK 結果の区別, 送信例外, 終了処理を確認する.
SDK revision と機器情報の保存, 取得不能時の `null` も fake で検証する.
今回の実装作業で実機への LED 送信は実施していない.
