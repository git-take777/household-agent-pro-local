"""
家計Pro - 設定・カテゴリ定義モジュール
担当: システム設計者
"""
from dataclasses import dataclass, field
from typing import Dict, List
from datetime import datetime

CATEGORIES = {
    "固定費": {
        "住居費": {"icon": "🏠", "description": "家賃・住宅ローン・管理費"},
        "光熱費": {"icon": "💡", "description": "電気・ガス・水道"},
        "通信費": {"icon": "📱", "description": "携帯・インターネット・固定電話"},
        "保険料": {"icon": "🛡️", "description": "生命保険・医療保険・火災保険"},
        "教育費": {"icon": "📚", "description": "学費・塾・習い事"},
        "車両費": {"icon": "🚗", "description": "車のローン・駐車場・車検"},
        "サブスク": {"icon": "🔄", "description": "定額サービス・月額課金"},
    },
    "変動費": {
        "食費": {"icon": "🍱", "description": "食料品・自炊材料・飲料（外食除く）"},
        "外食費": {"icon": "🍽️", "description": "1人での外食（すき家・丸亀製麺等）"},
        "日用品": {"icon": "🧴", "description": "洗剤・トイレットペーパー等"},
        "交通費": {"icon": "🚃", "description": "電車・バス・タクシー・ガソリン"},
        "衣服費": {"icon": "👕", "description": "衣類・靴・アクセサリー"},
        "医療費": {"icon": "🏥", "description": "病院・薬・歯科"},
        "娯楽費": {"icon": "🎮", "description": "趣味・レジャー・旅行"},
        "交際費": {"icon": "🤝", "description": "2人以上の外食・飲み会・冠婚葬祭・プレゼント"},
        "美容費": {"icon": "💇", "description": "美容院・化粧品・エステ"},
    },
    "特別費": {
        "冠婚葬祭": {"icon": "🎊", "description": "結婚式・お葬式・お祝い"},
        "家電購入": {"icon": "📺", "description": "家電製品の購入・修理"},
        "税金": {"icon": "🏛️", "description": "所得税・住民税・固定資産税"},
        "その他": {"icon": "📦", "description": "上記に分類できないもの"},
    },
}

INCOME_CATEGORIES = {
    "給与": {"icon": "💰", "description": "月給・賞与"},
    "副業": {"icon": "💼", "description": "フリーランス・アルバイト"},
    "投資": {"icon": "📈", "description": "配当・売却益・利息"},
    "年金": {"icon": "🏦", "description": "公的年金・企業年金"},
    "その他収入": {"icon": "💵", "description": "臨時収入・還付金等"},
}

DEFAULT_BUDGETS = {
    "住居費": 80000,
    "光熱費": 15000,
    "通信費": 10000,
    "保険料": 20000,
    "教育費": 15000,
    "車両費": 20000,
    "サブスク": 5000,
    "食費": 40000,
    "外食費": 15000,
    "日用品": 8000,
    "交通費": 10000,
    "衣服費": 10000,
    "医療費": 5000,
    "娯楽費": 15000,
    "交際費": 10000,
    "美容費": 5000,
    "冠婚葬祭": 5000,
    "家電購入": 5000,
    "税金": 0,
    "その他": 5000,
}

NECESSITY_SCORES = {
    "住居費": 10,
    "外食費": 5,
    "光熱費": 10,
    "通信費": 8,
    "保険料": 7,
    "教育費": 8,
    "車両費": 5,
    "サブスク": 3,
    "食費": 10,
    "日用品": 9,
    "交通費": 7,
    "衣服費": 5,
    "医療費": 9,
    "娯楽費": 2,
    "交際費": 4,
    "美容費": 3,
    "冠婚葬祭": 6,
    "家電購入": 4,
    "税金": 10,
    "その他": 3,
}

EXCEL_STYLES = {
    "header_fill": "1F4E79",
    "header_font": "FFFFFF",
    "subheader_fill": "D6E4F0",
    "fixed_fill": "E2EFDA",
    "variable_fill": "FCE4D6",
    "special_fill": "E4D5F0",
    "income_fill": "C6EFCE",
    "warning_fill": "FFC7CE",
    "good_fill": "C6EFCE",
    "neutral_fill": "FFEB9C",
    "border_color": "B4B4B4",
    "title_font_size": 16,
    "header_font_size": 11,
    "body_font_size": 10,
}

def get_all_expense_categories() -> List[str]:
    cats = []
    for group in CATEGORIES.values():
        cats.extend(group.keys())
    return cats

def get_category_group(category: str) -> str:
    for group_name, group in CATEGORIES.items():
        if category in group:
            return group_name
    return "不明"

def get_category_info(category: str) -> dict:
    for group in CATEGORIES.values():
        if category in group:
            return group[category]
    return {"icon": "❓", "description": "不明なカテゴリ"}
