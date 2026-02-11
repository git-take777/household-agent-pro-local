#!/usr/bin/env python3
"""
家計Pro - メインCLIインターフェース
担当: プロダクトオーナー / フロントエンド担当

使い方:
  python kakeibo_pro.py demo                        # サンプルデータ生成＋レポート作成
  python kakeibo_pro.py add                         # 支出を対話的に追加
  python kakeibo_pro.py add-income                  # 収入を対話的に追加
  python kakeibo_pro.py report                      # 今月のレポート生成
  python kakeibo_pro.py report 2026 1               # 指定月のレポート生成
  python kakeibo_pro.py summary                     # 今月のサマリー表示
  python kakeibo_pro.py budget                      # 予算設定
  python kakeibo_pro.py list                        # 今月の支出一覧
  python kakeibo_pro.py delete <id>                 # 支出を削除
  python kakeibo_pro.py receipt <画像パス>           # レシート画像からOCR登録
  python kakeibo_pro.py import-csv <サービス> <CSV>  # Pay履歴CSVインポート
  python kakeibo_pro.py pay-services                # 対応決済サービス一覧
"""
import sys
import os
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import get_all_expense_categories, INCOME_CATEGORIES, CATEGORIES, DEFAULT_BUDGETS
from data_manager import (
    add_expense, add_income, get_expenses, get_incomes,
    delete_expense, set_budgets, get_budgets, generate_sample_data,
)
from analyzer import monthly_summary, budget_vs_actual, cost_effectiveness_analysis
from excel_reporter import generate_full_report

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def cmd_demo():
    print("=" * 50)
    print("  家計Pro - デモモード")
    print("=" * 50)
    print("\nサンプルデータを6ヶ月分生成します...")
    generate_sample_data(6)

    today = date.today()
    output_path = os.path.join(OUTPUT_DIR, f"家計Pro_レポート_{today.strftime('%Y%m')}.xlsx")
    print(f"\nレポートを生成中...")
    generate_full_report(today.year, today.month, output_path)
    print(f"レポート作成完了: {output_path}")
    print("\nExcelファイルを開いて各シートを確認してください:")
    print("  - ダッシュボード: 月次概要・カテゴリ別支出・円グラフ")
    print("  - 支出明細: 全支出の詳細リスト")
    print("  - 収入明細: 全収入の詳細リスト")
    print("  - 予算vs実績: 予算と実績の比較・棒グラフ")
    print("  - 月次トレンド: 6ヶ月間の推移・折れ線グラフ")
    print("  - 費用対効果: 無駄な支出の検出・改善提案")
    print("  - 異常値検出: 統計的に異常な支出の検出")


def cmd_add():
    print("\n--- 支出追加 ---")
    print("\nカテゴリ一覧:")
    all_cats = get_all_expense_categories()
    for i, cat in enumerate(all_cats, 1):
        print(f"  {i:2d}. {cat}")

    try:
        cat_idx = int(input("\nカテゴリ番号: ")) - 1
        if cat_idx < 0 or cat_idx >= len(all_cats):
            print("無効な番号です")
            return
        category = all_cats[cat_idx]

        date_str = input("日付 (YYYY-MM-DD, 空欄で今日): ").strip()
        if not date_str:
            date_str = date.today().strftime("%Y-%m-%d")

        amount = int(input("金額 (円): "))
        memo = input("メモ (空欄可): ").strip()

        entry = add_expense(date_str, category, amount, memo)
        print(f"\n追加しました: {entry['date']} {category} {amount:,}円 {memo}")
    except (ValueError, KeyboardInterrupt):
        print("\nキャンセルしました")


def cmd_add_income():
    print("\n--- 収入追加 ---")
    print("\n収入カテゴリ一覧:")
    cats = list(INCOME_CATEGORIES.keys())
    for i, cat in enumerate(cats, 1):
        print(f"  {i}. {cat}")

    try:
        cat_idx = int(input("\nカテゴリ番号: ")) - 1
        if cat_idx < 0 or cat_idx >= len(cats):
            print("無効な番号です")
            return
        category = cats[cat_idx]

        date_str = input("日付 (YYYY-MM-DD, 空欄で今日): ").strip()
        if not date_str:
            date_str = date.today().strftime("%Y-%m-%d")

        amount = int(input("金額 (円): "))
        memo = input("メモ (空欄可): ").strip()

        entry = add_income(date_str, category, amount, memo)
        print(f"\n追加しました: {entry['date']} {category} {amount:,}円 {memo}")
    except (ValueError, KeyboardInterrupt):
        print("\nキャンセルしました")


def cmd_report(year: int = None, month: int = None):
    today = date.today()
    y = year or today.year
    m = month or today.month

    output_path = os.path.join(OUTPUT_DIR, f"家計Pro_レポート_{y}{m:02d}.xlsx")
    print(f"\n{y}年{m}月のレポートを生成中...")
    generate_full_report(y, m, output_path)
    print(f"レポート作成完了: {output_path}")


def cmd_summary(year: int = None, month: int = None):
    today = date.today()
    y = year or today.year
    m = month or today.month

    summary = monthly_summary(y, m)
    print(f"\n{'=' * 45}")
    print(f"  家計サマリー - {y}年{m}月")
    print(f"{'=' * 45}")
    print(f"  総収入:   {summary['total_income']:>12,}円")
    print(f"  総支出:   {summary['total_expense']:>12,}円")
    print(f"  収支:     {summary['balance']:>12,}円")
    print(f"  貯蓄率:   {summary['saving_rate']:>11.1f}%")
    print(f"  取引数:   {summary['expense_count']:>10d}件")
    print(f"{'-' * 45}")

    if summary["by_group"]:
        print("\n  【分類別】")
        for grp, amt in summary["by_group"].items():
            pct = amt / summary["total_expense"] * 100 if summary["total_expense"] > 0 else 0
            print(f"  {grp:6s}: {amt:>10,}円 ({pct:.1f}%)")

    if summary["by_category"]:
        print(f"\n  【カテゴリ別 Top5】")
        sorted_cats = sorted(summary["by_category"].items(), key=lambda x: x[1]["amount"], reverse=True)
        for cat, info in sorted_cats[:5]:
            pct = info["amount"] / summary["total_expense"] * 100 if summary["total_expense"] > 0 else 0
            print(f"  {cat:8s}: {info['amount']:>10,}円 ({pct:.1f}%)")

    ce = cost_effectiveness_analysis(y, m)
    if ce["waste_items"]:
        print(f"\n  【節約ポイント】")
        print(f"  効率スコア: {ce['efficiency_score']:.1f}%")
        print(f"  節約可能額: {ce['savings_potential']:,}円")
        for item in ce["waste_items"][:3]:
            print(f"  ⚠ {item['suggestion']}")


def cmd_list(year: int = None, month: int = None):
    today = date.today()
    y = year or today.year
    m = month or today.month

    expenses = get_expenses(y, m)
    if expenses.empty:
        print(f"\n{y}年{m}月の支出データはありません。")
        return

    print(f"\n{y}年{m}月の支出一覧 ({len(expenses)}件)")
    print(f"{'ID':>4s} {'日付':10s} {'カテゴリ':8s} {'金額':>10s} {'メモ'}")
    print("-" * 55)
    for _, row in expenses.iterrows():
        print(f"{row['id']:>4d} {row['date'].strftime('%Y-%m-%d')} {row['category']:8s} {row['amount']:>10,}円 {row.get('memo', '')}")
    print("-" * 55)
    print(f"{'合計':>25s} {int(expenses['amount'].sum()):>10,}円")


def cmd_budget():
    today = date.today()
    y, m = today.year, today.month

    current = get_budgets(y, m)
    print(f"\n--- {y}年{m}月 予算設定 ---")
    print("(空欄でスキップ、0で予算なし)\n")

    new_budgets = {}
    for cat in get_all_expense_categories():
        current_val = current.get(cat, 0)
        try:
            val = input(f"  {cat:8s} (現在: {current_val:,}円): ").strip()
            if val:
                new_budgets[cat] = int(val)
            else:
                new_budgets[cat] = current_val
        except ValueError:
            new_budgets[cat] = current_val

    set_budgets(new_budgets, y, m)
    print("\n予算を更新しました。")


def cmd_delete(entry_id: int):
    if delete_expense(entry_id):
        print(f"ID {entry_id} の支出を削除しました。")
    else:
        print(f"ID {entry_id} の支出が見つかりません。")


def cmd_receipt(image_path: str):
    """レシート画像をOCR処理して支出登録する"""
    from receipt_scanner import scan_receipt_image, receipt_to_expense

    print(f"\nレシート画像を読み取り中: {image_path}")
    result = scan_receipt_image(image_path)

    if not result.get("success"):
        print(f"エラー: {result.get('error', '不明なエラー')}")
        return

    print(f"\n--- レシート読み取り結果 ---")
    print(f"  店名:     {result.get('store_name', '不明')}")
    print(f"  日付:     {result.get('date', '不明')}")
    print(f"  合計金額: {result.get('total', 0):,}円")
    print(f"  カテゴリ: {result.get('category_guess', '不明')}")
    if result.get("items"):
        print(f"  品目数:   {len(result['items'])}件")
        for item in result["items"][:5]:
            print(f"    - {item['name']}: {item['amount']:,}円")

    confirm = input("\nこの内容で登録しますか？ (y/n/カテゴリ変更→カテゴリ名): ").strip()
    if confirm.lower() == "n":
        print("キャンセルしました。")
        return

    all_cats = get_all_expense_categories()
    if confirm in all_cats:
        result["category_guess"] = confirm

    entry = receipt_to_expense(result)
    print(f"\n登録しました: ID={entry['id']} {entry['date']} {entry['category']} {entry['amount']:,}円")


def cmd_import_csv(service: str, csv_path: str):
    """Pay決済履歴CSVをインポートする"""
    from pay_integration import PAY_SERVICES, register_transactions, import_generic_csv

    if service not in PAY_SERVICES and service != "custom":
        print(f"未対応のサービス: {service}")
        print(f"対応サービス: {', '.join(PAY_SERVICES.keys())}, custom")
        return

    print(f"\n{service} のCSVをインポート中: {csv_path}")

    try:
        if service in PAY_SERVICES:
            transactions = PAY_SERVICES[service]["import_func"](csv_path)
        else:
            date_col = input("日付カラム名: ").strip()
            store_col = input("店舗カラム名: ").strip()
            amount_col = input("金額カラム名: ").strip()
            transactions = import_generic_csv(csv_path, date_col, store_col, amount_col)

        if not transactions:
            print("取引データが見つかりませんでした。")
            return

        print(f"\n{len(transactions)}件の取引を検出しました。")
        confirm = input("全て自動登録しますか？ (y=自動/n=1件ずつ確認): ").strip()
        auto = confirm.lower() == "y"

        registered = register_transactions(transactions, auto_confirm=auto)
        print(f"\n{len(registered)}件を登録しました。")
    except Exception as e:
        print(f"インポートエラー: {e}")


def cmd_pay_services():
    """対応決済サービス一覧を表示"""
    from pay_integration import show_pay_services
    show_pay_services()


def _parse_year_month(args, start_idx=2):
    """CLIの年月引数を安全にパースする"""
    y, m = None, None
    try:
        if len(args) > start_idx:
            y = int(args[start_idx])
            if y < 2000 or y > 2100:
                print(f"警告: 年は2000-2100の範囲で指定してください（入力: {y}）")
                return None, None
        if len(args) > start_idx + 1:
            m = int(args[start_idx + 1])
            if m < 1 or m > 12:
                print(f"エラー: 月は1-12の範囲で指定してください（入力: {m}）")
                return None, None
    except ValueError:
        print("エラー: 年月は数値で指定してください")
        return None, None
    return y, m


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()

    try:
        if command == "demo":
            cmd_demo()
        elif command == "add":
            cmd_add()
        elif command == "add-income":
            cmd_add_income()
        elif command == "report":
            y, m = _parse_year_month(sys.argv)
            cmd_report(y, m)
        elif command == "summary":
            y, m = _parse_year_month(sys.argv)
            cmd_summary(y, m)
        elif command == "list":
            y, m = _parse_year_month(sys.argv)
            cmd_list(y, m)
        elif command == "budget":
            cmd_budget()
        elif command == "delete":
            if len(sys.argv) < 3:
                print("使い方: python kakeibo_pro.py delete <id>")
                return
            try:
                cmd_delete(int(sys.argv[2]))
            except ValueError:
                print("エラー: IDは数値で指定してください")
        elif command == "receipt":
            if len(sys.argv) < 3:
                print("使い方: python kakeibo_pro.py receipt <画像パス>")
                return
            cmd_receipt(sys.argv[2])
        elif command == "import-csv":
            if len(sys.argv) < 4:
                print("使い方: python kakeibo_pro.py import-csv <サービス名> <CSVファイルパス>")
                print("サービス: paypay, linepay, rakuten, custom")
                return
            cmd_import_csv(sys.argv[2], sys.argv[3])
        elif command == "pay-services":
            cmd_pay_services()
        else:
            print(f"不明なコマンド: {command}")
            print(__doc__)
    except Exception as e:
        print(f"エラーが発生しました: {e}")


if __name__ == "__main__":
    main()
