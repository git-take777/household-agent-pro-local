"""
家計Pro - Excel自動同期モジュール
支出・収入が登録されるたびに、26年家計簿.xlsx の該当月シートに自動反映する
"""
import os
from datetime import datetime
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KAKEIBO_FILE = os.path.join(BASE_DIR, "26年家計簿.xlsx")

# === スタイル定義 ===
HEADER_FONT = Font(name="Arial", bold=True, size=11, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="2C5F8A")
SUBHEADER_FILL = PatternFill("solid", fgColor="D6E4F0")
INCOME_FILL = PatternFill("solid", fgColor="E8F5E9")
EXPENSE_FILL = PatternFill("solid", fgColor="FFF3E0")
SUMMARY_FILL = PatternFill("solid", fgColor="F5F5F5")
BORDER_THIN = Border(
    left=Side(style="thin", color="CCCCCC"),
    right=Side(style="thin", color="CCCCCC"),
    top=Side(style="thin", color="CCCCCC"),
    bottom=Side(style="thin", color="CCCCCC"),
)
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")
RIGHT = Alignment(horizontal="right", vertical="center")
YEN_FORMAT = '#,##0"円"'
DATE_FORMAT = "YYYY/MM/DD"

MONTH_NAMES = [f"{m}月" for m in range(1, 13)]
SUMMARY_SHEET = "年間サマリー"

# 月別シートのカラム構成
COLUMNS = {
    "A": ("日付", 14),
    "B": ("種別", 8),
    "C": ("カテゴリ", 14),
    "D": ("分類", 12),
    "E": ("金額", 14),
    "F": ("メモ", 30),
    "G": ("登録日時", 18),
}


def create_kakeibo_file(owner_name='Take "TH" Naito'):
    """26年家計簿.xlsx を新規作成（月別シート + 年間サマリー）"""
    wb = Workbook()

    # --- 年間サマリーシート ---
    ws_summary = wb.active
    ws_summary.title = SUMMARY_SHEET
    _build_summary_sheet(ws_summary, owner_name)

    # --- 月別シート（1月〜12月） ---
    for month_name in MONTH_NAMES:
        ws = wb.create_sheet(title=month_name)
        _build_month_sheet(ws, month_name, owner_name)

    wb.save(KAKEIBO_FILE)
    return KAKEIBO_FILE


def _build_summary_sheet(ws, owner_name):
    """年間サマリーシートを構築"""
    # タイトル
    ws.merge_cells("A1:G1")
    ws["A1"] = f"2026年 家計簿 - {owner_name}"
    ws["A1"].font = Font(name="Arial", bold=True, size=16, color="2C5F8A")
    ws["A1"].alignment = CENTER

    ws.merge_cells("A2:G2")
    ws["A2"] = "年間サマリー（自動集計）"
    ws["A2"].font = Font(name="Arial", size=10, color="888888")
    ws["A2"].alignment = CENTER

    # 月別集計ヘッダー（行4）
    headers = ["月", "収入合計", "支出合計", "収支差額", "件数（収入）", "件数（支出）", "件数（合計）"]
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col_idx, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = BORDER_THIN

    # 月別データ行（行5〜16）
    for i, month_name in enumerate(MONTH_NAMES):
        row = 5 + i
        ws.cell(row=row, column=1, value=month_name).alignment = CENTER
        ws.cell(row=row, column=1).border = BORDER_THIN
        ws.cell(row=row, column=1).fill = SUBHEADER_FILL

        # 収入合計: SUMIF(種別="収入") on each month sheet
        ws.cell(row=row, column=2).value = f"=SUMPRODUCT(('{month_name}'!B:B=\"収入\")*('{month_name}'!E:E))"
        ws.cell(row=row, column=2).number_format = YEN_FORMAT
        ws.cell(row=row, column=2).alignment = RIGHT
        ws.cell(row=row, column=2).border = BORDER_THIN
        ws.cell(row=row, column=2).fill = INCOME_FILL

        # 支出合計
        ws.cell(row=row, column=3).value = f"=SUMPRODUCT(('{month_name}'!B:B=\"支出\")*('{month_name}'!E:E))"
        ws.cell(row=row, column=3).number_format = YEN_FORMAT
        ws.cell(row=row, column=3).alignment = RIGHT
        ws.cell(row=row, column=3).border = BORDER_THIN
        ws.cell(row=row, column=3).fill = EXPENSE_FILL

        # 収支差額
        col_b = get_column_letter(2)
        col_c = get_column_letter(3)
        ws.cell(row=row, column=4).value = f"={col_b}{row}-{col_c}{row}"
        ws.cell(row=row, column=4).number_format = YEN_FORMAT
        ws.cell(row=row, column=4).alignment = RIGHT
        ws.cell(row=row, column=4).border = BORDER_THIN

        # 件数（収入）
        ws.cell(row=row, column=5).value = f'=COUNTIF(\'{month_name}\'!B:B,"収入")'
        ws.cell(row=row, column=5).alignment = CENTER
        ws.cell(row=row, column=5).border = BORDER_THIN

        # 件数（支出）
        ws.cell(row=row, column=6).value = f'=COUNTIF(\'{month_name}\'!B:B,"支出")'
        ws.cell(row=row, column=6).alignment = CENTER
        ws.cell(row=row, column=6).border = BORDER_THIN

        # 件数（合計）
        ws.cell(row=row, column=7).value = f"=E{row}+F{row}"
        ws.cell(row=row, column=7).alignment = CENTER
        ws.cell(row=row, column=7).border = BORDER_THIN

    # 年間合計行（行17）
    total_row = 17
    ws.cell(row=total_row, column=1, value="年間合計")
    ws.cell(row=total_row, column=1).font = Font(name="Arial", bold=True, size=11)
    ws.cell(row=total_row, column=1).fill = SUMMARY_FILL
    ws.cell(row=total_row, column=1).alignment = CENTER
    ws.cell(row=total_row, column=1).border = BORDER_THIN

    for col_idx in range(2, 8):
        col_letter = get_column_letter(col_idx)
        ws.cell(row=total_row, column=col_idx).value = f"=SUM({col_letter}5:{col_letter}16)"
        ws.cell(row=total_row, column=col_idx).font = Font(name="Arial", bold=True)
        ws.cell(row=total_row, column=col_idx).fill = SUMMARY_FILL
        ws.cell(row=total_row, column=col_idx).border = BORDER_THIN
        if col_idx <= 4:
            ws.cell(row=total_row, column=col_idx).number_format = YEN_FORMAT
            ws.cell(row=total_row, column=col_idx).alignment = RIGHT
        else:
            ws.cell(row=total_row, column=col_idx).alignment = CENTER

    # カラム幅
    col_widths = [10, 14, 14, 14, 12, 12, 12]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _build_month_sheet(ws, month_name, owner_name):
    """月別シートのヘッダーを構築"""
    # タイトル行
    ws.merge_cells("A1:G1")
    ws["A1"] = f"2026年 {month_name} - {owner_name}"
    ws["A1"].font = Font(name="Arial", bold=True, size=13, color="2C5F8A")
    ws["A1"].alignment = CENTER

    # ヘッダー行（行2）
    for col_letter, (header, width) in COLUMNS.items():
        cell = ws[f"{col_letter}2"]
        cell.value = header
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = BORDER_THIN
        ws.column_dimensions[col_letter].width = width

    # フリーズペイン（ヘッダー固定）
    ws.freeze_panes = "A3"


def sync_expense_to_excel(entry: dict):
    """支出データを該当月シートに追記"""
    _sync_entry_to_excel(entry, entry_type="支出")


def sync_income_to_excel(entry: dict):
    """収入データを該当月シートに追記"""
    _sync_entry_to_excel(entry, entry_type="収入")


def _sync_entry_to_excel(entry: dict, entry_type: str):
    """エントリを該当月のシートに追記する"""
    if not os.path.exists(KAKEIBO_FILE):
        create_kakeibo_file()

    try:
        wb = load_workbook(KAKEIBO_FILE)
    except Exception:
        create_kakeibo_file()
        wb = load_workbook(KAKEIBO_FILE)

    # 日付から月を特定
    date_str = entry.get("date", "")
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        month_idx = dt.month
    except ValueError:
        month_idx = datetime.now().month

    sheet_name = f"{month_idx}月"
    if sheet_name not in wb.sheetnames:
        ws = wb.create_sheet(title=sheet_name)
        _build_month_sheet(ws, sheet_name, "Ken")
    else:
        ws = wb[sheet_name]

    # 次の空き行を探す（行3以降）
    next_row = 3
    while ws.cell(row=next_row, column=1).value is not None:
        next_row += 1

    # データ書き込み
    group = entry.get("group", "")
    memo = entry.get("memo", "")
    category = entry.get("category", "")
    amount = entry.get("amount", 0)
    created = entry.get("created_at", datetime.now().isoformat())

    ws.cell(row=next_row, column=1, value=date_str)
    ws.cell(row=next_row, column=1).alignment = CENTER
    ws.cell(row=next_row, column=1).border = BORDER_THIN

    ws.cell(row=next_row, column=2, value=entry_type)
    ws.cell(row=next_row, column=2).alignment = CENTER
    ws.cell(row=next_row, column=2).border = BORDER_THIN
    if entry_type == "収入":
        ws.cell(row=next_row, column=2).fill = INCOME_FILL
    else:
        ws.cell(row=next_row, column=2).fill = EXPENSE_FILL

    ws.cell(row=next_row, column=3, value=category)
    ws.cell(row=next_row, column=3).alignment = LEFT
    ws.cell(row=next_row, column=3).border = BORDER_THIN

    ws.cell(row=next_row, column=4, value=group)
    ws.cell(row=next_row, column=4).alignment = CENTER
    ws.cell(row=next_row, column=4).border = BORDER_THIN

    ws.cell(row=next_row, column=5, value=amount)
    ws.cell(row=next_row, column=5).number_format = YEN_FORMAT
    ws.cell(row=next_row, column=5).alignment = RIGHT
    ws.cell(row=next_row, column=5).border = BORDER_THIN

    ws.cell(row=next_row, column=6, value=memo)
    ws.cell(row=next_row, column=6).alignment = LEFT
    ws.cell(row=next_row, column=6).border = BORDER_THIN

    ws.cell(row=next_row, column=7, value=created[:16].replace("T", " "))
    ws.cell(row=next_row, column=7).alignment = CENTER
    ws.cell(row=next_row, column=7).border = BORDER_THIN
    ws.cell(row=next_row, column=7).font = Font(name="Arial", size=9, color="999999")

    wb.save(KAKEIBO_FILE)


def rebuild_excel_from_json():
    """既存のJSONデータからExcelを再構築する（リカバリ用）"""
    import json

    expense_file = os.path.join(BASE_DIR, "data", "expenses.json")
    income_file = os.path.join(BASE_DIR, "data", "incomes.json")

    # 新規作成
    create_kakeibo_file()

    # 支出を復元
    if os.path.exists(expense_file):
        with open(expense_file, "r", encoding="utf-8") as f:
            expenses = json.load(f)
        for entry in expenses:
            sync_expense_to_excel(entry)

    # 収入を復元
    if os.path.exists(income_file):
        with open(income_file, "r", encoding="utf-8") as f:
            incomes = json.load(f)
        for entry in incomes:
            sync_income_to_excel(entry)

    return KAKEIBO_FILE


if __name__ == "__main__":
    path = create_kakeibo_file()
    print(f"作成完了: {path}")
