# 詳細設計と実装

共通する要求は[全体要件](requirements.md)、言語や取得方式から独立した契約は[基本設計](design.md)で管理する。この文書は、今回選んだ具体方式とその検証範囲を管理する。

## C++20基盤への移行計画

基盤の実装言語をC++20とし、Pythonとの連携にはpybind11を使う。パッケージのビルドはscikit-build-coreとCMakeで構成する。
この節は実装前の設計であり、この文書変更だけで移行が完了したものとはしない。
現行mainの単発入力・拡張経路と、PR #8で提案した[ボタン入力の要件](requirements/buttons.md)・[基本設計](design/buttons.md)を引き継ぐ。
以下の「今回の実装範囲」以降は移行前のPython実装を説明し、移行後は同じ責務の実装をこの計画に従って置き換える。

### 移す責務と残す責務

| 責務 | 移行後の実装位置 |
| --- | --- |
| 小さな能力と関連製品の契約 | Python・SDKに依存しないC++の公開header |
| SourceのFIFO、受理・失敗・破棄、Observer通知 | C++。Pythonオブジェクトの所有はbinding境界で管理 |
| 単発入力の解放時認識と、継続するButton・同時押しの状態 | 入力実現側のC++。機器番号やSDKの型は受け取らない |
| Bindingによる選択と、選ばれたActionへのrunの依頼 | C++。入力元やSDKから独立させる |
| CLI、JSONの読込み、操作種別の登録・固有設定の検証 | Pythonの組み立て側 |
| SDKの列挙、接続、初期化、raw入力番号の補正、切断監視 | 既存Pythonアダプタを再利用 |
| Processesによるプロセス生成と、拡張固有の具体処理 | Python。C++の操作契約との橋渡しをbinding境界に置く |

単発入力の暫定規則と、Buttonの継続・終了の契約を混ぜない。短押し・長押しの判定、閾値、タイマーは移行範囲へ追加しない。
画像処理、音量、マクロ、動的コンテキスト、SDK自体のC++版への交換も今回の移行では扱わない。

### 契約の強制範囲

C++では`Read<T>`、`Input<T>`、Observer、Subject、Action、Link、Factoryを小さな純粋仮想関数の契約として定義する。
所有する基底ポインタから安全に解放できるよう、契約に仮想デストラクタを置く。
実装側は実装する契約を明示し、overrideを使う。必須メソッドが残る型は抽象型となり、インスタンスを生成できない。
Readの戻り値はT、Inputの取り出し結果は項目または空とし、音量やSlotへ一般契約を固定しない。
Buttonは`Read<bool>`・`Input<Change>`・Subjectの合成とし、利用側へ必要な能力だけを渡す。

Pythonの公開契約はABCとabstractmethodで表現し、具体実装は明示的に継承する。
必須メソッドが欠けたPython実装の生成は拒否するが、Pythonの引数・戻り値をC++コンパイラが静的に保証するとは扱わない。
pybind11のtrampolineだけでPython側の不足実装の生成禁止が成立するわけでもない。
Pythonとの呼出し・変換はbinding境界の責任とし、C++基盤へPythonの構造的型検査やSDKの実装を持ち込まない。

constメソッドであることや読み取り能力だけを受け取ることは、純粋性の保証ではない。
認識・保持状態の算出とBindingの選択は取得済みの不変値を使い、時計の採取、外部への反映、通知から分ける。
物理入力を解釈する計算をC++へ移しても、所属は入力実現側のままとする。

### 公開能力と非公開の書込み境界

SDKアダプタは物理入力をSlotと押下状態へ適合し、受理した時点を採取してから、非公開の受信側へ渡す。
この受信側はstart・receive・失敗記録・closeを扱い、機器から取得した情報をC++の認識・状態・履歴へ反映する。
現在状態のRead、履歴のInput、通知のSubjectとは別の境界とし、アプリ・拡張へ受信側を渡さない。

Pythonへ返す製品はLinkと公開能力のviewで構成する。同じ接続の状態を共有する所有元は保持し、viewが先に無効な参照になることを防ぐ。
内部のSource、認識器、Panelの実体型はPythonへ登録しない。
組み立て用のprivateなbridgeと、公開する能力のviewは別のbinding型にする。
pybind11が実体型へ自動downcastして、公開能力からreceive・start・失敗書込みなどへ到達できる構成を避ける。
privateな生成経路と公開viewは、同じ未処理入力・失敗・接続世代を参照し、状態やFIFOを二重化しない。

Pythonの任意値やObserver・Actionを保持する場合、その所有と解放はbinding境界で管理する。
nativeのロック中にPythonオブジェクトの参照カウント操作や破棄を行わない。
Sourceに保持する項目の順序・件数・受理結果はC++が管理し、Python側に別の配送待ち行列を作らない。

### ボタン能力の引継ぎ

Buttonの契約と整合条件は[機能別の基本設計](design/buttons.md)に置く。
単発入力を生成する経路と、Buttonを生成する経路は組み立て時に選び、不要な履歴を蓄積しない。
標準CLIの単発入力経路とJSON形式は維持する。

Changeはpressedとatを持つ不変値とする。atはPython側で適合済みの変化を受理した時の
time.monotonicによる秒であり、絶対日時や機器内の発生時刻ではない。
同じ受信で変わる個別Buttonと組合せButtonには同じ時点を渡す。
同じ単位の単調な時計を組み立て時に差し替えられるようにし、時計の取得失敗も全Buttonの取得失敗へつなげる。
配送の遅延を保持時間へ加算しないよう、履歴を取り出す時に時点を採取しない。
replayは待機時間を再現せず、既定時計の差分を元の記録の保持時間とは扱わない。

各Buttonの履歴はSourceを使い、liveの上限は256件、有限replayはmax(1, len(events))とする。
一つの履歴が容量を超えた場合も、接続内の全Buttonの状態と未処理履歴を無効にする。
再接続を所有するアプリは、拡張側の継続処理も新しい接続として開始し直す。

### GIL、ロック、実行thread

C++基盤はworkerを追加せず、既存のSDK reader、切断監視と、利用側の配送threadを使う。
SDKのcallbackは適合と受信までで戻り、Bindingの選択や拡張の実行を進めない。

Pythonオブジェクトの操作とPython関数の呼出しにはGILを保持する。
純nativeの処理はGILを解放して実行できるようにし、nativeのロックを保持したままGIL取得やPythonへの呼出しを待たない。
ロックはC++処理から戻る前に解放し、その後にGILを取得してPython側へ戻る。
短いbinding処理でGILを保持する場合も、同じnativeロックを持つ別経路がGILを待つ循環を作らない。

受信・切断とFIFOへの反映を順序付けた後、すべてのロックを解放してからObserverを呼ぶ。
通知先のsnapshotやPythonが所有する値の後始末も、nativeロックの外で行う。
drainは入力取得・Action・reportとの橋渡し時だけ必要なGILを取得し、待機・native処理と分ける。
closeはSDK thread内から呼ばず、callbackの無効化とthreadの停止を終えてから関連する所有参照を解放する。

### 移行時に維持する外部接続

Windowsで確認済みの通常ボタンrawコードの補正と、SDKの遅延import、openとinitの区別、接続世代の管理を維持する。
SDKのreader・heartbeatの停止、notify=False、停止可能な独自監視もPythonアダプタに残す。
Factory.makeでは未接続の製品を構成し、Link.openの完了後に受理を開始する。
新しいC++基盤へ替わったことを理由に、SDKや機器側の制約を上位のキーコンフィグへ移さない。

現在のWindows実機での確認はPython経路に対する記録であり、C++移行後の実機確認とは分ける。
移行後も同じ通常ボタンの単発経路、切断と終了を確認し、未確認の同時押し・Button経路・macOSを成功扱いしない。

### ビルドと検証の計画

SDK・Pythonを必要としないC++20の単体ビルドを用意し、native ctestでFIFO、認識、Button、Bindingと配送を検証する。
型検査を任意の開発ツールに委ねず、必須契約の未実装、契約にない能力へのアクセス、不適合なoverrideをコンパイル負例で検証する。
負例は意図した診断で失敗した場合だけ成功とし、includeや環境の不備による失敗と区別する。

Python連携ではABCの不足実装拒否、公開viewから内部書込みへ到達しないこと、GILをまたぐ通知・切断・所有を検証する。
既存のconfig、CLI、fake SDK、raw番号補正、実機なしの拡張例も回帰対象にする。
Windows・macOS・LinuxのCIでnative ctest、wheel作成・インストール、editableインストールとpytestを実行する計画とする。
wheelはcheckout外からimportして、SDKや開発ツリーが暗黙に必要になっていないことを確認する。
SDKの機器接続を含まないCI結果を、N4 Pro実機の適合保証へ広げない。

ビルド手順と公開APIの変更は実装PRでコードと合わせて更新する。この設計PRではC++ビルドと移行後pytestの成功を報告しない。
境界の根拠は[pybind11の仮想関数](https://pybind11.readthedocs.io/en/stable/advanced/classes.html)、
[GIL](https://pybind11.readthedocs.io/en/stable/advanced/misc.html#global-interpreter-lock-gil)、
[所有権](https://pybind11.readthedocs.io/en/stable/advanced/smart_ptrs.html)を参照する。

## 今回の実装範囲

Python 3.14で、ボタンの単独入力と同時押しを理想入力へ適合し、不変のキーコンフィグからActionを選んで実行する。
N4 Proへの接続には公式Device SDKを利用し、SDKがBUTTONに分類する入力を受け付ける。通常ボタンの識別子はアダプタ側でraw入力コードに合わせる。
SDKを必要としない再生入力でも、同じ上位の選択と実行を利用する。

操作の実例はアプリ起動とする。[起動の要件](requirements/launch.md)全体を完成させる範囲ではなく、指定した引数列によるプロセス生成だけを実装する。管理者権限、音量操作、記録マクロ、コンテキスト切替、設定画面、機器への表示は今回の実装に含めない。これらの要件と未確定事項は各要件文書に残す。

## 契約の表現

移行前のmainでは、交換する能力をPythonのProtocolで表し、実装クラスの共通基底への継承を要求していない。
これはC++20移行後の契約の強制方式ではない。移行後は上記計画のC++契約とPythonの明示継承へ置き換える。
契約名にはI接頭辞を付けず、メソッド名はsnake_caseにする。
ジェネリック型を含む基本契約は[ports.py](../src/opendeck/ports.py)、理想入力の識別と実行結果は[model.py](../src/opendeck/model.py)で定義する。

Inputの返却型は型引数で定める。理想入力の境界でSlotを返すことは、その境界の具体化であり、Inputの一般契約をSlotやパーセンテージへ固定するものではない。

Factoryは外部入力を実現する関連製品を作り、Actionは受け取らない。makeの時点では機器を開かず、Linkのopenで接続と初期化を行う。機器の設定とキーコンフィグは組み立て側で別々に渡す。

### アプリケーション・拡張への公開面

[基本設計の仮想キー契約](design.md#理想入力とキーコンフィグ)は、既存のSlotで具体化する。
Slotは `NewType("Slot", str)` で識別を区別し、今回の設定では空や重複のない名前を上位が宣言する。
アプリ・拡張へ渡すのは `Input[Slot]` と必要な能力であり、SDKのキー番号や認識状態ではない。
Slotと別の仮想キー型や、機器の番号に依存する固定コード一覧を今回追加しない。

[パッケージルート](../src/opendeck/__init__.py)から、Slot、Chord、Input、Subject、Observer、
Binding、Action、Result、Status、InputErrorを公開する。
これらは既存の型そのもので、別の型や中継オブジェクトで包まない。
import時はmodel・ports・bindingsだけを読み込み、設定処理、入力実装、SDKやOSアダプタを読み込まない。
Inputは引き続き型引数で取得する値を定める汎用契約であり、この公開面でもSlotに固定しない。

入力取得のInputErrorはportsで定義する契約上の例外とし、Sourceも同じ例外を使う。
利用側は具体的なSourceを参照せずに、取得失敗と空を識別できる。
利用手順は[アプリケーション・拡張の実装ガイド](extensions.md)に置く。

## 今回の設定形式

設定ファイルにはJSONを使う。ファイルの読み込みとJSONの解析は組み立て側で行い、読み込み済みの値を[config.py](../src/opendeck/config.py)のparseへ渡す。parseは操作種別から生成処理への対応表を受け、操作を実行・照会せずに設定を検証し、関連オブジェクトを構成する。未知の項目や参照先を勝手に補完しない。

| 項目 | 今回の表現 |
| --- | --- |
| inputs | 機器から独立したSlot名の一覧。空や重複を認めない |
| chords | inputsにある複数Slot名と、成立時に出力する別のSlot名。同じメンバー集合の重複を認めない |
| device.keys | 物理入力識別子の文字列からSlot名への対応。範囲は1から15。複数キーを同じ基底Slotに適合させない |
| actions | 名前から操作定義への対応。kindで登録済みの生成処理を選ぶ |
| bindings | Slot名からactionsにある操作名への対応。未割り当てのSlotを残せる |

actionsのkind以外の項目は、選んだ操作の生成処理が検証する。
標準CLIはlaunchを登録し、`argv` に空でない引数列を指定する。

これら5項目は必須で、利用しないchordsは空の一覧にする。上位のinputs・chords・bindingsと、下位のdevice.keysを同じJSONファイルに保存しても、構成後の責務と参照範囲は分ける。起動後の設定変更と保存画面は実装しない。

実機用の操作例は[buttons.json](../examples/buttons.json)、再生用イベントは[button-events.json](../examples/button-events.json)に置く。再生イベントはkeyとpressedを持つ一覧で、記載順に処理する。時刻や待機時間は扱わない。replayでも設定した操作を実行するので、起動先を利用環境に合わせる。セットアップとCLIの実行手順は[README](../README.md)を参照する。

入力実現側では、共通の純粋関数validate_adaptationで適合設定を検証する。
各物理入力を異なる基底Slotへ対応付け、同時押しの全メンバーが直接適合した基底Slotであることを要求する。
複数の物理入力を同じSlotへ対応付ける定義や、未適合Slotをメンバーに含む定義は接続開始前に拒否する。組合せの出力を別の組合せへ再合成するnested chordは今回の認識方式では実現しない。
この制約は下位実装の適合能力として扱い、上位の理想入力定義を制限する共通要件にはしない。

## 操作の生成と登録

操作の構成境界は[基本設計](design.md#操作の追加と構成)に従う。
[config.py](../src/opendeck/config.py)のBuilderは、`Mapping[str, object]` を受けてActionを返すcallableの型とする。
parseの第2引数は `Mapping[str, Builder]` とし、共通の設定処理は起動操作やOS実装をimportしない。
以前のStart参照を直接渡すPython呼び出しは、`{"launch": LaunchBuilder(target)}` を渡す形へ変更する。既存のJSON設定とCLIの引数は変更しない。

共通処理は操作名、操作定義の構造、空でない文字列のkindと登録の有無を検証する。
選ばれた生成処理にはkindを除いた操作固有の項目だけを、読み取り専用のMappingで渡す。
入力定義、物理キー、Binding、他の操作や汎用の依存オブジェクト一覧は渡さない。
Mapping内のリストなどまで不変にはしないため、生成処理は設定を変更せず、実行に保持する値を自身の契約に従ってコピー・確定する。

生成処理は機能固有の必須項目、未知の項目と値を検証し、不正ならValueErrorを送出する。
共通処理はその例外を原因に保持し、`actions[操作名]` の位置を付けたConfigErrorとして報告する。
それ以外の実装上の例外を設定不備や操作の実行結果へ置き換えない。
未登録のkindを暗黙に補完したり、外部モジュール名として読み込んだりしない。

[launch.py](../src/opendeck/launch.py)のLaunchBuilderはStart参照だけを受け取り、argvの検証と不変の引数列を持つLaunchの構成を担当する。
[cli.py](../src/opendeck/cli.py)で `{"launch": LaunchBuilder(Processes())}` を明示的に登録する。
追加する操作もActionを実装し、その設定を検証する生成処理に必要な対象の能力を渡して、この対応表へ登録する。
設定された各操作は構成時に一度生成し、複数のSlotが同じ操作名を参照した場合は同じActionを共有する。runは入力の発生ごとに呼ぶ。
外部パッケージの自動探索、実行中の登録変更、値を伴う入力の追加は今回実装しない。

登録した独自操作を、既存の再生入力・割り当て・実行へ接続する検証例は[test_extensions.py](../tests/test_extensions.py)に置く。

## キーコンフィグと操作

キーコンフィグはSlotから構成済みActionへの不変の対応関係とする。物理ボタンからSlotへの対応は入力アダプタ側の適合設定であり、キーコンフィグにはSDKの識別子や押下・解放を入れない。

SlotとキーコンフィグからActionを選ぶ処理は純粋関数にする。Actionの参照を返すだけで、その状態を照会せず、runも呼ばない。未割り当ての入力と、実行したActionの成否は別々に記録する。

実行側は選ばれたActionにrunを一回依頼する。入力元、Slot、物理ボタンの状態を渡さない。固定したActionは複数回呼び出せるが、結果は各実行に属する。失敗または結果不明でも自動再実行しない。

アプリ起動のActionは抽象的なStart能力を利用し、具体的なProcesses実装がsubprocess.Popenに引数列を渡す。shell=Falseとし、シェルのコマンド文字列へ組み直さない。今回の完了はプロセスを生成できたことを表し、起動後のアプリの準備完了や終了成功は意味しない。

起動先のstdin、stdout、stderrはすべてDEVNULLへ接続する。CLIの入出力を継承させず、長時間動く起動先のstdioがCLIの出力取得完了を遅らせないようにする。起動先の標準入出力の利用・ログ保存は今回対応しない。GUIの表示先を変更する処理ではない。

## 入力認識の暫定規則

同時押しと単独入力の優先関係は、基本設計で利用者向け動作仕様の確認事項として残っている。実装と再生テストのため、今回は以下を暫定規則とする。要件が確定した扱いにはしない。

- 単独入力と同時押しは解放時に一回成立させる。押下しただけではActionを実行しない。
- 既に保持している入力の重複押下、保持していない入力の解放は無視する。
- 解放した入力を含み、全メンバーが保持され、既存の成立済み組合せに使われていない同時押しを候補とする。
- 候補が複数あれば、メンバー数が最多のものを選ぶ。同数なら定義順を使う。
- 組合せが成立した場合は、そのメンバーを使用済みにする。残るメンバーを後で解放しても単独入力を成立させない。
- 同時押しが成立せず、解放した入力が使用済みでなければ、その単独Slotを成立させる。
- 切断や終了時は、保持・使用済みの認識状態を破棄する。

認識の状態遷移は、前の不変状態、取得済みのイベント、入力定義から、次の状態と成立Slotを返す純粋関数にする。SDKからの取得、現在の認識状態の保持、成立したSlotの配送はアダプタ側の副作用として扱う。純粋な関数でも、物理入力の知識を持つ計算はアダプタ内に置く。

## 未処理入力と通知

SourceはFIFOの未処理入力を保持し、InputとSubjectを別の能力として提供する。初期状態では受理せず、接続開始時にstartで有効にする。live入力では初期の上限を256件とする。通知には値を載せず、Observerのon_changeは処理側の起床を予約するだけとする。通知回数と入力件数を対応させない。

replayは有限のイベントJSON全体を先にメモリへ読み込み、openで認識した入力を提出してから実行側が取り出す。
この取得方式に合わせ、Sourceの容量を `max(1, len(events))` とし、有限記録の件数を理由にlive入力の上限へ抵触させない。
SDKを利用しない認識・割り当て・実行の検証用であり、リアルタイム取得の性能や長期ストリームの挙動を模擬・保証するものではない。

処理側はtakeを繰り返して各入力を一度だけ取り出し、空になるまで順序どおり実行する。Actionを実行するのは処理側であり、SDKのreader threadではない。ロックを保持したままObserverを呼ばない。組み立て時には初回の配送も予約する。

Source内部ではenqueueとrecord_failureが未処理入力・失敗状態を変更し、通知先のsnapshotを返す。notifyはそのsnapshotへロック外で通知する。liveアダプタは接続の世代確認、認識状態の更新、enqueueを自身のロック内で順序付け、すべてのロックを解放してからnotifyする。切断後に遅れて起床しても、takeは現在の待ち行列を読み、破棄済みの入力を再提出しない。

待ち行列が上限へ到達した場合は、その入力を黙って捨てて継続せず、取得経路を失敗として停止する。診断を残し、未処理入力と認識状態を破棄して接続を無効にする。入力元の切断より前にtakeで引き渡した入力は、その切断だけでは取り消さない。

Sourceは失敗を保持し、takeはInputErrorを送出する。単に入力がない状態とは区別する。closeでも失敗情報を消さず、再びstartした時に初期化する。CLIは取得失敗を受けるとfinallyで接続を解放する。

待ち行列は理想入力の未処理分を保持するために置く。責務境界が増えるたびに追加の待ち行列を置かず、今回Action用の配送待ち行列も追加しない。

## コードの配置と利用範囲

| ファイル | 責務 |
| --- | --- |
| [`__init__.py`](../src/opendeck/__init__.py) | アプリ・拡張向け契約の公開 |
| [model.py](../src/opendeck/model.py) | 上位の理想入力と組合せの定義、共通の実行結果 |
| [ports.py](../src/opendeck/ports.py) | 交換する能力、入力取得失敗と関連製品の契約 |
| [bindings.py](../src/opendeck/bindings.py) | 不変のキーコンフィグから操作を選ぶ純粋な処理 |
| [runtime.py](../src/opendeck/runtime.py) | 起床と、未処理入力を選択・実行へ渡す協調 |
| [recognition.py](../src/opendeck/recognition.py) | 入力実現側で使う非公開状態の純粋な遷移と適合能力の検証。割り当て適用側では使わない |
| [source.py](../src/opendeck/source.py) | 未処理入力の保持・消費・到着通知 |
| [launch.py](../src/opendeck/launch.py) | 起動固有の設定検証・操作生成と、Startへの実行依頼 |
| [adapters/process.py](../src/opendeck/adapters/process.py) | OSのプロセス生成へ適合するStart実装 |
| [adapters/streamdock.py](../src/opendeck/adapters/streamdock.py) | SDKへの接続と、SDKのBUTTON入力から理想入力への適合 |
| [adapters/replay.py](../src/opendeck/adapters/replay.py) | 記録済みイベントから同じ理想入力を実現する別のFactory |
| [config.py](../src/opendeck/config.py) | 共通設定の検証、登録された生成処理への委譲、関連オブジェクトの構成 |
| [cli.py](../src/opendeck/cli.py) | 操作の生成処理の登録、CLIでの資源所有・組み立て |

ファイル数を層数とみなさない。recognitionは純粋であっても、実際の押下・解放を扱う入力実現側の処理である。SlotからActionへの選択、Actionの実行にはその状態を持ち込まない。

## CLIの結果表示

入力一回分の処理ごとに、input、status、detailを持つJSONを標準出力へ出す。inputには理想入力のSlot名だけを表示する。statusは、未割り当てのunassignedと、Actionの実行結果であるdone、failed、unknownを区別する。

CLI自身の結果出力はJSONとし、起動先のstdioはDEVNULLへ分ける。ただしSDK内部には標準出力へ直接printする診断があり、live利用時の標準出力全体がJSONだけになることは、この実装では保証しない。

構成・接続・入力取得・解放に失敗した場合は、CLIが標準エラーへ診断を出し、終了コード1にする。操作の結果がfailedまたはunknownの場合も終了コード1を保持し、runをCtrl+Cで終了しても過去の失敗を成功へ置き換えない。実行・開始の失敗と解放の失敗が両方ある場合はExceptionGroupへまとめて両方を報告する。結果に応じた自動再実行は行わない。

## SDKとの接続

SDKは[MiraboxSpace/StreamDock-Device-SDK](https://github.com/MiraboxSpace/StreamDock-Device-SDK)を
`git submodule` として `vendor/streamdock-sdk` へ配置し、
リビジョン `7f0d47fe91033b0883edf29b574a6c74ea9bed00` へ固定する。SDKのファイルは変更しない。

SDKとnative transport libraryは、StreamDockFactory.makeまたはlist_devicesで機器を列挙する時に読み込む。中核処理、再生入力、純粋関数のテストをimportするだけでSDKやDLLを読み込まない。makeは列挙して製品を生成するが機器をopenしない。SDK側はTransportDLLを自分のモジュール位置から探すため、そのディレクトリ構成を保って読み込む。

Windows向け依存のwmi 1.5.1にはdocstring内の不正な`\_`があり、Python 3.14で初回import時にSyntaxWarningが出る。DeviceManagerのimport中だけ、wmi由来のこの警告を限定して抑制する。他の警告やimport失敗は隠さず、SDKと依存パッケージのファイルは変更しない。

SDKのopenがFalseを返す場合は接続失敗として扱う。open後の初期化で例外が出た場合とは区別し、後者も入力を受理できる状態にはしない。makeで生成しただけ、または機器が列挙できただけでは、接続成功としない。

Link.openはcallbackを登録してからSDKをopenし、initの完了後にSourceを開始して入力受理を有効にする。openとinitの途中で届いたイベントは受理しない。初期化に失敗した時もcallbackと接続資源を解放し、元の開始失敗と解放失敗の両方がある場合はExceptionGroupで報告する。

SDKのinitは画面の起床、輝度変更、アイコン消去などを伴う。今回のアダプタが呼ぶ初期化と、その機器への影響を、実機確認の対象にする。

SDKのinitは結果を返さず、内部の個別書き込みがすべて成功したかを集約していない。今回の入力受理の開始条件は、openが成功を返し、initが例外なく復帰したことまでである。機器側の初期化完了と入力取得の適合は実機で確認し、この開始条件だけで基本設計の実機成立条件を満たしたとしない。

SDKのkey callbackではEventType.BUTTONのイベントを受け付ける。取得済み情報を認識処理へ渡し、成立した理想入力をSourceへ追加して戻る。
`TOUCH_POINT`、`KNOB_ROTATE`、`KNOB_PRESS`、`SWIPE`など、BUTTON以外に分類されたイベントは受け付けない。

ユーザーがWindows上のN4 Pro（firmware `V4.N4 Pro E.02.010`）で採取したログでは、
入力パケットのヘッダーは `ACK..OK`、byte9は通常ボタンのrawコード1から10、byte10は押下 `01`・解放 `00` だった（byte位置は0始まり）。
これは通常ボタンの入力番号であり、SDKの画像配置用インデックスではない。

固定SDKの `StreamDockN4Pro.decode_input_event` は画像配置マップを誤って逆引きし、raw1から5をSDKキー11から15へ、
raw6から10を同じ6から10へ変換する。
サンプルの `device.keys` は1・2なので、観測した通常ボタン操作はいずれも設定に一致せず無視された。サンプルの番号は変更せず、入力側で補正する。

アダプタはSDKのraw callbackでパケットを記録し、同じreader thread・同じ接続世代のkey callbackに対応付ける。
対応する通常ボタンのrawコード1から10を、SDKの画像配置由来のキー番号より優先して入力識別子に使う。
認識・配送はkey callbackから一回だけ行い、raw callbackから二重に配送しない。SDKファイルは変更しない。

副画面のrawコード `0x40` から `0x43` と他種別のイベントには通常ボタンの補正を適用せず、従来のSDKデコード・型フィルターを保つ。
raw `0x40` のタッチ入力もSDKキー11になるため、SDKの11を一律に1へ変換すると通常ボタン1と衝突する。
設定可能な識別子1から15は、すべてが同じ押下・解放の通知列を持つ保証ではない。副画面の実際の押下・解放・保持・重複は未確認で、解放などのイベントを合成しない。

機器の取り外しは、停止可能な独自のポーリング処理でtransportの列挙結果を0.5秒間隔で調べる。SDKのDeviceManager.listenは停止条件を持たないループなので利用しない。SDKのreadがNoneを返すことだけでは切断と判定しない。接続管理の同期と古いcallbackを無効にする処理は接続実装内に置く。

終了と切断では入力の受理を停止し、未引き渡し入力と認識状態を破棄してから資源を解放する。SDKのcloseにはnotify=Falseを渡し、取り外した機器への切断通知書き込みを避ける。入力のtakeと切断の順序を同期し、古い接続のcallbackから新しい入力を追加しない。

SDKのheartbeat workerには10秒のsleepがある。SDK.closeの停止指示後に、アダプタが最大10.1秒のjoinを追加し、正常なsleep終了を待てるようにする。終了処理はその待機分だけ長くなり得る。SDK内部の停止flagをアダプタから直接書き換えない。

SDKのreader、heartbeat、独自の監視threadが停止したことを確認できない場合は、正常に解放できた扱いにしない。SDKcallbackのthreadからcloseしない。ただしSDK.closeはtransport.closeの例外を内部でprintして捕捉するため、すべてのthreadが停止しても、native資源の解放がすべて成功したことまでは呼び出し側で確認できない。このSDKの確認能力の限界も実機確認に残す。

取り外しは取得失敗として利用側へ伝え、今回のCLIは資源の解放を試みて終了する。自動再接続は行わず、再開するには製品の選択・組み立てから再実行する。

## SDKソース上の根拠

以下は固定リビジョンの公式ソースで確認した事実と、そこからの実装判断である。実機での通知欠落の有無や同時押し対応を証明するものではない。

| 確認した箇所 | 事実と実装判断 |
| --- | --- |
| [SDK概要](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/docs/readme.en.md#L34-L68) | Python/C++のWindows/macOS対応が記載される。今回の実測済み対応範囲とは分ける |
| [N4 Pro decoder](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/src/StreamDock/Devices/StreamDockN4Pro.py#L129-L164) | 通常キーと副画面入力をBUTTONに分類するが、通常キーの番号に画像配置マップの逆引きを使う。上記の補正はアダプタ内に限定し、副画面の通知列は実機確認に残す |
| [reader](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/src/StreamDock/Devices/StreamDock.py#L499-L538) | reader threadが個別イベントを取得し、key callbackを呼ぶ。上位の実行をcallbackで待たない |
| [openとinit](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/src/StreamDock/Devices/StreamDock.py#L152-L177) | openは失敗時にFalseを返す。initは機器への複数の設定を行う。接続と初期化の成否を分ける |
| [close](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/src/StreamDock/Devices/StreamDock.py#L210-L285) | notify=Falseで切断通知書き込みを抑える。readerとheartbeatを停止・待機するが、transport.closeの例外は内部でprintして捕捉する |
| [heartbeat worker](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/src/StreamDock/Devices/StreamDock.py#L591-L610) | loop内で10秒sleepする。正常な終了の待機に必要な時間として扱う |
| [DeviceManager](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/src/StreamDock/DeviceManager.py) | enumerate、製品別の機器生成、hotplug監視がある。停止制御のためlistenを直接使わない |
| [native transport loader](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/src/StreamDock/Transport/LibUSBHIDAPI.py#L61-L161) | OS・architecture別library名を選び、モジュール直下のTransportDLLからimport時に読み込む |

## 検証の区分

外部依存なしで、入力認識の状態遷移、単独・同時押しの排他、重複イベント、FIFO配送、起床と取り出し、未割り当て、実行結果、切断後の入力無効化を検証する。操作の生成境界は、独自のkindの登録、起動操作との併用、機能固有の設定不備、構成時の副作用がないこと、同じActionの反復実行と失敗・結果不明時の非再実行をSDKなしで検証する。接続のテストにはfake機器を使い、SDKのopen失敗、初期化例外、切断、終了を区別する。

ユーザーのWindows実機ログでは、上記firmwareのN4 Proの接続・初期化と通常ボタンの入力パケット取得を確認している。
補正後の実機ログでは、通常ボタン1の解放からprimaryの認識と起動操作のdone（プロセスIDの返却）、通常ボタン2からsecondaryの認識とunassignedを確認した。これは単独入力からプロセス生成までの確認であり、起動したGUIの準備完了や同時押しの実機動作を確認したものではない。
**macOSでの実機動作も未確認**。再生入力やfake機器のテスト成功を、SDK/native libraryや機器本体の適合確認に置き換えない。

実機では通常キーと副画面入力の識別と通知列の違い、複数保持、押下順と解放順、長押し時の重複、通知欠落、抜き差し、初期化による表示への影響、純正ソフトとの同時利用可否を確認する。失敗時に操作が重複実行されないこと、終了後にreaderや監視が残らないこと、機器を再び開けることも確認する。
