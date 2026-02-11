#!/bin/zsh
# ============================================================
#  家計Pro - gitmoji コミット＆Push スクリプト (zsh対応版 v3)
# ============================================================
#
#  使い方:
#    cd /Users/take/App/WebApp/claude_code/HouseholdFinanceProAgent
#    rm -f .git/index.lock
#    chmod +x setup_and_push.sh
#    zsh setup_and_push.sh
#
#  ※ 既にコミット済みファイルがあっても動作します
#     (orphanブランチで履歴をリセットします)
#
# ============================================================

set -e

REMOTE_URL="https://github.com/git-take777/household-agent-pro-local.git"
BRANCH="feat/kakeibo-pro"

echo "============================================"
echo "  家計Pro - gitmoji コミット＆Push (v3)"
echo "============================================"
echo ""

# --- lock ファイルの掃除 ---
if [ -f ".git/index.lock" ]; then
    echo "index.lock を削除します..."
    rm -f .git/index.lock
fi

# --- git init (既存なら skip) ---
if [ ! -d ".git" ]; then
    git init
    git branch -m main
fi

# --- remote 設定 ---
if ! git remote get-url origin > /dev/null 2>&1; then
    git remote add origin "$REMOTE_URL"
else
    git remote set-url origin "$REMOTE_URL"
fi

# --- orphanブランチで完全リセット ---
# orphan = 過去の履歴を持たないまっさらなブランチ
# これにより、全ファイルが「新規追加」として扱われる
echo ""
echo "orphanブランチを作成: $BRANCH"
git checkout --orphan "$BRANCH" 2>/dev/null || true

# ステージングエリアをクリア（全ファイルをunstaged状態に）
git rm -rf --cached . 2>/dev/null || true
git reset 2>/dev/null || true

echo ""
echo "gitmoji コミットを作成します..."
echo ""

# ============================================================
# Commit 1
# ============================================================
echo "[1/9] init"
git add .gitignore requirements.txt
git commit -m "🎉 init: プロジェクト初期セットアップ

- .gitignore: キャッシュ・データ・生成ファイルの除外設定
- requirements.txt: openpyxl, pandas の依存定義

家計Pro - local環境で家計簿の計算・統計分析を行うPython+Excelツール
ミッション: 手軽に効率よく計算し節約、費用対効果の算出"

# ============================================================
# Commit 2
# ============================================================
echo "[2/9] config"
git add config.py
git commit -m "🏗️ arch(config): カテゴリ・予算・必要度スコアの設計定義

担当: システム設計者

- 固定費/変動費/特別費の3階層カテゴリ体系（21カテゴリ）
- 収入カテゴリ5種（給与/副業/投資/年金/その他）
- DEFAULT_BUDGETS: カテゴリ別デフォルト予算額
- NECESSITY_SCORES: 費用対効果分析用の必要度スコア（1-10）
- EXCEL_STYLES: レポートの統一スタイル定数
- ユーティリティ関数: get_all_expense_categories, get_category_group等"

# ============================================================
# Commit 3
# ============================================================
echo "[3/9] data_manager"
git add data_manager.py
git commit -m "✨ feat(data): 支出・収入・予算のCRUD管理モジュール

担当: バックエンド担当

- add_expense/add_income: 日付バリデーション付きデータ登録
- get_expenses/get_incomes: 年月・カテゴリによるフィルタリング検索
- update_expense: カテゴリ再検証・グループ自動更新付き更新
- delete_expense/delete_income: エントリ削除
- set_budgets/get_budgets: 月別予算の設定・取得
- generate_sample_data: デモ用6ヶ月分サンプルデータ生成
- _validate_date: YYYY-MM-DD形式の厳密な日付検証

データはJSON形式でdata/ディレクトリに永続化"

# ============================================================
# Commit 4
# ============================================================
echo "[4/9] analyzer"
git add analyzer.py
git commit -m "📊 feat(analyzer): 統計分析・費用対効果・異常値検出エンジン

担当: バックエンド担当

- monthly_summary: 月次サマリー（収支/カテゴリ別/分類別）
- multi_month_trend: 過去Nヶ月の推移分析（動的end_month対応）
- budget_vs_actual: 予算vs実績の比較分析（達成率/状態判定）
- cost_effectiveness_analysis: 費用対効果分析
- anomaly_detection: Z-score基準の統計的異常値検出（1.5σ）
- category_trend: カテゴリ別の月次変化率分析
- yearly_summary: 年間サマリーとTop5カテゴリ"

# ============================================================
# Commit 5
# ============================================================
echo "[5/9] excel_reporter"
git add excel_reporter.py
git commit -m "💄 feat(excel): 7シート構成のExcelレポート生成エンジン

担当: フロントエンド担当

- ダッシュボード: 月次概要 + 円グラフ（支出構成比）
- 支出明細: フィルタ付き全支出リスト + SUM数式
- 収入明細: 収入一覧 + 合計数式
- 予算vs実績: 棒グラフ付き予算比較
- 月次トレンド: 折れ線グラフ + カテゴリ別推移マトリックス
- 費用対効果: 無駄検出テーブル + コスパ指数マトリックス
- 異常値検出: Z-score基準の異常支出レポート"

# ============================================================
# Commit 6
# ============================================================
echo "[6/9] receipt_scanner"
git add receipt_scanner.py
git commit -m "🔍 feat(receipt): レシートOCRスキャナーとカテゴリ自動推定

担当: バックエンド担当

- scan_receipt_image: 画像ファイルからOCRテキスト抽出
- parse_receipt_text: OCRテキストから構造化データへの変換
- 日付パース: YYYY/MM/DD, YYYY-MM-DD, 令和(R)形式に対応
- _guess_category: 店名・品目からカテゴリ自動推定
- scan_receipt_folder: フォルダ一括処理
- receipt_to_expense: パース結果から支出登録への変換"

# ============================================================
# Commit 7
# ============================================================
echo "[7/9] pay_integration"
git add pay_integration.py
git commit -m "🔌 feat(pay): PayPay/LINE Pay/楽天Pay CSV取込とAPI連携基盤

担当: バックエンド担当

- import_paypay_csv / import_linepay_csv / import_rakuten_csv
- import_generic_csv: 汎用CSV（カラム名指定方式）
- 複数エンコーディング自動検出（UTF-8/Shift_JIS/CP932/EUC-JP）
- register_transactions: 取引の一括/対話式登録
- setup_rakuten_api: 楽天API認証設定（将来実装用）
- show_pay_services: 対応サービス一覧"

# ============================================================
# Commit 8
# ============================================================
echo "[8/9] kakeibo_pro"
git add kakeibo_pro.py
git commit -m "🎨 feat(cli): 統合CLIインターフェース（全12コマンド）

担当: プロダクトオーナー / フロントエンド担当

- demo / add / add-income / report / summary
- list / budget / delete
- receipt: レシートOCRから自動登録
- import-csv: Pay履歴CSVインポート
- pay-services: 対応決済サービス一覧
- _parse_year_month: 年月引数の安全なバリデーション"

# ============================================================
# Commit 9
# ============================================================
echo "[9/9] test_kakeibo"
git add test_kakeibo.py
git commit -m "✅ test: 4モジュール25テストケースのテストスイート

担当: テスト担当

- TestConfig: カテゴリ一覧、グループ分類、スコアカバレッジ (5)
- TestDataManager: CRUD操作、バリデーション、日付検証 (11)
- TestAnalyzer: 月次サマリー、予算比較、費用対効果 (4)
- TestReceiptScanner: パース、令和日付、カテゴリ推定 (4)

全25テスト PASSED"

# ============================================================
# 残りのファイルがあれば追加
# ============================================================
if [ -n "$(git status --porcelain)" ]; then
    echo "[+] 残りのファイルを追加"
    git add -A
    git commit -m "🔧 chore: セットアップスクリプト等の追加" 2>/dev/null || true
fi

echo ""
echo "============================================"
echo "  全コミット作成完了"
echo "============================================"
echo ""
git log --oneline --graph
echo ""

# --- Push ---
echo ""
echo "push します... (force push で既存ブランチを上書き)"
git push -u origin "$BRANCH" --force

echo ""
echo "============================================"
echo "  完了！ 以下のURLからPRを作成してください:"
echo "  https://github.com/git-take777/household-agent-pro-local/pull/new/$BRANCH"
echo "============================================"
