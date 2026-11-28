# macOSの音量adapter

`MacOSOutputVolume` は, 現在の既定出力機器のmain音量とミュートを
`OutputVolume` として提供する. 組み立て側で
`opendeck.adapters.macos_volume.MacOSOutputVolume` を生成し, 拡張へ注入する.

## 対応範囲と結果

Core Audio HAL の `AudioObjectGetPropertyData` / `AudioObjectSetPropertyData` を
標準ライブラリの `ctypes` から呼ぶ. 追加パッケージは使用しない.
音量は出力側main elementの `volm`, ミュートは `mute` を扱う.
機器にmain controlがない場合や変更不可の場合は `UNSUPPORTED` となる.
各channelの組み合わせによる代用は実装していない.

各操作の直前に `dOut` を解決する. 対象不在と明示的な `livn = 0` は
`NO_OUTPUT` となる. Core Audioの権限不足, 未対応, API失敗は
`VolumeError` に元の `OSStatus` を含めて報告する.
`set_volume()` / `set_mute()` の正常復帰はAPIが要求を受け付けたことを表す.
機器の丸めや非同期反映があるため, 反映後の値は再取得する.

## 通知と解放

`subscribe(observer)` は, 既定出力の変更と現在の機器の音量・ミュート・生存状態を
監視する. 通知は現在値の再取得を促す. 複数の変更はまとめられることがある.
HAL callbackはworkerへの起床通知だけを行い, workerが機器の再取得と
Observerの呼出しを行う. 既定出力が同じIDのまま利用不能になった場合も,
生存状態の監視を維持する.

購読元は返された解除関数を `finally` で呼ぶ.
`MacOSOutputVolume.close()` は所有する全購読と, 開始失敗時に解放できなかった
登録を解放する. 解除失敗は例外となり, 同じ解除関数または `close()` で再試行できる.
開始途中で失敗した場合もadapterを保持し, `close()` を試みる.
後続の `subscribe()` も開始失敗から残った登録の解放を先に試みる.
`close()` 後の新規購読は失敗する.

解除後の遅いHAL callbackは無効化される. 解除に失敗したcallbackも参照を保持し,
以後の通知を無効化したまま残す. interpreter終了前に購読とadapterを解放する.
workerが解除前に配送を受理したObserverは, 解除後に処理を終える場合がある.
配送の受理と解除は同じlockで判断する.
非同期の再登録失敗はログと無効化通知で知らせ, 次のOS通知で再取得する.
未解決の失敗は解除時にも報告する. 読取と変更はそれぞれのOS結果を返す.
Observer自身の例外はworkerの例外として直ちに報告される.
解除時点で保存済みの例外は, 資源の解放後にも元の例外を呼出元へ伝える.
受理済みの処理が解除後に失敗した場合は, workerの例外報告で確認する.

## 確認範囲

2026-11-28にmacOS 27.2.1のUSB出力機器で読取専用の確認を行った.
対象のmain音量controlは存在せず `UNSUPPORTED`, ミュートは `False` だった.
通知登録3件と解除後の登録0件を確認した.
自動テストはfake HALを使用する. システム音量を変更するテストは実行していない.
実機での音量変更, 外部変更通知, 出力先変更と切断後の回復は未確認.
[読取専用の診断](output-volume-diagnostic.md)を使うと, 実機での手動操作と通知後の取得結果を照合できる.

## 一次資料

- 値の範囲と機器ごとのcontrolの対応可否は, Appleの音量操作ガイドと
  Xcode SDKの `AudioHardware.h` / `AudioHardwareBase.h` を照合した.
  [Appleの音量操作ガイド](https://developer.apple.com/library/archive/qa/qa1016/)
- 設定値の反映は非同期となる場合がある. 通知の登録と解除はHALのAPIを使う.
  [設定](https://developer.apple.com/documentation/coreaudio/audioobjectsetpropertydata(_:_:_:_:_:_:)) /
  [通知登録](https://developer.apple.com/documentation/coreaudio/audioobjectaddpropertylistener(_:_:_:_:)) /
  [通知解除](https://developer.apple.com/documentation/coreaudio/audioobjectremovepropertylistener(_:_:_:_:))
- C callbackは参照を保持する必要がある.
  [Pythonのctypes callback](https://docs.python.org/3.15/library/ctypes.html#callback-functions)
