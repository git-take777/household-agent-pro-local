"""
家計Pro - 統計分析モジュール
担当: バックエンド担当
月次トレンド、カテゴリ分析、予算vs実績、費用対効果分析
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from data_manager import get_expenses, get_incomes, get_budgets
from config import (
    get_all_expense_categories, get_category_group,
    NECESSITY_SCORES, CATEGORIES, DEFAULT_BUDGETS,
)


def monthly_summary(year: int, month: int) -> dict:
    expenses = get_expenses(year, month)
    incomes = get_incomes(year, month)

    total_expense = int(expenses["amount"].sum()) if not expenses.empty else 0
    total_income = int(incomes["amount"].sum()) if not incomes.empty else 0
    balance = total_income - total_expense
    saving_rate = (balance / total_income * 100) if total_income > 0 else 0

    by_category = {}
    if not expenses.empty:
        for cat, grp in expenses.groupby("category"):
            by_category[cat] = {
                "amount": int(grp["amount"].sum()),
                "count": len(grp),
                "group": get_category_group(cat),
            }

    by_group = {}
    if not expenses.empty:
        for grp_name, grp in expenses.groupby("group"):
            by_group[grp_name] = int(grp["amount"].sum())

    return {
        "year": year,
        "month": month,
        "total_expense": total_expense,
        "total_income": total_income,
        "balance": balance,
        "saving_rate": round(saving_rate, 1),
        "by_category": by_category,
        "by_group": by_group,
        "expense_count": len(expenses),
    }


def multi_month_trend(year: int, months: int = 6, end_month: int = None) -> List[dict]:
    """指定年月から過去N ヶ月分のトレンドを取得。end_monthを指定しない場合は現在月を使用。"""
    if end_month is None:
        end_month = datetime.now().month
    results = []
    for i in range(months):
        m = end_month - months + i + 1
        y = year
        while m <= 0:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1
        results.append(monthly_summary(y, m))
    return results


def budget_vs_actual(year: int, month: int) -> List[dict]:
    budgets = get_budgets(year, month)
    expenses = get_expenses(year, month)

    results = []
    for cat in get_all_expense_categories():
        budget = budgets.get(cat, 0)
        actual = 0
        if not expenses.empty:
            cat_expenses = expenses[expenses["category"] == cat]
            actual = int(cat_expenses["amount"].sum())

        diff = budget - actual
        rate = (actual / budget * 100) if budget > 0 else (100 if actual > 0 else 0)

        status = "適正"
        if rate > 120:
            status = "大幅超過"
        elif rate > 100:
            status = "超過"
        elif rate < 50 and budget > 0:
            status = "余裕あり"

        results.append({
            "category": cat,
            "group": get_category_group(cat),
            "budget": budget,
            "actual": actual,
            "diff": diff,
            "rate": round(rate, 1),
            "status": status,
        })

    return results


def cost_effectiveness_analysis(year: int, month: int) -> dict:
    expenses = get_expenses(year, month)
    if expenses.empty:
        return {"waste_items": [], "savings_potential": 0, "efficiency_score": 0}

    waste_items = []
    total_expense = int(expenses["amount"].sum())
    necessary_total = 0

    for cat, grp in expenses.groupby("category"):
        amount = int(grp["amount"].sum())
        necessity = NECESSITY_SCORES.get(cat, 5)
        cost_per_necessity = amount / necessity if necessity > 0 else amount

        if necessity <= 4 and amount > 10000:
            waste_items.append({
                "category": cat,
                "amount": amount,
                "necessity_score": necessity,
                "cost_per_necessity": round(cost_per_necessity),
                "suggestion": _get_saving_suggestion(cat, amount),
            })

        necessary_total += amount * (necessity / 10)

    waste_items.sort(key=lambda x: x["cost_per_necessity"], reverse=True)

    savings_potential = sum(
        max(0, item["amount"] - 5000) for item in waste_items
    )

    efficiency_score = round(
        (necessary_total / total_expense * 100) if total_expense > 0 else 0, 1
    )

    return {
        "waste_items": waste_items,
        "savings_potential": savings_potential,
        "efficiency_score": efficiency_score,
        "total_expense": total_expense,
        "necessary_total": round(necessary_total),
    }


def category_trend(category: str, year: int, months: int = 6) -> List[dict]:
    results = []
    for i in range(months):
        m = 12 - months + i + 1
        y = year
        while m <= 0:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1

        expenses = get_expenses(y, m, category)
        total = int(expenses["amount"].sum()) if not expenses.empty else 0
        results.append({"year": y, "month": m, "amount": total})

    for i in range(1, len(results)):
        prev = results[i - 1]["amount"]
        curr = results[i]["amount"]
        if prev > 0:
            results[i]["change_rate"] = round((curr - prev) / prev * 100, 1)
        else:
            results[i]["change_rate"] = 0
    if results:
        results[0]["change_rate"] = 0

    return results


def yearly_summary(year: int) -> dict:
    all_expenses = get_expenses(year)
    all_incomes = get_incomes(year)

    total_expense = int(all_expenses["amount"].sum()) if not all_expenses.empty else 0
    total_income = int(all_incomes["amount"].sum()) if not all_incomes.empty else 0
    balance = total_income - total_expense

    monthly_data = []
    for m in range(1, 13):
        summary = monthly_summary(year, m)
        monthly_data.append(summary)

    avg_expense = total_expense / 12
    avg_income = total_income / 12

    top_categories = []
    if not all_expenses.empty:
        by_cat = all_expenses.groupby("category")["amount"].sum().sort_values(ascending=False)
        for cat, amt in by_cat.head(5).items():
            pct = amt / total_expense * 100 if total_expense > 0 else 0
            top_categories.append({
                "category": cat,
                "amount": int(amt),
                "percentage": round(pct, 1),
            })

    return {
        "year": year,
        "total_expense": total_expense,
        "total_income": total_income,
        "balance": balance,
        "avg_monthly_expense": round(avg_expense),
        "avg_monthly_income": round(avg_income),
        "saving_rate": round((balance / total_income * 100) if total_income > 0 else 0, 1),
        "monthly_data": monthly_data,
        "top_categories": top_categories,
    }


def anomaly_detection(year: int, month: int, threshold: float = 1.5) -> List[dict]:
    """過去データから異常値（急激な増減）を検出"""
    current = get_expenses(year, month)
    if current.empty:
        return []

    anomalies = []
    for cat in get_all_expense_categories():
        history = []
        for i in range(1, 7):
            m = month - i
            y = year
            while m <= 0:
                m += 12
                y -= 1
            exp = get_expenses(y, m, cat)
            history.append(int(exp["amount"].sum()) if not exp.empty else 0)

        if not any(history):
            continue

        avg = np.mean(history)
        std = np.std(history)
        current_amt = int(current[current["category"] == cat]["amount"].sum()) if cat in current["category"].values else 0

        if std > 0 and abs(current_amt - avg) > threshold * std:
            direction = "増加" if current_amt > avg else "減少"
            anomalies.append({
                "category": cat,
                "current": current_amt,
                "average": round(avg),
                "std_dev": round(std),
                "z_score": round((current_amt - avg) / std, 2),
                "direction": direction,
            })

    return anomalies


def _get_saving_suggestion(category: str, amount: int) -> str:
    suggestions = {
        "娯楽費": f"娯楽費が{amount:,}円です。月{amount//2:,}円に抑えると年間{(amount//2)*12:,}円の節約になります",
        "交際費": f"交際費{amount:,}円。飲み会の回数を減らすか、2次会を控えると節約できます",
        "衣服費": f"衣服費{amount:,}円。セール時期にまとめ買いすると効率的です",
        "美容費": f"美容費{amount:,}円。頻度の見直しやクーポン活用を検討してみてください",
        "サブスク": f"サブスク{amount:,}円。使用頻度の低いサービスを見直してみましょう",
        "家電購入": f"家電購入{amount:,}円。購入前に価格比較サイトでの確認がおすすめです",
    }
    return suggestions.get(
        category,
        f"{category}に{amount:,}円。本当に必要か再検討してみてください"
    )
