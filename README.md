# TimeSenseApp

スライダーと選択ボタンを使って、感覚評価の時間変化を記録するアプリケーションです。PCでサーバーを起動し、同じネットワーク上のiPad等のブラウザーから回答します。記録したデータからTI・TDS・TCATAの集計用CSVを作成できます。

## ダウンロードと起動

[ダウンロードページ](https://github.com/ren3100-git/TimeSenseApp/releases/latest)のAssetsからmacOS用ZIPをダウンロードし、展開したTimeSenseApp.appをMac本体へコピーして開いてください。配布アプリの実行にPythonのインストールは不要です。

配布アプリはApple Silicon（arm64）用です。Intel Mac、他のmacOS環境、実機のiPadでの動作は独立に検証していません。Appleによる公証は行っていないため、macOSのセキュリティ機能により起動が制限される場合があります。

## 基本的な使い方

1. Macと回答用端末を同じネットワークに接続します。
2. 「Experiment Setup」でスライダーとボタンの名称・数、スライダーの範囲、選択方式を設定し、「Save Settings」で保存します。
3. 「Server」でデータ保存先を確認し、「Start Server」を押します。
4. 表示されたNetwork URLを回答用端末のブラウザーで開きます。「Show QR」からQRコードも表示できます。
5. 回答画面で被験者ID・試料ID・試行番号等を入力し、「Start」で記録を開始します。スライダーやボタンで回答し、「Pause／Resume」で一時停止・再開、「Finish」で終了します。
6. 回答画面の終了・保存表示を確認してから、次の試行へ進んでください。
7. 実験終了後は「Shutdown Server」でサーバーを停止します。

PC側のサーバーが起動していないと、端末から回答を保存できません。通信に失敗した場合は、回答画面を閉じずに接続を確認してください。実験前に短い試行を行い、保存されたCSVを確認してください。

## 評価方式と設定

- TI：スライダーによる強度の時系列記録。
- TDS：同時に1つのボタンを選択する方式。
- TCATA：複数のボタンを選択できる方式。

スライダーの「詳細設定」では目盛りや値と位置の対応を設定できます。採用欄で使用する項目を選択し、ボタンの列数や順序のランダム化も設定できます。

## 保存されるデータ

初期保存先は、利用者のDocuments内のTimeSenseApp_dataです。試行ごとのフォルダに次のファイルを保存します。

- data.csv：経過時間、入力形式、項目ID・名称、値、イベント、サーバー日時。
- meta.txt：被験者ID、試料ID、試行番号、開始・終了日時、評価方式等。

被験者の氏名等を入力する必要はありません。実験データと設定は利用者のPCに保存されます。公開リポジトリと配布アプリに実験データは含めていません。

## 集計用CSVの作成

Launcherの「Stats Export」タブで入力フォルダ・出力先・サンプリング周波数・集計条件を設定し、CSVを作成します。TIの値・平均・標準偏差、TDSの選択内容・選択率、TCATAの選択率を出力できます。出力する項目を選択し、プレビューでグラフを確認できます。

集計CSVは日本語版Excel向けにcp932で出力します。元のdata.csvはUTF-8 BOM付きです。集計の意味や条件が実験計画に適合するかを確認して使用してください。

## ネットワークについて

本アプリには利用者認証機能がありません。同じネットワーク上の端末からアクセスできるため、信頼できるネットワーク内で使用し、インターネットには公開しないでください。接続できない場合は、端末間の通信やファイアウォールの設定を確認してください。

## ソースコードから起動する場合

Python 3.12を使用したmacOS環境で確認しています。リポジトリをダウンロードし、そのフォルダ内で以下を実行します。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python launcher_v7.py
```

テスト：

```bash
python -m unittest discover -s tests -v
```

macOSアプリのビルド：

```bash
python -m PyInstaller --noconfirm --clean TimeSenseApp.spec
```

生成先はdist/TimeSenseApp.appです。ビルド設定ではPythonのビルド情報と共有ライブラリに含まれるホームディレクトリのパスを汎用表記へ置換し、アドホック署名を行います。再配布時には、配布物全体に個人パスや実験データが残っていないことを確認してください。

## 開発・配布および免責事項

本ソフトウェアは個人が開発・配布しています。開発者はApple Developer Programに登録していません。本ソフトウェアは現状のまま提供され、動作、正確性、特定の目的への適合性を保証しません。利用は利用者自身の責任で行ってください。法令上認められる範囲において、開発者は本ソフトウェアの利用または利用不能により生じた損害、データの損失その他の不利益について責任を負いません。

This software is developed and distributed by an individual developer who is not enrolled in the Apple Developer Program. It is provided as is, without warranties regarding its operation, accuracy, or fitness for a particular purpose. Use of the software is at the user’s own risk. To the extent permitted by applicable law, the developer accepts no liability for damages, data loss, or other adverse consequences arising from the use of, or inability to use, the software.
