# Stream Dock配布拡張の互換性調査

2026-10-20に指定された2件の配布物をダウンロードし、実行せずに解析した。
比較対象はOpenDeckのmain `9f8f922`。これは互換性の調査記録であり、個別操作を基盤の要件へ追加する文書ではない。
ホストの責務と依存方向は[基本設計案](../design/extensions.md)で管理する。

## 判定

| 対象 | 現行OpenDeck | Windowsでの再利用の見通し | 同じ配布物のmacOS利用 |
| --- | --- | --- | --- |
| System Monitor | 外部拡張ホストがないため利用不可 | 互換ホストの候補。設定画面、画像・タイトルの反映に加え、補助サービスとの連携を検証する必要がある | Windows実行ファイルのみ。Mac入口の実体がなく、そのままネイティブ実行できない |
| Windows Screen Controller | 外部拡張ホストがないため利用不可 | ボタン用操作を初回検証の候補にできる。全操作にはノブ能力も必要。画面側の対応条件が残る | Windows実行ファイルのみ。Mac入口の実体がなく、そのままネイティブ実行できない |

両者とも、既存の実行ファイルを別プロセスとして動かし、公開された通信形式の相手側を実装する方針を検討できる。
実行ファイルを読み込んでActionへ変換するだけでは成立しない。起動、登録、配置、設定画面、入力と表示の往復を扱う相手が必要になる。
Windowsでの起動・登録・操作成功はまだ確認しておらず、互換性を保証する判定ではない。

ホストと基盤をマルチプラットフォームにしても、拡張自身のWindows依存は解消しない。
macOSでは、対応する実行コードを入手するか、拡張側の機能を別実装する必要がある。

## 取得した配布物

取得元の製品ページから、公開APIが返すCDNの配布URLを確認した。取得したファイルはいずれも拡張子が`.sdPlugin`のZIPだった。
配布URLは版番号を含まないため、以下のSHA-256で今回の入力を識別する。

| 項目 | System Monitor | Windows Screen Controller |
| --- | --- | --- |
| 製品ページ | [178366994579015](https://vsdinside.key123.vip/product/178366994579015?lang=ja) | [20250925001507](https://vsdinside.key123.vip/product/20250925001507?lang=ja) |
| 配布ファイル | [com.hotspot.streamdock.system.monitor.sdPlugin](https://cdn1.key123.vip/marketplace/streamDock/plugin/files/com.hotspot.streamdock.system.monitor.sdPlugin) | [com.mirabox.displaycontrol.sdPlugin](https://cdn1.key123.vip/marketplace/streamDock/plugin/files/com.mirabox.displaycontrol.sdPlugin) |
| 実取得サイズ | 35,688,835 bytes | 473,601 bytes |
| ストア表示/APIの版 | `1.6.260814` | `1.0.260826` |
| manifestの版 | `1.6.260814` | `1.1.260826` |
| SDKVersion | `1` | `1` |
| manifestの対応OS | Windows 7以上 | Windows 10以上 |
| manifestの必要ホスト版 | `2.9.121` | `2.9` |

SHA-256:

- System Monitor: `6639b602c17d734fb66286a72e5088ebd0a00891399272316865e59f1a3e5835`
- Windows Screen Controller: `301a7fb8cc332ecd5e5ab73affa6f9495d58765030078a0b2535c040b6975333`

Screen Controllerはストアとmanifestの版が一致しない。版表示だけで同一の内容だと判断しない。
必要ホスト版は配布元ソフトに対する宣言であり、OpenDeckの版や対応済みAPIを意味しない。

ZIPのパス、重複、シンボリックリンクを確認して展開し、manifest、HTML/JavaScript、PEヘッダー、import table、文字列と一部の機械語の参照・呼出経路を調べた。
パッケージのコード、設定画面、実行ファイル、インストーラーは一切実行していない。サービスやドライバーの導入もしていない。
配布物そのものはこのリポジトリへ転載しない。以下の証拠位置は各パッケージ直下を基準とする。

## System Monitor

### 構成とOS依存

`manifest.json`には14操作があり、CPU、メモリ、ディスク、ネットワーク、GPU、センサーの表示とサービス保守を含む。
全操作のControllersは`Keypad`、`Information`、`SecondaryScreen`。
`CodePathWin`は`SystemMonitor.exe`で、実体はWindows x64のPE実行ファイルだった。
`CodePathMac`は`SystemMonitor`だが該当ファイルはなく、OS宣言もWindowsのみ。

本体はQt5Widgets、Qt5Gui、Qt5WebSockets、Qt5Network、Qt5Core、Windows API、MSVC runtimeをimportする。
QtとruntimeのDLL、`platforms/qwindows.dll`などが同梱される。
補助EXEの`get_info.exe`、`hwinfo/HWInfoSever.exe`、`hwinfo/SystemMonitorLib1.dll`、`hwinfo/SystemMonitor64.dll`も含む。
DLLの同梱だけで全依存が充足するとは判断しない。

### 確認できた通信と動作経路

| 根拠 | 静的に確認した内容 | 互換ホストで扱う点 |
| --- | --- | --- |
| `PropertyInspector/js/action.js:783-791,849-890` | PIがホスト情報と操作情報を受け、渡されたポートのloopback WebSocketへ接続し、eventとuuidで登録する | HTML/JavaScriptの実行環境、起動情報と登録 |
| `PropertyInspector/js/index.js:209,229,239-278,319-321,436,457`ほか | 設定保存、`sendToPlugin`、`openUrl`の呼出がある | 配置ごとの設定、PIと本体間のJSON中継、外部URLを開く依頼 |
| `PropertyInspector/js/custom_system_monitor.js:25-140,153-210` | センサー一覧を要求し、PIへの応答から分類と項目を選ぶ | 独自payloadを基盤の共通型にせず往復させる |
| `PropertyInspector/js/serviceMaintenance.js:90-134` | 接続時に`maintenanceOperation: status`を送り、明示操作でinstall/update/uninstall/resetを送る | PIとの双方向通信。設定画面を表示することと保守操作の実行を区別する |
| `SystemMonitor.exe`の機械語 | `setImage`、`setTitle`、`setState`、`sendToPropertyInspector`のJSON構築関数に呼出元がある | 拡張が作った表示内容とPI応答を対応する宛先へ反映する |
| 同本体の別接続経路 | `ws://localhost:15500`を構成して`QWebSocket::open`へ渡す呼出経路がある | ホストへの接続とは別に補助側との通信がある。ホストのWS接続だけで完結しない |
| 同本体の保守分岐 | uninstallとの比較から、`runas`と`--uninstall`を構成し`ShellExecuteExW`を呼ぶ経路がある | 実行ファイルにはWindowsのサービス保守に関わる処理がある |

本体の表示系JSON構築関数の開始VAは、setImageが`0x140029760`、setTitleが`0x140029d50`、setStateが`0x140029b30`、sendToPropertyInspectorが`0x140029540`。
別接続はVA `0x1400023c1`から`0x14001a500`へ、そこでQtのopenへ渡る。
保守処理はVA `0x14000555e`付近の`maintenanceOperation`処理、`0x1400057cf`付近のuninstall比較から`0x14001e0d0`の処理を経て、`0x14001e2d2`のShellExecuteExW呼出へ続く。
これらは上記ハッシュの実行ファイルに対する静的な位置であり、実行したログではない。

表示内容の生成とセンサー取得は拡張側の仕事になる。ホストは表示先と描画能力へ接続する。
ボタンを押していない間にも拡張が稼働し、表示を更新できる経路が必要で、単発のAction呼出だけではこの利用を表せない。
更新の頻度、補助サービスの起動・共存、保守時の権限要求と成功条件、センサー取得の成否は実行確認に残る。
一部の保守経路があることを、全保守操作の成功や全表示APIの利用条件が確定したことへ広げない。

GPU温度の`PropertyInspectorPath`だけはWindowsのバックスラッシュ区切りだった。
パッケージ内資源の解決は外部形式への適合側で扱い、この表記を基盤の共通パス規則にしない。

## Windows Screen Controller

### 構成とOS依存

`CodePath`と`CodePathWin`は`bin/displayControl.exe`で、実体はWindows x64のPE実行ファイルだった。
`CodePathMac`の`bin/displayControl`は存在しない。実行本体のソースは同梱されず、PIのHTML/JavaScriptは読める。
本体はMSVCP140、VCRUNTIME140、VCRUNTIME140_1、Windows CRTなどをimportし、パッケージにDLLは同梱されない。

| manifestの操作 | Controllers | 操作の内容 |
| --- | --- | --- |
| `action1`、`action3` | `Knob` | 輝度・コントラストの調整 |
| `action2`、`action4` | `Keypad` | 輝度・コントラストの設定 |
| `action5`、`action6`、`action7` | `Keypad` | 電源、入力ソース、工場出荷設定への復帰 |

これらは当該拡張の内容であり、OpenDeck基盤の操作一覧ではない。
ノブに対応せず全7操作が利用可能だと表示するのは誤りになる。

### 確認できた通信と依存

| 根拠 | 静的に確認した内容 | 判断の範囲 |
| --- | --- | --- |
| `static/action.js:72-76` | PIが渡されたポートのloopback WebSocketへ接続し、eventとuuidで登録する | 公式PI登録形式との一致 |
| `static/action.js:63-69,79-94`、各`actionN/index.js` | 7画面の有効なWebSocket helper呼出16箇所はすべて`saveData`。`setSettings`を送り、`didReceiveSettings`を受ける | 設定往復の実callsite。送信contextはこのコードではPIの`$uuid`を使うため、配置との対応をホスト側で解決する必要がある |
| `static/action.js:99-105` | `application.language`に応じて相対位置の言語JSONを読む | ホスト情報とローカル資源の読込み |
| `action6/index.js:37-79,84-106` | 選択中の画面と対応入力ソース一覧から設定画面を構成する | 画面と機能の対応情報が必要。固定した選択肢だけでは足りない |
| `bin/displayControl.exe`のimport table | dxva2の物理モニター列挙、`GetVCPFeatureAndVCPFeatureReply`、`SetVCPFeature`、capabilities取得と、USER32のモニター列挙をimportする | Windowsのモニター制御APIへの依存がある |
| 同本体の文字列 | loopback WS、登録引数、`dialRotate`、`ticks`、`pressed`、画像data URLなどがある | 実行時の使用・必須性・完全な通信順序を文字列だけでは確定しない |

`static/action.js`にはsendToPlugin、setImage、setState、openUrlの定義もあるが、各操作のPIからそれらへの呼出は見つからなかった。
SDK helperの定義だけを、この対象が必要とするAPIの証拠にはしない。本体側が別途使うAPIは実行時の確認に残る。

importにあるVCP操作は、[Microsoftの説明](https://learn.microsoft.com/en-us/windows/win32/monitor/using-the-low-level-monitor-configuration-functions)ではDDC/CIと画面ごとのcapabilitiesを扱う。
このパッケージでも画面側の対応機能が成立条件になると考えられるが、内蔵画面、接続経路、複数画面、各操作の成否は未確認。
互換ホストが登録を受け付けることと、接続した画面で操作が成功することを分けて確認する。

## 現行基盤との対応と不足

| 必要な境界 | 現行OpenDeckとの関係 | 次に確認・具体化する内容 |
| --- | --- | --- |
| 実行形式への適合 | 標準CLIはlaunchを固定登録しており、外部ホストは未実装 | manifestの読込み、実行条件、プロセスの起動・登録・終了、WSの相手側 |
| 拡張と配置の識別 | Bindingは入力からActionを選択する。外部contextの管理はない | 一つの拡張の稼働と、複数配置の寿命・設定・表示先を区別する |
| 入力 | Buttonの開始・終了と保持状態は利用可能。成立済みの`Input[Slot]`だけでは押下・解放列を復元できない | Buttonの履歴から外部イベントへ適合する。ノブは別能力として設計する |
| 設定とPI | 外部PIの実行環境、設定の保持・通知・中継は未実装 | 拡張全体と配置ごとの設定、PI識別子との対応、HTML資源とJSON往復 |
| 表示 | 公開された描画能力と機器への出力接続は未実装 | 渡された画像・タイトル・状態と表示先を接続する。内容は拡張が生成する |
| 拡張固有の依存 | WindowsのサービスやモニターAPIは基盤の責務に含めない | 拡張側の実行条件として扱い、未充足や実行失敗を区別する |

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
この調査ではいずれも実行していない。Windowsでの通信ログと実機の結果が揃うまでは、「解析上の候補」と「動作確認済み」を区別する。
