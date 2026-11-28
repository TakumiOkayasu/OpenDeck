# 既定の音声出力を操作する契約

拡張は `OutputVolume` を組み立て側から受け取る。組み立て側は稼働環境と設定に応じて実装を選び、購読の解除を所有する。インターフェースと `VolumeError`、`VolumeFailure` は `opendeck` から参照できる。

## 対象と値

- 各操作の開始時に OS の既定の再生出力を選ぶ。Windows では `eRender` / `eConsole`、macOS では既定の出力機器を対象にする。アプリ別、入力機器、通信向け出力の選択は対象外とする。
- `read_volume()` と `read_mute()` は、それぞれ音量とミュートを取得する。操作ごとに取得するため、連続する二つの読取の間に出力先や状態が変わる場合がある。
- `set_volume(level)` は `0.0` から `1.0` の有限な数値を受け取る。`set_mute(muted)` は真偽値を受け取る。範囲外の値や型の誤りは `ValueError` になる。
- 音量の数値は、各 OS の出力レベルの相対位置を表す。機器の分解能や OS の音量曲線により、同じ値で得られる音量は変わる。変更 API の正常復帰は要求の受付を表す。表示に使う実際の値は読み直す。
- 音量とミュートの取得・変更の可否はそれぞれの操作で判定する。同じ機器でも読み取れる項目が変更できるとは限らない。

## 変更通知の購読

`subscribe(observer)` は購読を開始し、終了用の関数を返す。通知は、音量、ミュート、既定出力、または出力の利用可否が変わった可能性を知らせる。通知がまとまる場合があるため、必要な状態は `on_change()` を受けてから読み直す。初期状態が必要な利用側は、購読後に読み取る。

`on_change()` は別スレッドで呼ばれる場合がある。利用側は作業の予約だけを行い、読取・描画・解除は予約先で行う。終了関数が成功すると、新たな通知の受付を停止する。終了前に受け付けた通知は、その後も完了まで進む場合がある。正常に終了した購読の終了関数は繰り返し呼べる。

OS の通知登録や解除が失敗したときは `VolumeError` になる。通知の登録に必要な資源は組み立て側が解放する。

## 失敗の扱い

期待される実行上の失敗は `VolumeError.reason` で判別できる。操作結果や表示に変換する責務は、既存の `Action` と同様に利用側が持つ。

| 理由 | 状況 |
| --- | --- |
| `DISABLED` | 組み立て側の設定により機能が無効 |
| `UNSUPPORTED` | OS、出力機器または操作に対応する制御が利用できない |
| `PERMISSION_DENIED` | OS が権限不足を報告した |
| `NO_OUTPUT` | 既定出力がない、または処理の対象が消失した |
| `FAILED` | その他の OS API の失敗 |

`UnavailableOutputVolume` は、設定で無効化した構成と対応する実装が存在しない構成に使える。取得・設定は対応する失敗を返し、購読からは解除可能な静かな購読を返す。利用側は実装の型を確認せず、同じ契約で呼び出す。実行中に OS API が失敗したときは、選択済みの実装が失敗を報告する。

## OS API の根拠

- Windows の MMDevice は用途を指定して既定出力を取得できる。Endpoint Volume は正規化した音量とミュートを提供する。出力先の変更と音量・ミュートの変更は別の通知から取得する。[既定出力](https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nf-mmdeviceapi-immdeviceenumerator-getdefaultaudioendpoint)・[Microsoft の実装例](https://learn.microsoft.com/en-us/windows/win32/coreaudio/endpoint-volume-controls)・[出力先の通知](https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nn-mmdeviceapi-immnotificationclient)
- macOS の Core Audio HAL は既定出力と、機器ごとのプロパティの有無・書き込み可否を取得できる。機器の main 制御が使える場合にその音量とミュートを操作する。[Core Audio](https://developer.apple.com/documentation/coreaudio)・[Apple の音量操作解説](https://developer.apple.com/library/archive/qa/qa1016/)・[書き込み可否](https://developer.apple.com/documentation/coreaudio/audioobjectispropertysettable(_:_:_:))

[macOS](../macos-volume.md) と [Windows](../windows-volume.md) のアダプター文書に、各実装の選び方と検証範囲を記録する。
