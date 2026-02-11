#!/usr/bin/env python3
"""
家計Pro - テストスイート
担当: テスト担当
"""
import os
import sys
import json
import shutil
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    get_all_expense_categories, get_category_group,
    get_category_info, CATEGORIES, INCOME_CATEGORIES,
    NECESSITY_SCORES, DEFAULT_BUDGETS,
)
import data_manager
from data_manager import (
    add_expense, add_income, get_expenses, get_incomes,
    delete_expense, delete_income, update_expense,
    set_budgets, get_budgets, generate_sample_data,
    _validate_date,
)
from analyzer import (
    monthly_summary, multi_month_trend, budget_vs_actual,
    cost_effectiveness_analysis, anomaly_detection, yearly_summary,
)
from receipt_scanner import parse_receipt_text, _guess_category


TEST_DATA_DIR = "/sessions/focused-keen-fermat/test_data_kakeibo"


class TestConfig(unittest.TestCase):
    def test_get_all_categories(self):
        cats = get_all_expense_categories()
        self.assertGreater(len(cats), 10)
        self.assertIn("食費", cats)
        self.assertIn("住居費", cats)
        self.assertIn("娯楽費", cats)

    def test_get_category_group(self):
        self.assertEqual(get_category_group("住居費"), "固定費")
        self.assertEqual(get_category_group("食費"), "変動費")
        self.assertEqual(get_category_group("税金"), "特別費")
        self.assertEqual(get_category_group("存在しない"), "不明")

    def test_get_category_info(self):
        info = get_category_info("食費")
        self.assertIn("description", info)
        self.assertIn("icon", info)

    def test_necessity_scores_coverage(self):
        cats = get_all_expense_categories()
        for cat in cats:
            self.assertIn(cat, NECESSITY_SCORES, f"{cat}のNECESSITY_SCOREがありません")

    def test_default_budgets_coverage(self):
        cats = get_all_expense_categories()
        for cat in cats:
            self.assertIn(cat, DEFAULT_BUDGETS, f"{cat}のDEFAULT_BUDGETがありません")


class TestDataManager(unittest.TestCase):
    def setUp(self):
        self.original_data_dir = data_manager.DATA_DIR
        data_manager.DATA_DIR = TEST_DATA_DIR
        data_manager.EXPENSE_FILE = os.path.join(TEST_DATA_DIR, "expenses.json")
        data_manager.INCOME_FILE = os.path.join(TEST_DATA_DIR, "incomes.json")
        data_manager.BUDGET_FILE = os.path.join(TEST_DATA_DIR, "budgets.json")
        os.makedirs(TEST_DATA_DIR, exist_ok=True)

    def tearDown(self):
        if os.path.exists(TEST_DATA_DIR):
            shutil.rmtree(TEST_DATA_DIR)
        data_manager.DATA_DIR = self.original_data_dir
        data_manager.EXPENSE_FILE = os.path.join(self.original_data_dir, "expenses.json")
        data_manager.INCOME_FILE = os.path.join(self.original_data_dir, "incomes.json")
        data_manager.BUDGET_FILE = os.path.join(self.original_data_dir, "budgets.json")

    def test_add_expense(self):
        entry = add_expense("2026-02-01", "食費", 5000, "テスト")
        self.assertEqual(entry["category"], "食費")
        self.assertEqual(entry["amount"], 5000)
        self.assertEqual(entry["group"], "変動費")

    def test_add_expense_invalid_category(self):
        with self.assertRaises(ValueError):
            add_expense("2026-02-01", "存在しないカテゴリ", 1000)

    def test_add_expense_invalid_amount(self):
        with self.assertRaises(ValueError):
            add_expense("2026-02-01", "食費", -100)

    def test_add_expense_invalid_date(self):
        with self.assertRaises(ValueError):
            add_expense("2026-13-45", "食費", 1000)

    def test_validate_date(self):
        self.assertEqual(_validate_date("2026-02-11"), "2026-02-11")
        with self.assertRaises(ValueError):
            _validate_date("invalid-date")
        with self.assertRaises(ValueError):
            _validate_date("2026/02/11")

    def test_get_expenses(self):
        add_expense("2026-01-15", "食費", 3000)
        add_expense("2026-02-15", "食費", 5000)
        df = get_expenses(2026, 2)
        self.assertEqual(len(df), 1)
        self.assertEqual(int(df.iloc[0]["amount"]), 5000)

    def test_delete_expense(self):
        entry = add_expense("2026-02-01", "食費", 1000)
        self.assertTrue(delete_expense(entry["id"]))
        self.assertFalse(delete_expense(9999))

    def test_add_income(self):
        entry = add_income("2026-02-25", "給与", 300000, "2月分給与")
        self.assertEqual(entry["category"], "給与")
        self.assertEqual(entry["amount"], 300000)

    def test_add_income_invalid_category(self):
        with self.assertRaises(ValueError):
            add_income("2026-02-25", "不明カテゴリ", 100000)

    def test_update_expense(self):
        entry = add_expense("2026-02-01", "食費", 5000)
        updated = update_expense(entry["id"], amount=7000)
        self.assertEqual(updated["amount"], 7000)

    def test_update_expense_category_validation(self):
        entry = add_expense("2026-02-01", "食費", 5000)
        with self.assertRaises(ValueError):
            update_expense(entry["id"], category="不正カテゴリ")

    def test_budgets(self):
        budgets = {"食費": 60000, "住居費": 90000}
        set_budgets(budgets, 2026, 2)
        result = get_budgets(2026, 2)
        self.assertEqual(result["食費"], 60000)


class TestAnalyzer(unittest.TestCase):
    def setUp(self):
        self.original_data_dir = data_manager.DATA_DIR
        data_manager.DATA_DIR = TEST_DATA_DIR
        data_manager.EXPENSE_FILE = os.path.join(TEST_DATA_DIR, "expenses.json")
        data_manager.INCOME_FILE = os.path.join(TEST_DATA_DIR, "incomes.json")
        data_manager.BUDGET_FILE = os.path.join(TEST_DATA_DIR, "budgets.json")
        os.makedirs(TEST_DATA_DIR, exist_ok=True)

        add_expense("2026-02-05", "食費", 30000, "スーパー")
        add_expense("2026-02-10", "食費", 15000, "外食")
        add_expense("2026-02-15", "娯楽費", 20000, "映画")
        add_expense("2026-02-20", "住居費", 80000, "家賃")
        add_income("2026-02-25", "給与", 300000, "2月分給与")

    def tearDown(self):
        if os.path.exists(TEST_DATA_DIR):
            shutil.rmtree(TEST_DATA_DIR)
        data_manager.DATA_DIR = self.original_data_dir
        data_manager.EXPENSE_FILE = os.path.join(self.original_data_dir, "expenses.json")
        data_manager.INCOME_FILE = os.path.join(self.original_data_dir, "incomes.json")
        data_manager.BUDGET_FILE = os.path.join(self.original_data_dir, "budgets.json")

    def test_monthly_summary(self):
        summary = monthly_summary(2026, 2)
        self.assertEqual(summary["total_expense"], 145000)
        self.assertEqual(summary["total_income"], 300000)
        self.assertEqual(summary["balance"], 155000)
        self.assertIn("食費", summary["by_category"])
        self.assertEqual(summary["by_category"]["食費"]["amount"], 45000)

    def test_budget_vs_actual(self):
        bva = budget_vs_actual(2026, 2)
        self.assertIsInstance(bva, list)
        food = next((b for b in bva if b["category"] == "食費"), None)
        self.assertIsNotNone(food)
        self.assertEqual(food["actual"], 45000)

    def test_cost_effectiveness(self):
        ce = cost_effectiveness_analysis(2026, 2)
        self.assertIn("waste_items", ce)
        self.assertIn("efficiency_score", ce)
        self.assertIn("savings_potential", ce)
        self.assertEqual(ce["total_expense"], 145000)

    def test_empty_month(self):
        summary = monthly_summary(2026, 6)
        self.assertEqual(summary["total_expense"], 0)
        self.assertEqual(summary["total_income"], 0)


class TestReceiptScanner(unittest.TestCase):
    def test_parse_receipt_basic(self):
        text = """イオン 幕張店
2026/02/11 14:30
牛乳         ¥198
パン         ¥250
りんご       ¥398
合計         ¥846
"""
        result = parse_receipt_text(text)
        self.assertEqual(result["date"], "2026-02-11")
        self.assertGreater(result["total"], 0)
        self.assertEqual(result["category_guess"], "食費")

    def test_parse_receipt_no_date(self):
        text = """ドラッグストア
洗剤    ¥500
合計    ¥500"""
        result = parse_receipt_text(text)
        self.assertEqual(result["date"], date.today().strftime("%Y-%m-%d"))

    def test_guess_category(self):
        self.assertEqual(_guess_category("イオン", []), "食費")
        self.assertEqual(_guess_category("ユニクロ", []), "衣服費")
        self.assertEqual(_guess_category("マツキヨ", []), "日用品")
        self.assertEqual(_guess_category("unknown", []), "食費")  # デフォルト

    def test_parse_reiwa_date(self):
        text = """コンビニ
R8.02.11
おにぎり ¥150
合計 ¥150"""
        result = parse_receipt_text(text)
        self.assertEqual(result["date"], "2026-02-11")


if __name__ == "__main__":
    unittest.main(verbosity=2)
