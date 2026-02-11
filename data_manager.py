"""
家計Pro - データ管理モジュール
担当: バックエンド担当
支出・収入データのCRUD操作とデータバリデーション
"""
import json
import os
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
import pandas as pd
from config import get_all_expense_categories, INCOME_CATEGORIES, get_category_group

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
EXPENSE_FILE = os.path.join(DATA_DIR, "expenses.json")
INCOME_FILE = os.path.join(DATA_DIR, "incomes.json")
BUDGET_FILE = os.path.join(DATA_DIR, "budgets.json")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_json(filepath: str) -> list:
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(filepath: str, data: list):
    _ensure_data_dir()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


# === 支出データ ===

def _validate_date(date_str: str) -> str:
    """日付文字列を検証し、正規化して返す"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError(f"無効な日付形式: {date_str}。YYYY-MM-DD形式で入力してください")


def add_expense(
    date_str: str,
    category: str,
    amount: int,
    memo: str = "",
    necessity: Optional[int] = None,
) -> dict:
    date_str = _validate_date(date_str)
    valid_cats = get_all_expense_categories()
    if category not in valid_cats:
        raise ValueError(f"無効なカテゴリ: {category}。有効: {valid_cats}")
    if amount <= 0:
        raise ValueError("金額は正の整数である必要があります")

    entry = {
        "id": _next_id(EXPENSE_FILE),
        "date": date_str,
        "category": category,
        "group": get_category_group(category),
        "amount": amount,
        "memo": memo,
        "necessity": necessity,
        "created_at": datetime.now().isoformat(),
    }
    data = _load_json(EXPENSE_FILE)
    data.append(entry)
    _save_json(EXPENSE_FILE, data)
    return entry


def add_income(
    date_str: str,
    category: str,
    amount: int,
    memo: str = "",
) -> dict:
    date_str = _validate_date(date_str)
    if category not in INCOME_CATEGORIES:
        raise ValueError(f"無効な収入カテゴリ: {category}")
    if amount <= 0:
        raise ValueError("金額は正の整数である必要があります")

    entry = {
        "id": _next_id(INCOME_FILE),
        "date": date_str,
        "category": category,
        "amount": amount,
        "memo": memo,
        "created_at": datetime.now().isoformat(),
    }
    data = _load_json(INCOME_FILE)
    data.append(entry)
    _save_json(INCOME_FILE, data)
    return entry


def get_expenses(
    year: Optional[int] = None,
    month: Optional[int] = None,
    category: Optional[str] = None,
) -> pd.DataFrame:
    data = _load_json(EXPENSE_FILE)
    if not data:
        return pd.DataFrame(columns=["id", "date", "category", "group", "amount", "memo", "necessity"])
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    if year:
        df = df[df["date"].dt.year == year]
    if month:
        df = df[df["date"].dt.month == month]
    if category:
        df = df[df["category"] == category]
    return df.sort_values("date").reset_index(drop=True)


def get_incomes(
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> pd.DataFrame:
    data = _load_json(INCOME_FILE)
    if not data:
        return pd.DataFrame(columns=["id", "date", "category", "amount", "memo"])
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    if year:
        df = df[df["date"].dt.year == year]
    if month:
        df = df[df["date"].dt.month == month]
    return df.sort_values("date").reset_index(drop=True)


def delete_expense(entry_id: int) -> bool:
    data = _load_json(EXPENSE_FILE)
    new_data = [e for e in data if e["id"] != entry_id]
    if len(new_data) == len(data):
        return False
    _save_json(EXPENSE_FILE, new_data)
    return True


def delete_income(entry_id: int) -> bool:
    data = _load_json(INCOME_FILE)
    new_data = [e for e in data if e["id"] != entry_id]
    if len(new_data) == len(data):
        return False
    _save_json(INCOME_FILE, new_data)
    return True


def update_expense(entry_id: int, **kwargs) -> Optional[dict]:
    data = _load_json(EXPENSE_FILE)
    for entry in data:
        if entry["id"] == entry_id:
            if "category" in kwargs:
                valid_cats = get_all_expense_categories()
                if kwargs["category"] not in valid_cats:
                    raise ValueError(f"無効なカテゴリ: {kwargs['category']}")
                kwargs["group"] = get_category_group(kwargs["category"])
            if "date" in kwargs:
                kwargs["date"] = _validate_date(kwargs["date"])
            if "amount" in kwargs and kwargs["amount"] <= 0:
                raise ValueError("金額は正の整数である必要があります")
            for k, v in kwargs.items():
                if k in entry:
                    entry[k] = v
            entry["updated_at"] = datetime.now().isoformat()
            _save_json(EXPENSE_FILE, data)
            return entry
    return None


# === 予算データ ===

def set_budgets(budgets: Dict[str, int], year: int, month: int):
    data = _load_json(BUDGET_FILE)
    key = f"{year}-{month:02d}"
    existing = [b for b in data if b["period"] != key]
    existing.append({"period": key, "budgets": budgets})
    _save_json(BUDGET_FILE, existing)


def get_budgets(year: int, month: int) -> Dict[str, int]:
    from config import DEFAULT_BUDGETS
    data = _load_json(BUDGET_FILE)
    key = f"{year}-{month:02d}"
    for entry in data:
        if entry["period"] == key:
            return entry["budgets"]
    return DEFAULT_BUDGETS.copy()


# === サンプルデータ生成 ===

def generate_sample_data(months: int = 6):
    """デモ用のサンプルデータを生成する"""
    import random
    random.seed(42)

    today = date.today()
    base_year = today.year
    base_month = today.month

    _ensure_data_dir()
    _save_json(EXPENSE_FILE, [])
    _save_json(INCOME_FILE, [])

    expense_ranges = {
        "住居費": (75000, 85000), "光熱費": (8000, 25000),
        "通信費": (8000, 12000), "保険料": (18000, 22000),
        "食費": (35000, 65000), "日用品": (3000, 12000),
        "交通費": (5000, 15000), "衣服費": (0, 20000),
        "医療費": (0, 10000), "娯楽費": (5000, 25000),
        "交際費": (3000, 20000), "美容費": (0, 8000),
        "サブスク": (3000, 6000), "教育費": (0, 10000),
    }

    income_ranges = {
        "給与": (280000, 320000),
        "副業": (0, 50000),
    }

    for i in range(months):
        m = base_month - months + i + 1
        y = base_year
        while m <= 0:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1

        for cat, (lo, hi) in expense_ranges.items():
            amt = random.randint(lo, hi)
            if amt == 0:
                continue
            num_entries = random.randint(1, 4) if cat in ("食費", "日用品", "交通費") else 1
            per_entry = amt // num_entries
            for j in range(num_entries):
                day = random.randint(1, 28)
                memos = {
                    "食費": ["スーパー", "外食", "コンビニ", "デリバリー"],
                    "日用品": ["ドラッグストア", "100均", "ホームセンター"],
                    "交通費": ["定期代", "タクシー", "ガソリン"],
                    "娯楽費": ["映画", "ゲーム", "旅行", "書籍"],
                    "交際費": ["飲み会", "ランチ", "プレゼント"],
                }
                memo = random.choice(memos.get(cat, [""]))
                add_expense(f"{y}-{m:02d}-{day:02d}", cat, per_entry, memo)

        for cat, (lo, hi) in income_ranges.items():
            amt = random.randint(lo, hi)
            if amt == 0:
                continue
            add_income(f"{y}-{m:02d}-25", cat, amt, f"{m}月分{cat}")

    print(f"サンプルデータを{months}ヶ月分生成しました。")


def _next_id(filepath: str) -> int:
    data = _load_json(filepath)
    if not data:
        return 1
    return max(e.get("id", 0) for e in data) + 1
