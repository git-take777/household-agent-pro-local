# 家計Pro

ローカルで動く家計簿 Web アプリケーションです。Python + Flask で動作し、支出・収入の管理、レシート画像の OCR 読み取り、統計分析、Excel レポート出力ができます。

ミッション: **手軽に効率よく計算し、節約・費用対効果の算出で無駄な消費を防ぐ**

---

## セットアップ

### 必要なもの

- Python 3.10 以上
- pip（Python パッケージマネージャ）
- Tesseract OCR（レシート読み取り機能を使う場合）

### 1. パッケージのインストール

```bash
cd /path/to/HouseholdFinanceProAgent
pip3 install -r requirements.txt
```

`requirements.txt` の中身:

```
openpyxl>=3.1.0
pandas>=2.0.0
numpy>=1.24.0
flask>=3.0.0
Pillow>=10.0.0
pytesseract>=0.3.10
```

### 2. Tesseract OCR のインストール（任意）

レシート画像から自動で店舗名・金額・日付を読み取る機能を使う場合に必要です。インストールしなくても他の全機能は動作します。

**macOS（Homebrew）:**

```bash
brew install tesseract
brew install tesseract-lang   # 日本語 OCR を有効にする
```

**Ubuntu / Debian:**

```bash
sudo apt install tesseract-ocr tesseract-ocr-jpn
```

### 3. サーバーの起動

```bash
cd /path/to/HouseholdFinanceProAgent
python3 web_app.py
```

起動すると以下のように表示されます:

```
==================================================
  家計Pro Web - http://localhost:8080
  停止: Ctrl+C
==================================================
```

ブラウザで **http://localhost:8080** を開いてください。

停止するときはターミナルで `Ctrl + C` を押します。

#### 起動スクリプトを使う場合（macOS）

パッケージや Tesseract の有無を自動チェックして起動するスクリプトも用意しています:

```bash
chmod +x start_server.sh
./start_server.sh
```

---

## 画面の使い方

### ダッシュボード（トップページ）

`http://localhost:8080/`

- 今月の **総収入・総支出・収支・貯蓄率** を一目で確認できます
- **カテゴリ別支出** テーブル（固定費=緑、変動費=オレンジ、特別費=紫で色分け）
- **分類別合計**（固定費・変動費・特別費）
- **費用対効果スコア** と節約ポイント
- **月次トレンド** 棒グラフ（過去 6 ヶ月の支出推移）
- ヘッダーの「前月 / 翌月」ボタンで月を切り替えられます

### 支出一覧

`http://localhost:8080/expenses`

- 月ごとの全支出をリスト表示
- 各行の「削除」ボタンで支出を個別に削除可能
- 合計金額と件数を下部に表示

### 支出追加

`http://localhost:8080/add`

1. **日付** を選択（デフォルトは今日）
2. **カテゴリ** をドロップダウンから選択（固定費/変動費/特別費のグループ付き）
3. **金額（円）** を入力
4. **メモ** を入力（任意）
5. 「追加する」ボタンをクリック

カテゴリは 21 種類あります:

| 固定費 | 変動費 | 特別費 |
|--------|--------|--------|
| 住居費、光熱費、通信費、保険料、教育費、車両費、サブスク | 食費、日用品、交通費、衣服費、医療費、娯楽費、交際費、美容費 | 冠婚葬祭、家電購入、税金、その他 |

### 収入追加

`http://localhost:8080/add-income`

- 給与、副業、投資、年金、その他収入の 5 カテゴリ
- 操作方法は支出追加と同じです

### レシート読み取り（OCR）

`http://localhost:8080/receipt`

1. 「クリックまたはドラッグ&ドロップ」エリアにレシート画像をアップロード
2. 対応形式: **JPEG (.jpg, .jpeg)** と **PNG (.png)**
3. アップロードすると自動で以下が行われます:
   - **画像圧縮**: 長辺 1600px 以下にリサイズ、JPEG は目標 500KB 以下に品質調整、EXIF 回転自動補正
   - **OCR 解析**: Tesseract で画像からテキストを抽出し、以下を自動推定:
     - **店舗名**: セブンイレブン、ローソン、イオン、マクドナルドなど 50 以上の店舗に対応
     - **日付**: `YYYY/MM/DD`、`YYYY-MM-DD`、`R8/02/11`（令和）形式に対応
     - **合計金額**: 「合計」「小計」「税込」キーワード付近の金額を検出
     - **カテゴリ**: 店舗名やキーワードから自動推定（食費、日用品、交通費など）
     - **決済方法**: 現金、クレジット、PayPay、Suica などを検出
4. 読み取り結果を確認・修正して「この内容で支出登録する」をクリック

**Tesseract 未インストールの場合**: 画像の圧縮・保存は行われ、手動入力フォームが表示されます。エラーメッセージで Tesseract のインストール方法も案内されます。

### 予算管理

`http://localhost:8080/budget`

- **予算 vs 実績** テーブル: 各カテゴリの予算・実績・差額・達成率・進捗バーを一覧表示
- 状態ラベル: 「適正」「超過」「大幅超過」「余裕あり」
- 下部の **予算設定フォーム** で各カテゴリの月間予算を変更可能

### 分析

`http://localhost:8080/analysis`

- **効率スコア**: 支出全体の費用対効果（必要度で加重）
- **節約可能額**: 必要度が低く高額な支出カテゴリの削減見込み額
- **無駄な支出の検出**: 必要度スコア 4 以下かつ 10,000 円超のカテゴリを抽出し、改善提案を表示
- **異常値検出**: 過去 6 ヶ月の平均から Z-score 1.5σ 以上の統計的に異常な支出を検出

### Excel レポート出力

`http://localhost:8080/report`

ボタンをクリックすると 7 シート構成の `.xlsx` ファイルをプロジェクトフォルダに生成します:

| シート名 | 内容 |
|----------|------|
| ダッシュボード | 月次概要 + 円グラフ（支出構成比） |
| 支出明細 | フィルタ付き全支出リスト + SUM 数式 |
| 収入明細 | 収入一覧 + 合計数式 |
| 予算 vs 実績 | 棒グラフ付き予算比較 |
| 月次トレンド | 折れ線グラフ + カテゴリ別推移マトリックス |
| 費用対効果 | 無駄検出テーブル + コスパ指数マトリックス |
| 異常値検出 | Z-score 基準の異常支出レポート |

---

## CLI（コマンドライン）での使い方

Web UI の代わりにターミナルから直接操作することもできます。

```bash
python3 kakeibo_pro.py add                          # 支出を対話的に追加
python3 kakeibo_pro.py add-income                    # 収入を対話的に追加
python3 kakeibo_pro.py report                        # 今月のExcelレポート生成
python3 kakeibo_pro.py report 2026 1                 # 指定月のレポート生成
python3 kakeibo_pro.py summary                       # 今月のサマリー表示
python3 kakeibo_pro.py list                          # 今月の支出一覧
python3 kakeibo_pro.py budget                        # 予算設定
python3 kakeibo_pro.py delete <id>                   # 支出を削除
python3 kakeibo_pro.py receipt <画像パス>             # レシートOCR
python3 kakeibo_pro.py import-csv <サービス> <CSV>    # Pay履歴インポート
python3 kakeibo_pro.py pay-services                  # 対応決済サービス一覧
```

---

## Pay 決済履歴の CSV インポート

以下のキャッシュレス決済サービスの利用履歴 CSV を取り込めます:

- **PayPay**: PayPay アプリ → 取引履歴 → CSV エクスポート
- **LINE Pay**: LINE Pay → 利用履歴 → CSV ダウンロード
- **楽天ペイ**: 楽天ペイ → 利用明細 → CSV ダウンロード

CSV のエンコーディングは UTF-8 / Shift_JIS / CP932 / EUC-JP を自動検出します。

```bash
python3 kakeibo_pro.py import-csv paypay ~/Downloads/paypay_history.csv
python3 kakeibo_pro.py import-csv linepay ~/Downloads/linepay.csv
python3 kakeibo_pro.py import-csv rakuten ~/Downloads/rakuten.csv
```

---

## プロジェクト構成

```
HouseholdFinanceProAgent/
├── web_app.py           # Flask Webアプリケーション（メイン）
├── kakeibo_pro.py       # CLIインターフェース
├── config.py            # カテゴリ・予算・スコア定義
├── data_manager.py      # CRUD操作 + JSONデータ永続化
├── analyzer.py          # 統計分析エンジン
├── excel_reporter.py    # Excelレポート生成
├── receipt_scanner.py   # レシートOCRスキャナー
├── pay_integration.py   # Pay決済CSV取込
├── test_kakeibo.py      # テストスイート（25テスト）
├── requirements.txt     # 依存パッケージ
├── start_server.sh      # サーバー起動スクリプト
├── setup_and_push.sh    # Git push用スクリプト
├── data/                # JSONデータ保存先（自動生成）
│   ├── expenses.json
│   ├── incomes.json
│   └── budgets.json
└── uploads/             # レシート画像保存先（自動生成）
```

---

## テストの実行

```bash
python3 -m pytest test_kakeibo.py -v
```

4 モジュール・25 テストケース:

- TestConfig（5）: カテゴリ一覧、グループ分類、スコアカバレッジ
- TestDataManager（11）: CRUD 操作、バリデーション、日付検証
- TestAnalyzer（4）: 月次サマリー、予算比較、費用対効果
- TestReceiptScanner（4）: パース、令和日付、カテゴリ推定

---

## トラブルシューティング

### `localhost へのアクセスが拒否されました (HTTP 403)`

macOS Monterey 以降、ポート 5000 は AirPlay Receiver が占有しています。本アプリはポート **8080** を使用するため、`http://localhost:8080` にアクセスしてください。

### レシート画像をアップロードしても何も変わらない

Tesseract OCR がインストールされていない可能性があります。ページに表示されるエラーメッセージを確認し、以下でインストールしてください:

```bash
brew install tesseract
brew install tesseract-lang
```

### `ModuleNotFoundError: No module named 'flask'`

依存パッケージがインストールされていません:

```bash
pip3 install -r requirements.txt
```

### データを初期化したい

`data/` フォルダ内の JSON ファイルを削除するとリセットされます:

```bash
rm -rf data/
```

次回起動時に空の状態で自動作成されます。
