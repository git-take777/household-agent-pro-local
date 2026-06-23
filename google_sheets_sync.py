"""
家計Pro - Google スプレッドシート自動同期モジュール
支出・収入が登録されるたびに、Google Sheets の該当月シートに自動反映する

★ セットアップ手順（容量問題を回避する方式）:
  1. Google Cloud Console で「サービスアカウント」を作成
  2. Google Sheets API と Google Drive API を有効化
  3. サービスアカウントの JSON キーをダウンロード → credentials/service_account.json に配置
  4. 自分のGoogleアカウントでスプレッドシートを新規作成
  5. setup_with_existing_sheet() を実行して連携開始
"""
import os
import json
import time
from datetime import datetime
from typing import Optional

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_DIR = os.path.join(BASE_DIR, "credentials")
SERVICE_ACCOUNT_FILE = os.path.join(CREDENTIALS_DIR, "service_account.json")
CONFIG_FILE = os.path.join(BASE_DIR, "gsheets_config.json")

OWNER_NAME = 'Take "TH" Naito'
MONTH_NAMES = [f"{m}月" for m in range(1, 13)]
SUMMARY_SHEET = "年間サマリー"

HEADERS = ["日付", "種別", "カテゴリ", "分類", "金額", "メモ", "登録日時"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_spreadsheet_id_for_year(year: int) -> Optional[str]:
    """指定年のスプレッドシートIDを取得"""
    config = _load_config()
    year_key = f"spreadsheet_{year}"
    if year_key in config:
        return config[year_key].get("spreadsheet_id")
    # 旧形式（単一設定）との互換: 2026年はデフォルトのIDを使う
    if year == 2026 and "spreadsheet_id" in config:
        return config["spreadsheet_id"]
    return None


def _save_spreadsheet_for_year(year: int, spreadsheet_id: str, spreadsheet_url: str):
    """指定年のスプレッドシートIDを保存"""
    config = _load_config()
    year_key = f"spreadsheet_{year}"
    config[year_key] = {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": spreadsheet_url,
        "created_at": datetime.now().isoformat(),
    }
    # 旧形式との互換を維持
    if year == 2026 and "spreadsheet_id" not in config:
        config["spreadsheet_id"] = spreadsheet_id
        config["spreadsheet_url"] = spreadsheet_url
    _save_config(config)


def _load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _get_client() -> Optional["gspread.Client"]:
    if not GSPREAD_AVAILABLE:
        print("[Google Sheets] gspread がインストールされていません。pip3 install gspread google-auth")
        return None

    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"[Google Sheets] サービスアカウントキーが見つかりません: {SERVICE_ACCOUNT_FILE}")
        print("  → credentials/service_account.json を配置してください")
        return None

    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        print(f"[Google Sheets] 認証エラー: {e}")
        return None


def get_service_account_email() -> Optional[str]:
    """サービスアカウントのメールアドレスを取得"""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        return None
    with open(SERVICE_ACCOUNT_FILE, "r") as f:
        data = json.load(f)
    return data.get("client_email")


# ============================================================
# ★ 新しいセットアップ方式: ユーザーが作成済みのシートを使う
# ============================================================

def setup_with_existing_sheet(spreadsheet_url: str, year: int = None):
    """
    ユーザーが自分のGoogleアカウントで作成したスプレッドシートを連携する。

    使い方:
      1. Google Sheets で空のスプレッドシートを作成
      2. サービスアカウントのメールアドレスに「編集者」権限で共有
      3. この関数にURLを渡す

    例:
      setup_with_existing_sheet("https://docs.google.com/spreadsheets/d/xxxxx/edit", year=2024)
    """
    if year is None:
        year = datetime.now().year

    client = _get_client()
    if not client:
        return

    # URLからスプレッドシートIDを抽出
    spreadsheet_id = _extract_sheet_id(spreadsheet_url)
    if not spreadsheet_id:
        print(f"[Google Sheets] 無効なURL: {spreadsheet_url}")
        print("  → https://docs.google.com/spreadsheets/d/xxxxx/edit の形式で指定してください")
        return

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        print(f"[Google Sheets] スプレッドシートに接続成功: {spreadsheet.title}")
    except gspread.SpreadsheetNotFound:
        sa_email = get_service_account_email()
        print(f"[Google Sheets] アクセス権限がありません。")
        print(f"  → スプレッドシートの共有設定で以下のメールアドレスを「編集者」として追加してください:")
        print(f"  → {sa_email}")
        return
    except Exception as e:
        print(f"[Google Sheets] 接続エラー: {e}")
        return

    # 年別設定を保存
    _save_spreadsheet_for_year(year, spreadsheet_id, spreadsheet_url)

    # シート構造を初期化
    _initialize_spreadsheet(spreadsheet, year)

    print(f"[Google Sheets] {year}年 セットアップ完了！")
    print(f"  URL: {spreadsheet_url}")
    print(f"  以降、{year}年の支出・収入を登録するたびに自動で反映されます。")


def _extract_sheet_id(url: str) -> Optional[str]:
    """Google Sheets URLからスプレッドシートIDを抽出"""
    # https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit...
    import re
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    if match:
        return match.group(1)
    # IDだけ渡された場合
    if re.match(r"^[a-zA-Z0-9_-]{20,}$", url):
        return url
    return None


# ============================================================
# スプレッドシート取得（登録時に毎回呼ばれる）
# ============================================================

def get_spreadsheet(year: int = None) -> Optional["gspread.Spreadsheet"]:
    """指定年のスプレッドシートを取得"""
    if year is None:
        year = datetime.now().year

    client = _get_client()
    if not client:
        return None

    spreadsheet_id = _get_spreadsheet_id_for_year(year)
    if not spreadsheet_id:
        return None

    try:
        return client.open_by_key(spreadsheet_id)
    except Exception as e:
        print(f"[Google Sheets] {year}年 スプレッドシート取得エラー: {e}")
        return None


# ============================================================
# シート初期化
# ============================================================

def _initialize_spreadsheet(spreadsheet: "gspread.Spreadsheet", year: int = 2026):
    """スプレッドシートに月別シート + 年間サマリーを作成（API制限対策あり）"""
    existing_sheets = [ws.title for ws in spreadsheet.worksheets()]

    # 月別シートを作成（存在しないものだけ）
    for month_name in MONTH_NAMES:
        if month_name not in existing_sheets:
            ws = spreadsheet.add_worksheet(title=month_name, rows=1000, cols=10)
            _setup_month_sheet(ws, month_name, year)
            print(f"  シート作成: {month_name}")
            time.sleep(5)  # API制限回避: 5秒待機
        else:
            print(f"  シート既存: {month_name}")

    # 年間サマリーシートを作成
    if SUMMARY_SHEET not in existing_sheets:
        default_sheets = [ws for ws in spreadsheet.worksheets() if ws.title in ("Sheet1", "シート1")]
        if default_sheets:
            default_sheets[0].update_title(SUMMARY_SHEET)
            time.sleep(3)
            _setup_summary_sheet(default_sheets[0], year)
        else:
            ws = spreadsheet.add_worksheet(title=SUMMARY_SHEET, rows=50, cols=10)
            time.sleep(3)
            _setup_summary_sheet(ws, year)
        print(f"  シート作成: {SUMMARY_SHEET}")
    else:
        print(f"  シート既存: {SUMMARY_SHEET}")

    # サマリーシートを先頭に移動
    try:
        time.sleep(3)
        summary_ws = spreadsheet.worksheet(SUMMARY_SHEET)
        spreadsheet.reorder_worksheets(
            [summary_ws] + [spreadsheet.worksheet(m) for m in MONTH_NAMES]
        )
    except Exception:
        pass

    print("[Google Sheets] 全13シート初期化完了")


def _setup_month_sheet(ws: "gspread.Worksheet", month_name: str, year: int = 2026):
    # データとヘッダーを1回で書き込み
    ws.update(range_name="A1:G2", values=[
        [f"{year}年 {month_name} - {OWNER_NAME}", "", "", "", "", "", ""],
        HEADERS,
    ])
    time.sleep(2)
    # 書式をまとめて設定
    ws.batch_format([
        {"range": "A2:G2", "format": {
            "backgroundColor": {"red": 0.17, "green": 0.37, "blue": 0.54},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "horizontalAlignment": "CENTER",
        }},
        {"range": "A1", "format": {
            "textFormat": {"bold": True, "fontSize": 13,
                           "foregroundColor": {"red": 0.17, "green": 0.37, "blue": 0.54}},
        }},
    ])
    try:
        ws.update_sheet_properties(ws.id, {"gridProperties": {"frozenRowCount": 2}})
    except Exception:
        pass


def _setup_summary_sheet(ws: "gspread.Worksheet", year: int = 2026):
    # タイトル + ヘッダーをまとめて1回で書き込み
    title_and_header = [
        [f"{year}年 家計簿 - {OWNER_NAME}", "", "", "", "", "", ""],
        ["年間サマリー（自動集計）", "", "", "", "", "", ""],
        ["", "", "", "", "", "", ""],  # 空行
        ["月", "収入合計", "支出合計", "収支差額", "件数（収入）", "件数（支出）", "件数（合計）"],
    ]
    ws.update(range_name="A1:G4", values=title_and_header)
    time.sleep(3)

    # 月別数式 + 年間合計を1回で書き込み
    rows = []
    for i, month_name in enumerate(MONTH_NAMES):
        row_num = 5 + i
        rows.append([
            month_name,
            f'=SUMPRODUCT((\'{month_name}\'!B:B="収入")*(\'{month_name}\'!E:E))',
            f'=SUMPRODUCT((\'{month_name}\'!B:B="支出")*(\'{month_name}\'!E:E))',
            f'=B{row_num}-C{row_num}',
            f'=COUNTIF(\'{month_name}\'!B:B,"収入")',
            f'=COUNTIF(\'{month_name}\'!B:B,"支出")',
            f'=E{row_num}+F{row_num}',
        ])
    rows.append([
        "年間合計",
        "=SUM(B5:B16)", "=SUM(C5:C16)", "=SUM(D5:D16)",
        "=SUM(E5:E16)", "=SUM(F5:F16)", "=SUM(G5:G16)",
    ])
    ws.update(range_name="A5:G17", values=rows, value_input_option="USER_ENTERED")
    time.sleep(3)

    # 書式をまとめて1回で設定
    ws.batch_format([
        {"range": "A4:G4", "format": {
            "backgroundColor": {"red": 0.17, "green": 0.37, "blue": 0.54},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "horizontalAlignment": "CENTER",
        }},
        {"range": "A1", "format": {
            "textFormat": {"bold": True, "fontSize": 16,
                           "foregroundColor": {"red": 0.17, "green": 0.37, "blue": 0.54}},
        }},
        {"range": "B5:D17", "format": {
            "numberFormat": {"type": "NUMBER", "pattern": '#,##0"円"'},
        }},
        {"range": "A17:G17", "format": {
            "backgroundColor": {"red": 0.96, "green": 0.96, "blue": 0.96},
            "textFormat": {"bold": True},
        }},
    ])


# ============================================================
# データ同期（登録時に呼ばれる）
# ============================================================

def sync_expense_to_sheets(entry: dict):
    _sync_entry_to_sheets(entry, entry_type="支出")


def sync_income_to_sheets(entry: dict):
    _sync_entry_to_sheets(entry, entry_type="収入")


def _sync_entry_to_sheets(entry: dict, entry_type: str):
    date_str = entry.get("date", "")
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        year = dt.year
        month_idx = dt.month
    except ValueError:
        year = datetime.now().year
        month_idx = datetime.now().month

    spreadsheet = get_spreadsheet(year)
    if not spreadsheet:
        return

    sheet_name = f"{month_idx}月"

    try:
        ws = spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=10)
        _setup_month_sheet(ws, sheet_name, year)

    all_values = ws.col_values(1)
    next_row = len(all_values) + 1
    if next_row < 3:
        next_row = 3

    group = entry.get("group", "")
    memo = entry.get("memo", "")
    category = entry.get("category", "")
    amount = entry.get("amount", 0)
    created = entry.get("created_at", datetime.now().isoformat())

    row_data = [
        date_str,
        entry_type,
        category,
        group,
        amount,
        memo,
        created[:16].replace("T", " "),
    ]

    ws.update(
        range_name=f"A{next_row}:G{next_row}",
        values=[row_data],
        value_input_option="USER_ENTERED",
    )

    if entry_type == "収入":
        ws.format(f"B{next_row}", {"backgroundColor": {"red": 0.91, "green": 0.96, "blue": 0.91}})
    else:
        ws.format(f"B{next_row}", {"backgroundColor": {"red": 1, "green": 0.95, "blue": 0.88}})


# ============================================================
# ユーティリティ
# ============================================================

def rebuild_sheets_from_json():
    """既存のJSONデータからGoogle Sheetsを年別に再構築する"""
    expense_file = os.path.join(BASE_DIR, "data", "expenses.json")
    income_file = os.path.join(BASE_DIR, "data", "incomes.json")

    # 全エントリから対象年を収集
    all_entries = []
    if os.path.exists(expense_file):
        with open(expense_file, "r", encoding="utf-8") as f:
            all_entries.extend(json.load(f))
    if os.path.exists(income_file):
        with open(income_file, "r", encoding="utf-8") as f:
            all_entries.extend(json.load(f))

    years = set()
    for entry in all_entries:
        try:
            years.add(int(entry.get("date", "")[:4]))
        except (ValueError, TypeError):
            years.add(datetime.now().year)

    if not years:
        years = {datetime.now().year}

    # 各年のスプレッドシートが設定されているか確認
    missing_years = []
    for year in sorted(years):
        sid = _get_spreadsheet_id_for_year(year)
        if not sid:
            missing_years.append(year)

    if missing_years:
        print(f"以下の年のスプレッドシートが未設定です: {missing_years}")
        print("先に setup_with_existing_sheet(url, year=XXXX) を実行してください。")
        return

    # 支出を復元
    if os.path.exists(expense_file):
        with open(expense_file, "r", encoding="utf-8") as f:
            expenses = json.load(f)
        for entry in expenses:
            sync_expense_to_sheets(entry)
        print(f"支出 {len(expenses)} 件を復元しました")

    # 収入を復元
    if os.path.exists(income_file):
        with open(income_file, "r", encoding="utf-8") as f:
            incomes = json.load(f)
        for entry in incomes:
            sync_income_to_sheets(entry)
        print(f"収入 {len(incomes)} 件を復元しました")

    print(f"対象年: {sorted(years)}")


def get_spreadsheet_url() -> Optional[str]:
    config = _load_config()
    return config.get("spreadsheet_url")


def check_connection() -> dict:
    result = {
        "gspread_installed": GSPREAD_AVAILABLE,
        "credentials_exist": os.path.exists(SERVICE_ACCOUNT_FILE),
        "config_exist": os.path.exists(CONFIG_FILE),
        "spreadsheet_url": None,
        "connected": False,
    }

    if not GSPREAD_AVAILABLE:
        result["error"] = "gspread がインストールされていません"
        return result

    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        result["error"] = f"サービスアカウントキーが見つかりません: {SERVICE_ACCOUNT_FILE}"
        return result

    client = _get_client()
    if not client:
        result["error"] = "認証に失敗しました"
        return result

    result["service_account_email"] = get_service_account_email()

    config = _load_config()
    spreadsheet_id = config.get("spreadsheet_id")
    if spreadsheet_id:
        try:
            spreadsheet = client.open_by_key(spreadsheet_id)
            result["spreadsheet_url"] = spreadsheet.url
            result["connected"] = True
        except Exception as e:
            result["error"] = f"スプレッドシートにアクセスできません: {e}"
    else:
        result["error"] = "スプレッドシートが未設定です。setup_with_existing_sheet() を実行してください。"

    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        url = sys.argv[1]
        # 第2引数があれば年として扱う
        year = None
        if len(sys.argv) > 2:
            try:
                year = int(sys.argv[2])
            except ValueError:
                print(f"年の指定が不正です: {sys.argv[2]}")
                sys.exit(1)
        if year is None:
            year = datetime.now().year
        print(f"スプレッドシートURL: {url}")
        print(f"対象年: {year}")
        setup_with_existing_sheet(url, year=year)
    else:
        status = check_connection()
        print("=== Google Sheets 接続状態 ===")
        for k, v in status.items():
            print(f"  {k}: {v}")

        sa_email = get_service_account_email()
        if sa_email:
            print(f"\n★ サービスアカウントのメールアドレス:")
            print(f"  {sa_email}")
            print(f"  → このアドレスをスプレッドシートの共有設定に「編集者」として追加してください")

        # 設定済みの年別スプレッドシート一覧
        config = _load_config()
        print(f"\n★ 設定済みスプレッドシート:")
        for key, val in config.items():
            if key.startswith("spreadsheet_") and isinstance(val, dict):
                year_str = key.replace("spreadsheet_", "")
                url_val = val.get("spreadsheet_url", "未設定")
                print(f"  {year_str}年: {url_val}")
        # 旧形式（2026年デフォルト）
        if "spreadsheet_id" in config and "spreadsheet_2026" not in config:
            print(f"  2026年(デフォルト): {config.get('spreadsheet_url', '未設定')}")

        print(f"\n★ 使い方:")
        print(f"  python3 google_sheets_sync.py <URL> <年>")
        print(f"  例: python3 google_sheets_sync.py https://docs.google.com/.../edit 2024")
