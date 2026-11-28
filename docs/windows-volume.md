# Windows の既定出力の音量操作

`WindowsOutputVolume` は、[既定出力の共通契約](design/output-volume.md)を Windows Core Audio で実装する。
組み立て側で `opendeck.adapters.windows_volume` から生成し、必要な能力だけを拡張へ渡す。

```python
from opendeck.adapters.windows_volume import WindowsOutputVolume

output = WindowsOutputVolume()
try:
    current_volume = output.read_volume()
    current_mute = output.read_mute()
finally:
    output.close()
```

対象は `eRender` / `eConsole` の既定の再生出力で、各読取・変更時に取得する。
音量は Windows の正規化された audio-tapered 値 `0.0..1.0`、ミュートは真偽値で扱う。
`set_volume()` と `set_mute()` は OS API の要求受付を返す。反映された値が必要なら読み直す。
ハードウェア制御の有無により、排他モードで実際に音へ反映される条件は機器ごとに異なる。
[既定出力の取得](https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nf-mmdeviceapi-immdeviceenumerator-getdefaultaudioendpoint)・[音量と排他モード](https://learn.microsoft.com/en-us/windows/win32/api/endpointvolume/nn-endpointvolume-iaudioendpointvolumecallback)

## 通知と終了

`subscribe(observer)` は登録を開始し、解除関数を返す。
既定出力・機器の利用可否・音量・ミュートの変化をまとめて通知する。
Observer はアプリケーションの処理を予約し、必要な値をその処理で読み直す。
通知の回数は、個々の OS の変更回数と対応しない。

COM の通知登録・出力の再取得・登録解除は、一つの専用スレッドで行う。
OS の callback は待機を行わず、Win32 event に変更を記録する。
専用スレッドは event の待機から戻って既定出力の登録を更新し、Observer に通知する。
読取・変更は、それぞれの呼出しスレッドで COM の初期化を所有するか、既存の初期化を利用する。
暗黙の MTA を利用する場合は操作中の参照を保持し、通知スレッドの終了で MTA が解体されないようにする。
[callback の制約](https://learn.microsoft.com/en-us/windows/win32/api/endpointvolume/nn-endpointvolume-iaudioendpointvolumecallback)・[COM の初期化](https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/nf-combaseapi-coinitializeex)

解除関数と `close()` はアプリケーションの所有スレッドから呼ぶ。
Observer の中から呼ぶと `RuntimeError` になる。他の通知スレッドの終了を相互に待つことを防ぐため、解除もアプリケーションへ予約する。
解除は新しい通知の受付を停止し、専用スレッドで native 登録を解放してから戻る。
受付済みの Observer が完了するまで待つ場合がある。
終了時の API 失敗は `VolumeError` として返り、登録を所有したスレッドを保持する。
解除関数または `close()` を再度呼ぶと、そのスレッドで解放を再試行できる。

初期登録の途中で失敗しても、取得済みの登録を解放する。
後始末も失敗したときは、元の失敗に後始末の情報を付け、アダプターが解放の責任を保持する。
この場合も `close()` で再試行できる。
通知後の再登録が失敗したときはログと通知で知らせ、未解決の失敗は解除時にも返す。
後続の OS 通知で再登録できれば、その失敗は解消する。

## 失敗と確認範囲

出力不在と消失は `NO_OUTPUT`、インターフェース未対応は `UNSUPPORTED`、
アクセス拒否は `PERMISSION_DENIED`、その他の HRESULT は `FAILED` に対応付ける。
失敗には操作名と16進数の HRESULT を残す。取得不能な音量やミュートは `VolumeError` になる。
Observer の予期しない例外はログへ報告し、native 登録の解放後に元の例外を所有側へ返す。
[取得エラー](https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nf-mmdeviceapi-immdeviceenumerator-getdefaultaudioendpoint)・[Activate のエラー](https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nf-mmdeviceapi-immdevice-activate)

[fake 試験](../tests/test_windows_volume.py)は、共通契約、HRESULT の変換、不正値の拒否、
通知と再登録、開始・終了の競合、開始途中と解放の失敗、COM 操作のスレッド所有を確認する。
試験の音量・ミュート変更は fake の状態だけを操作する。
LLVM 23.1.3、Windows SDK 10.0.26100.7705、MSVC の CRT と CPython 3.15.2 の Windows 用ライブラリで、
x64 の `_native.pyd` をクロスコンパイル・リンクし、`PyInit__native` のエクスポートを確認した。
[Windows 上の読み取り専用の確認](../tests/test_windows_volume_native.py)は用意したが、Windows 上での実行は未実施。
実際の音量・ミュート変更、外部通知、既定出力切替、切断と再接続の実機確認も残る。
