# Stream Dock配布拡張の互換性調査

2026-10-20に指定された2件の配布物をダウンロードし、実行せずに解析した。
比較対象はOpenDeckのmain `9f8f922`。これは互換性の調査記録であり、個別操作を基盤の要件へ追加する文書ではない。
ホストの責務と依存方向は[基本設計案](../design/extensions.md)で管理する。

## 判定

### System Monitorの判定

- 現行OpenDeck: 外部拡張ホストがないため利用不可
- Windowsでの再利用の見通し: 互換ホストの候補。
  設定画面、画像・タイトルの反映に加え、補助サービスとの連携を検証する必要がある
- 同じ配布物のmacOS利用: Windows実行ファイルのみ。
  Mac入口の実体がなく、そのままネイティブ実行できない

### Windows Screen Controllerの判定

- 現行OpenDeck: 外部拡張ホストがないため利用不可
- Windowsでの再利用の見通し: ボタン用操作を初回検証の候補にできる。
  全操作にはノブ能力も必要。画面側の対応条件が残る
- 同じ配布物のmacOS利用: Windows実行ファイルのみ。
  Mac入口の実体がなく、そのままネイティブ実行できない

### 両配布物に共通する判定の範囲

両者とも、既存の実行ファイルを別プロセスとして動かし、公開された通信形式の相手側を実装する方針を検討できる。
実行ファイルを読み込んでActionへ変換するだけでは成立しない。起動、登録、配置、設定画面、入力と表示の往復を扱う相手が必要になる。
Windowsでの起動・登録・操作成功はまだ確認しておらず、互換性を保証する判定ではない。

ホストと基盤をマルチプラットフォームにしても、拡張自身のWindows依存は解消しない。
macOSでは、対応する実行コードを入手するか、拡張側の機能を別実装する必要がある。

## 取得した配布物

取得元の製品ページから、公開APIが返すCDNの配布URLを確認した。取得したファイルはいずれも拡張子が`.sdPlugin`のZIPだった。
配布URLは版番号を含まないため、以下のSHA-256で今回の入力を識別する。

### System Monitorの配布情報

- 製品ページ: [178366994579015][system-monitor-product]
- 配布ファイル:
  [com.hotspot.streamdock.system.monitor.sdPlugin][system-monitor-download]
- 実取得サイズ: 35,688,835 bytes
- ストア表示/APIの版: `1.6.260814`
- manifestの版: `1.6.260814`
- SDKVersion: `1`
- manifestの対応OS: Windows 7以上
- manifestの必要ホスト版: `2.9.121`
- SHA-256:
  `6639b602c17d734fb66286a72e5088ebd0a00891399272316865e59f1a3e5835`

### Windows Screen Controllerの配布情報

- 製品ページ: [20250925001507][screen-controller-product]
- 配布ファイル:
  [com.mirabox.displaycontrol.sdPlugin][screen-controller-download]
- 実取得サイズ: 473,601 bytes
- ストア表示/APIの版: `1.0.260826`
- manifestの版: `1.1.260826`
- SDKVersion: `1`
- manifestの対応OS: Windows 10以上
- manifestの必要ホスト版: `2.9`
- SHA-256:
  `301a7fb8cc332ecd5e5ab73affa6f9495d58765030078a0b2535c040b6975333`

### 配布物の識別と解析方法

Screen Controllerはストアとmanifestの版が一致しない。版表示だけで同一の内容だと判断しない。
必要ホスト版は配布元ソフトに対する宣言であり、OpenDeckの版や対応済みAPIを意味しない。

ZIPのパス、重複、シンボリックリンクを確認して展開し、manifest、HTML/JavaScript、PEヘッダー、import table、文字列と一部の機械語の参照・呼出経路を調べた。
パッケージのコード、設定画面、実行ファイル、インストーラーは一切実行していない。サービスやドライバーの導入もしていない。
配布物そのものはこのリポジトリへ転載しない。以下の証拠位置は各パッケージ直下を基準とする。

## System Monitor

### System Monitorの構成とOS依存

`manifest.json`には14操作があり、CPU、メモリ、ディスク、ネットワーク、GPU、センサーの表示とサービス保守を含む。
全操作のControllersは`Keypad`、`Information`、`SecondaryScreen`。
`CodePathWin`は`SystemMonitor.exe`で、実体はWindows x64のPE実行ファイルだった。
`CodePathMac`は`SystemMonitor`だが該当ファイルはなく、OS宣言もWindowsのみ。

本体はQt5Widgets、Qt5Gui、Qt5WebSockets、Qt5Network、Qt5Core、Windows API、MSVC runtimeをimportする。
QtとruntimeのDLL、`platforms/qwindows.dll`などが同梱される。
補助EXEの`get_info.exe`、`hwinfo/HWInfoSever.exe`、`hwinfo/SystemMonitorLib1.dll`、`hwinfo/SystemMonitor64.dll`も含む。
DLLの同梱だけで全依存が充足するとは判断しない。

### 確認できた通信と動作経路

#### System MonitorのPI接続と登録

- 根拠: `PropertyInspector/js/action.js:783-791,849-890`
- 静的に確認した内容: PIがホスト情報と操作情報を受け、
  渡されたポートのloopback WebSocketへ接続し、eventとuuidで登録する
- 互換ホストで扱う点: HTML/JavaScriptの実行環境、起動情報と登録

#### System Monitorの設定とメッセージ

- 根拠: `PropertyInspector/js/index.js:209,229,239-278,319-321,436,457`ほか
- 静的に確認した内容: 設定保存、`sendToPlugin`、`openUrl`の呼出がある
- 互換ホストで扱う点: 配置ごとの設定、PIと本体間のJSON中継、外部URLを開く依頼

#### センサー一覧の要求と選択

- 根拠: `PropertyInspector/js/custom_system_monitor.js:25-140,153-210`
- 静的に確認した内容: センサー一覧を要求し、PIへの応答から分類と項目を選ぶ
- 互換ホストで扱う点: 独自payloadを基盤の共通型にせず往復させる

#### PIからのサービス保守要求

- 根拠: `PropertyInspector/js/serviceMaintenance.js:90-134`
- 静的に確認した内容: 接続時に`maintenanceOperation: status`を送り、
  明示操作でinstall/update/uninstall/resetを送る
- 互換ホストで扱う点: PIとの双方向通信。
  設定画面を表示することと保守操作の実行を区別する

#### 本体の表示系JSON構築

- 根拠: `SystemMonitor.exe`の機械語
- 静的に確認した内容:
  `setImage`、`setTitle`、`setState`、`sendToPropertyInspector`のJSON構築関数に呼出元がある
- 互換ホストで扱う点: 拡張が作った表示内容とPI応答を対応する宛先へ反映する

#### 本体の補助側への別接続

- 根拠: 同本体の別接続経路
- 静的に確認した内容: `ws://localhost:15500`を構成して
  `QWebSocket::open`へ渡す呼出経路がある
- 互換ホストで扱う点: ホストへの接続とは別に補助側との通信がある。
  ホストのWS接続だけで完結しない

#### 本体のサービス保守分岐

- 根拠: 同本体の保守分岐
- 静的に確認した内容: uninstallとの比較から、`runas`と`--uninstall`を構成し
  `ShellExecuteExW`を呼ぶ経路がある
- 互換ホストで扱う点: 実行ファイルにはWindowsのサービス保守に関わる処理がある

#### 本体の静的解析位置

本体の表示系JSON構築関数の開始VAは、次のとおり。

- setImage: `0x140029760`
- setTitle: `0x140029d50`
- setState: `0x140029b30`
- sendToPropertyInspector: `0x140029540`

別接続はVA `0x1400023c1`から`0x14001a500`へ、そこでQtのopenへ渡る。
保守処理はVA `0x14000555e`付近の`maintenanceOperation`処理、
`0x1400057cf`付近のuninstall比較から`0x14001e0d0`の処理を経て、
`0x14001e2d2`のShellExecuteExW呼出へ続く。
これらは上記ハッシュの実行ファイルに対する静的な位置であり、実行したログではない。

#### System Monitorの解釈と実行確認に残る事項

表示内容の生成とセンサー取得は拡張側の仕事になる。ホストは表示先と描画能力へ接続する。
ボタンを押していない間にも拡張が稼働し、表示を更新できる経路が必要で、単発のAction呼出だけではこの利用を表せない。
更新の頻度、補助サービスの起動・共存、保守時の権限要求と成功条件、センサー取得の成否は実行確認に残る。
一部の保守経路があることを、全保守操作の成功や全表示APIの利用条件が確定したことへ広げない。

GPU温度の`PropertyInspectorPath`だけはWindowsのバックスラッシュ区切りだった。
パッケージ内資源の解決は外部形式への適合側で扱い、この表記を基盤の共通パス規則にしない。

## Windows Screen Controller

### Windows Screen Controllerの構成とOS依存

`CodePath`と`CodePathWin`は`bin/displayControl.exe`で、実体はWindows x64のPE実行ファイルだった。
`CodePathMac`の`bin/displayControl`は存在しない。実行本体のソースは同梱されず、PIのHTML/JavaScriptは読める。
本体はMSVCP140、VCRUNTIME140、VCRUNTIME140_1、Windows CRTなどをimportし、パッケージにDLLは同梱されない。

- manifestの操作: `action1`、`action3`
  - Controllers: `Knob`
  - 操作の内容: 輝度・コントラストの調整
- manifestの操作: `action2`、`action4`
  - Controllers: `Keypad`
  - 操作の内容: 輝度・コントラストの設定
- manifestの操作: `action5`、`action6`、`action7`
  - Controllers: `Keypad`
  - 操作の内容: 電源、入力ソース、工場出荷設定への復帰

これらは当該拡張の内容であり、OpenDeck基盤の操作一覧ではない。
ノブに対応せず全7操作が利用可能だと表示するのは誤りになる。

### 確認できた通信と依存

#### Screen ControllerのPI接続と登録

- 根拠: `static/action.js:72-76`
- 静的に確認した内容: PIが渡されたポートのloopback WebSocketへ接続し、
  eventとuuidで登録する
- 判断の範囲: 公式PI登録形式との一致

#### Screen Controllerの設定往復

- 根拠: `static/action.js:63-69,79-94`、各`actionN/index.js`
- 静的に確認した内容: 7画面の有効なWebSocket helper呼出16箇所はすべて`saveData`。
  `setSettings`を送り、`didReceiveSettings`を受ける
- 判断の範囲: 設定往復の実callsite。
  送信contextはこのコードではPIの`$uuid`を使うため、
  配置との対応をホスト側で解決する必要がある

#### 言語JSONの読込み

- 根拠: `static/action.js:99-105`
- 静的に確認した内容: `application.language`に応じて相対位置の言語JSONを読む
- 判断の範囲: ホスト情報とローカル資源の読込み

#### 入力ソースの設定画面

- 根拠: `action6/index.js:37-79,84-106`
- 静的に確認した内容: 選択中の画面と対応入力ソース一覧から設定画面を構成する
- 判断の範囲: 画面と機能の対応情報が必要。固定した選択肢だけでは足りない

#### 本体のモニター制御API依存

- 根拠: `bin/displayControl.exe`のimport table
- 静的に確認した内容: dxva2の物理モニター列挙、`GetVCPFeatureAndVCPFeatureReply`、
  `SetVCPFeature`、capabilities取得と、USER32のモニター列挙をimportする
- 判断の範囲: Windowsのモニター制御APIへの依存がある

#### 本体から見つかった文字列

- 根拠: 同本体の文字列
- 静的に確認した内容: loopback WS、登録引数、`dialRotate`、`ticks`、`pressed`、
  画像data URLなどがある
- 判断の範囲: 実行時の使用・必須性・完全な通信順序を文字列だけでは確定しない

#### Screen Controllerの解釈と実行確認に残る事項

`static/action.js`にはsendToPlugin、setImage、setState、openUrlの定義もあるが、
各操作のPIからそれらへの呼出は見つからなかった。
SDK helperの定義だけを、この対象が必要とするAPIの証拠にはしない。
本体側が別途使うAPIは実行時の確認に残る。

importにあるVCP操作は、[Microsoftの説明][microsoft-vcp]ではDDC/CIと画面ごとのcapabilitiesを扱う。
このパッケージでも画面側の対応機能が成立条件になると考えられるが、内蔵画面、接続経路、複数画面、各操作の成否は未確認。
互換ホストが登録を受け付けることと、接続した画面で操作が成功することを分けて確認する。

## 現行基盤との対応と不足

### 実行形式への適合

- 現行OpenDeckとの関係: 標準CLIはlaunchを固定登録しており、外部ホストは未実装
- 次に確認・具体化する内容:
  manifestの読込み、実行条件、プロセスの起動・登録・終了、WSの相手側

### 拡張と配置の識別

- 現行OpenDeckとの関係: Bindingは入力からActionを選択する。外部contextの管理はない
- 次に確認・具体化する内容:
  一つの拡張の稼働と、複数配置の寿命・設定・表示先を区別する

### 入力

- 現行OpenDeckとの関係: Buttonの開始・終了と保持状態は利用可能。
  成立済みの`Input[Slot]`だけでは押下・解放列を復元できない
- 次に確認・具体化する内容:
  Buttonの履歴から外部イベントへ適合する。ノブは別能力として設計する

### 設定とPI

- 現行OpenDeckとの関係: 外部PIの実行環境、設定の保持・通知・中継は未実装
- 次に確認・具体化する内容:
  拡張全体と配置ごとの設定、PI識別子との対応、HTML資源とJSON往復

### 表示

- 現行OpenDeckとの関係: 公開された描画能力と機器への出力接続は未実装
- 次に確認・具体化する内容:
  渡された画像・タイトル・状態と表示先を接続する。内容は拡張が生成する

### 拡張固有の依存

- 現行OpenDeckとの関係: WindowsのサービスやモニターAPIは基盤の責務に含めない
- 次に確認・具体化する内容: 拡張側の実行条件として扱い、未充足や実行失敗を区別する

### 公式資料との照合と責務の境界

[公式登録手順](https://sdk.key123.vip/en/guide/registration.html)では、ホストがEXEへ通信ポート、識別子、登録イベント、infoを渡す。
[受信イベント](https://sdk.key123.vip/en/guide/events-received.html)のwillAppear/willDisappearは操作配置の出現・消失であり、プロセスの開始・終了と同一視しない。
[送信イベント](https://sdk.key123.vip/en/guide/events-sent.html)も含め、実物が使う通信と照合する。
公式資料にあるAPIをすべて最初から実装することや、Elgato形式全体への互換性を約束するものではない。

外部形式のUUID、context、controller、画像表現は互換アダプタ内に閉じる。
入力認識・機器用Factoryへ拡張の起動や設定を追加せず、ホストを基盤の利用側に置く。
取得済みmanifestやメッセージの検証・変換と、プロセス起動・通信・保存・描画の副作用は分ける。

## 次の検証候補

最初の実物検証は、依存が比較的少ないScreen ControllerのKeypad操作に範囲を絞る案が妥当と考える。
これは順序の提案であり、ノブを黙ってボタンに置き換えたり、拡張全体を対応済みにする判断ではない。

1. 登録、配置の出現、設定の受信・保存とPI表示までを確認する。独自メッセージや起動条件を記録して、不足契約を確定する。
2. 対応画面でボタンの開始・終了から選択した操作の結果までを確認する。別配置の設定と混ざらないこと、終了後に配送が残らないことも確認する。
3. ノブ能力と表示への接続を別に検証し、その後System Monitorの本体・PI・補助サービスとの連携を確認する。

工場出荷設定への復帰やサービスの変更は、登録・設定の確認とは分けて扱う。
この調査ではいずれも実行していない。
Windowsでの通信ログと実機の結果が揃うまでは、「解析上の候補」と「動作確認済み」を区別する。

[system-monitor-product]: https://vsdinside.key123.vip/product/178366994579015?lang=ja
[system-monitor-download]: https://cdn1.key123.vip/marketplace/streamDock/plugin/files/com.hotspot.streamdock.system.monitor.sdPlugin
[screen-controller-product]: https://vsdinside.key123.vip/product/20250925001507?lang=ja
[screen-controller-download]: https://cdn1.key123.vip/marketplace/streamDock/plugin/files/com.mirabox.displaycontrol.sdPlugin
[microsoft-vcp]: https://learn.microsoft.com/en-us/windows/win32/monitor/using-the-low-level-monitor-configuration-functions
