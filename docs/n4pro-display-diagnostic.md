# N4 Pro 表示・入力の実機診断

PR #24 の公開 API を使う手動診断。表示と入力の対応は実測する。実行中は画像が置き換わり、終了後の表示復元は保証しない。起動ロゴやファームウェアは変更しない。操作にアプリを割り当てない。

## 準備と起動

- Windows ネイティブ環境、N4 Pro 1 台。純正ソフトなど機器を使用するアプリを終了する。
- [README のセットアップ](../README.md#セットアップ)に従い、固定 SDK の submodule とデバイス用依存を準備する。
  `make_buttons` や通常の OpenDeck アプリは同時に動かさない。
- 対象 checkout のルートで PowerShell を開く。複数台なら原則 1 台にする。
  複数台で実行する場合のみ、列挙順を確認し `--device-index 0` のように指定する。番号は固定の機器 ID ではない。

```powershell
mise exec -- uv run python tools/n4pro_display_diagnostic.py
```

実行するたびに `logs/diagnostics/n4pro-diagnostic-日時.jsonl` が作られる。
保存先のディレクトリがなければ作成し、既存ファイルは上書きしない。
保存先を指定する場合は `--output .\result.jsonl` を付ける。
`Ctrl+C` で中断でき、それまでの記録は残る。エラーが出た場合も JSONL と画面のエラーを保存する。

入力だけを確認する場合は `--step` で工程を指定する。画像送信の案内を省き、
選んだ操作だけを記録する。複数回指定した場合は指定順に実行する。
`--seconds` で各工程の記録時間を変更できる。既定は5秒で、有限の正数を指定する。

```powershell
mise exec -- uv run python tools/n4pro_display_diagnostic.py --step touch_center --seconds 2
mise exec -- uv run python tools/n4pro_display_diagnostic.py --step button_3 --step swipe_left
```

工程名は `touch_top_left` / `touch_top_right` / `touch_center` /
`touch_bottom_left` / `touch_bottom_right`、`swipe_left` / `swipe_right`、
`button_1` 〜 `button_10`。`--help` でも確認できる。
機器の接続・SDK初期化は行うため、入力だけの診断でも初期化による画面変更は起こり得る。

### タッチ・副画面・ノブの追加観測

次の工程は `--step` で指定した場合に実行する。
番号は利用者が正面から見て左から数えた観測位置であり、SDKの番号との対応は採取結果で確認する。

| 工程名 | 操作 |
| --- | --- |
| `secondary_1` 〜 `secondary_4` | 副画面の左から指定した領域の中央に触れ、離す |
| `touch_hold` | 中央に1本の指で触れ、記録終了まで保持する |
| `touch_drag` | 左上から右下へ指を離さずなぞる |
| `touch_two_fingers` | 中央付近に2本の指で同時に触れ、離す |
| `knob_N_press_release` | 左からN番目のノブを押して離す |
| `knob_N_left` / `knob_N_right` | 押さずに反時計回り / 時計回りへ1目盛り回す |
| `knob_N_held_left` / `knob_N_held_right` | Enter前に押したまま準備し、開始後に同じ方向へ1目盛り回し、記録終了まで押し続ける |

ノブのNは1〜4。押下・解放を採取する工程と、押したまま回す工程を分けて実行できる。

```powershell
mise exec -- uv run python tools/n4pro_display_diagnostic.py --step knob_1_press_release
mise exec -- uv run python tools/n4pro_display_diagnostic.py --step knob_1_held_left
mise exec -- uv run python tools/n4pro_display_diagnostic.py --step secondary_2 --step touch_drag
```

固定SDKのdecoderにはノブの押下状態、ノブIDと回転方向、副画面の解放側通知がある。
回転のtick数、押しながら回転する専用通知、タッチの開始・終了・複数指の区別は未確認。
rawだけ届いた場合も保存し、公開 `button` / `touch` がなかった事実と合わせて確認する。
実機の押下・解放・回転の対応や副画面の単発Action成立は未確認のまま記録する。
[固定SDKのN4 Pro decoder](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDockN4Pro.py#L135-L203)

### 背景と個別画像の更新順の観測

`--image-order` は画像更新だけを行うモード。各工程の表示を目視・撮影してからEnterで次へ進む。
`background-images-background` は背景 → 通常ボタンと副画面の全個別画像 → 背景、
`images-background` は全個別画像 → 背景の順に、既存の公開Viewを呼ぶ。
背景のラベルは工程に応じて `BG1` / `BG2` / `BG3` となる。

```powershell
mise exec -- uv run python tools/n4pro_display_diagnostic.py --image-order background-images-background
mise exec -- uv run python tools/n4pro_display_diagnostic.py --image-order images-background
```

各工程を `image_phase_start` / `image_phase_end` の `phase` と `operation` で記録し、
その間の `image_sent` / `image_failed` を照合する。`session.image_order` に選択した順序を保存する。
`image_phase_end` はAPIが戻った工程の区切りで、表示完了は写真と目視で確認する。
`--step` と `--image-order` は一方を選択する。指定がなければ既存の表示・入力手順を実行する。
部分フレーム・レイヤー、ACK、重なり・保持の保証範囲は未確認。
画面領域、向き、上書きと保持、更新頻度・遅延の実機結果はIssue #38に残る。

## 確認手順

1. 最初の Enter で背景 `BG` を送る。目視・撮影してから次へ進む。送信の正常終了は描画完了を意味しない。
   変化がなければ 10 秒程度観察する。これは観察の目安であり SDK の保証ではない。
2. 次の Enter で通常ボタン向け D1〜D10、副画面向け D11〜D14 を送る。
   各ラベルの位置、見切れ、向き、色が分かるように撮影する。左上は赤、右上は緑、外周は白枠、背景は格子。
   画像は PNG で通常 112 x 112、副画面 176 x 112、背景 800 x 480。サイズはタッチ座標範囲を表さない。
3. 画面の指示ごとに Enter を押し、`開始` が表示されてから 5 秒以内に示された操作を行う。
   タッチ 5 位置、左右スワイプ、通常ボタン 10 個の順。ボタンは左上から右へ、次の段も左から順に押す。
   1 回の操作で複数座標が届く場合もそのまま保存する。
4. 全操作が終わると終了する。途中でも Ctrl+C で終了できる。JSONL と写真を一緒に保管する。画像の位置や向きは写真から確認する。プログラムは画面の実際の見た目を取得できない。

JSONL は 1 行が 1 レコードで、現在の `schema_version` は2。
各行の `time` は書き出し時の壁時計、`monotonic_ns` は同じプロセスの単調時計による書き出し時刻。
`session` に OS、Python、Git リビジョン、SDK リビジョン、device index、選択工程と記録秒数を保存する。
取得できないリビジョンは `null`。
SDK初期化後の `device` にクラス名、serial、VID/PID、取得したfirmware値を保存する。
これはSDKが返した情報であり、機器の能力やファームウェアの互換性を判定した結果ではない。
`image_sent` は描画 API の正常復帰、`image_failed` は描画 API が例外で失敗したことを示す。
どちらも描画先 `target`、画像の `label`、`draw()` 呼出しの所要時間 `elapsed_ms` を記録する。
例外の詳細は終了時の `error` に記録する。`elapsed_ms` に画像の生成時間は含まない。
実機の描画完了は画面を観察して確認する。

`step_start` / `step_end` は操作の区切り、
`button` / `touch` / `swipe` は実際に取得した入力、
`error` / `stopped` / `finished` は終了状況を示す。
`finished` は手順完了であり、実機の表示・入力の成功を意味しない。
操作時間外に保留されていた入力の `step` は `null` とし、次の操作に割り当てない。
入力レコードの `time` は、キューから取り出した入力を JSONL に書き出した時刻。
`sdk_raw` / `sdk_decoded` / `sdk_touch` はSDK callback側の観測記録。
`received_monotonic_ns` はadapter callbackに入った時点の単調時計、
`observation_sequence` はこの診断のlogging handlerが処理した順序を示す。
`sdk_raw.raw` は受信bytes全体の16進表現、`sdk_decoded.decoded` はSDKイベントの表現。
同じ `generation` と `packet_id` によりrawと、その直後に同じreaderで通知されたdecodedを照合する。
rawのないdecodedと、対応するrawを確認できない別経路のtouchは `packet_id: null` とする。
固定SDKはraw callbackの後にdecode/key callbackを同じreaderで同期実行し、UNKNOWNにはkey callbackを行わない。
そのためrawだけの記録も残る。[固定SDKのreader](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/fc124cb5bc8fe0cd6c72d3f2af80588adc7dcffb/Python-SDK/src/StreamDock/Devices/StreamDock.py#L561-L655)

工程IDは `step_start` / `step_end` の `step` に記録する。
callbackの工程を調べる場合は `received_monotonic_ns` を工程の `monotonic_ns` 区間と照合する。
キューからの取得記録とcallback記録は異なる観測地点で、個々の公開入力にraw IDは追加していない。
機器内部での発生時刻と、押下・回転を横断する順序は、この診断からは確定できない。
未操作、無反応、中断を成功と判定しない。
callbackの診断記録も同期で書き込むため、記録処理自体の負荷を含んだ実行となる。
callback中の書込み障害は保持し、機器のcallbackが戻った後、診断の所有threadの終了時に例外で報告する。
その場合は記録に欠損がある。手順完了の表示に加え、終了コードと標準エラーも確認する。
JSONL にはserial、raw、エラー内容も含まれるため、共有前に内容を確認する。

画像描画先の指定は公開 API の引数で、SDK の画像スロット番号ではない。
実装上の変換は表示先 1〜5 → SDK 11〜15、6〜10 → SDK 6〜10、11〜14 → SDK 1〜4。
表示先 11〜14 が実際にどの副画面領域へ現れるかは観測する。

## 判定と記録

| 観点 | 期待する観察 | 失敗・未確認 |
| --- | --- | --- |
| 背景 | BG、格子、赤・緑の目印が画面に現れる | 例外・未表示・異なる表示。API の正常終了だけでは未確認 |
| 通常ボタン | D1〜D10 が各 1 箇所に読める向きで表示される | 欠落、重複、切れ、向き・色の異常。位置は実測して記録 |
| 副画面 | D11〜D14 がそれぞれ別領域に表示される | 欠落、重複、切れ、向き・色の異常 |
| タッチ | 操作した位置に対して座標が記録される | 無反応・明らかな欠落。座標の範囲や向きは実測し、想定と違うだけでは API 違反と断定しない |
| スワイプ | 左右でそれぞれ `Swipe` と方向が記録される | 無反応、逆方向、異なるイベント |
| ボタン入力 | 個々の押下で `input-N` を記録できる | 無反応、別の位置と区別できない。表示先の番号との一致は要求しない |

JSONL の操作名と入力を照合し、画面の写真とともに判定する。
`display-N` と `input-N` は独立した番号である。画面の写真は JSONL に自動では含まれない。

## 既存テストと実機確認の境界

PR #24 は fake transport と固定 SDK で描画先変換、画像変換、イベントの受け渡しを検証済み。
fake の成功は実機の画像位置、表示形式、座標と画面位置の対応、左右スワイプ、描画完了を保証しない。
今回の fixture が出力した送信ログも実機の成功を証明しない。実機で観測・記録するまで各項目は未確認とする。

Issue #42では、個別の入力工程、callback受信時刻・raw対応、SDKから取得可能な機器情報を追加した。
画像要求は `image_sent` / `image_failed` と所要時間で確認する。
切断・キューあふれ等の入力失敗は公開入力から伝播する `error` の型、message、tracebackで確認し、
callback記録が存在することを公開入力への配送成功と扱わない。
[LEDの個別診断](n4pro-led-diagnostic.md)では、指定した4色の要求、SDKの結果、所要時間を記録する。
公開LED能力の契約と実機確認はIssue #39に残る。
今回の自動テストはfakeの観測地点・対応付けを確認しており、新規のN4 Pro実機観測は行っていない。
