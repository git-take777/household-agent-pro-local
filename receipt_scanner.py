"""
家計Pro - レシートOCRモジュール
担当: バックエンド担当

レシート画像から情報を抽出し、支出データとして登録する。
OCRエンジンは拡張可能な設計（Tesseract / Google Vision API / Claude Vision）

必要な追加パッケージ:
  pip install Pillow pytesseract
  (Tesseract OCR本体も別途インストールが必要)
"""
import os
import re
import json
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from config import get_all_expense_categories, CATEGORIES


# === OCR結果のパース ===

def parse_receipt_text(text: str) -> dict:
    """OCR出力テキストからレシート情報を抽出する"""
    result = {
        "store_name": "",
        "date": "",
        "items": [],
        "total": 0,
        "category_guess": "",
        "raw_text": text,
    }

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return result

    # 店名: 通常は最初の数行にある
    result["store_name"] = lines[0] if lines else ""

    # 日付抽出: 複数のパターンに対応
    date_patterns = [
        r"(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})",  # 2026/02/11, 2026-02-11, 2026年2月11日
        r"(\d{2})[/\-](\d{1,2})[/\-](\d{1,2})",        # 26/02/11
        r"R(\d)[/\.\-](\d{1,2})[/\.\-](\d{1,2})",      # R6.02.11 (令和)
    ]
    for pattern in date_patterns:
        for line in lines:
            match = re.search(pattern, line)
            if match:
                groups = match.groups()
                if len(groups) == 3:
                    y, m, d = groups
                    y = int(y)
                    if pattern.startswith("R"):
                        y = y + 2018  # 令和 -> 西暦
                    elif y < 100:
                        y += 2000 if y < 50 else 1900
                    try:
                        result["date"] = f"{y}-{int(m):02d}-{int(d):02d}"
                    except ValueError:
                        pass
                break
        if result["date"]:
            break

    if not result["date"]:
        result["date"] = date.today().strftime("%Y-%m-%d")

    # 金額抽出: 各行から品目と金額のペアを抽出
    amount_pattern = re.compile(r"[¥￥]?\s*([\d,]+)\s*$")
    total_patterns = [
        re.compile(r"(?:合計|合　計|お買上|お買い上げ|TOTAL|total)\s*[¥￥]?\s*([\d,]+)"),
        re.compile(r"[¥￥]\s*([\d,]+)\s*(?:合計|TOTAL)"),
    ]

    # 合計金額の抽出
    for pattern in total_patterns:
        for line in lines:
            match = pattern.search(line)
            if match:
                result["total"] = int(match.group(1).replace(",", ""))
                break
        if result["total"]:
            break

    # 品目の抽出
    for line in lines:
        if any(kw in line for kw in ["合計", "小計", "税", "お釣り", "お預かり", "TOTAL", "CHANGE"]):
            continue
        match = amount_pattern.search(line)
        if match:
            amount = int(match.group(1).replace(",", ""))
            item_name = line[:match.start()].strip()
            item_name = re.sub(r"^[\d]+\s*", "", item_name)  # 先頭の数字を除去
            if item_name and amount > 0 and amount < 1000000:
                result["items"].append({"name": item_name, "amount": amount})

    # 合計がなければ品目の合計を使用
    if not result["total"] and result["items"]:
        result["total"] = sum(item["amount"] for item in result["items"])

    # カテゴリ推定
    result["category_guess"] = _guess_category(result["store_name"], result["items"])

    return result


def _guess_category(store_name: str, items: list) -> str:
    """店名と品目からカテゴリを推定する"""
    store_lower = store_name.lower()

    store_keywords = {
        "食費": ["スーパー", "マルエツ", "イオン", "セブン", "ファミマ", "ローソン",
                 "コンビニ", "マクドナルド", "吉野家", "すき家", "restaurant",
                 "弁当", "寿司", "ラーメン", "カフェ", "スタバ", "ドトール",
                 "パン", "ベーカリー", "肉", "魚", "八百屋", "成城石井",
                 "ライフ", "サミット", "オーケー", "業務スーパー", "コストコ"],
        "日用品": ["ドラッグ", "マツキヨ", "ウエルシア", "サンドラッグ", "ツルハ",
                  "ホームセンター", "コーナン", "カインズ", "ダイソー", "セリア",
                  "100均", "無印", "ニトリ"],
        "衣服費": ["ユニクロ", "GU", "H&M", "ZARA", "しまむら", "ABCマート",
                  "靴", "アウトレット"],
        "交通費": ["JR", "地下鉄", "メトロ", "バス", "タクシー", "ENEOS",
                  "出光", "ガソリン", "駐車場", "パーキング"],
        "医療費": ["病院", "クリニック", "薬局", "調剤", "歯科", "眼科"],
        "娯楽費": ["映画", "カラオケ", "ゲーム", "本屋", "書店", "Amazon",
                  "楽天", "ヨドバシ", "ビックカメラ"],
        "美容費": ["美容", "理容", "ヘアサロン", "エステ", "ネイル"],
    }

    for category, keywords in store_keywords.items():
        for kw in keywords:
            if kw.lower() in store_lower:
                return category

    item_names = " ".join(item["name"] for item in items).lower()
    for category, keywords in store_keywords.items():
        for kw in keywords:
            if kw.lower() in item_names:
                return category

    return "食費"  # デフォルト


def scan_receipt_image(image_path: str) -> dict:
    """レシート画像をOCR処理し、構造化データを返す"""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"画像ファイルが見つかりません: {image_path}")

    ext = os.path.splitext(image_path)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"):
        raise ValueError(f"サポートされていない画像形式: {ext}")

    # OCRエンジンの選択（利用可能なものから自動選択）
    text = ""
    ocr_engine = "none"

    # 1. pytesseractを試す
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang="jpn")
        ocr_engine = "tesseract"
    except ImportError:
        pass
    except Exception as e:
        print(f"Tesseract OCRエラー: {e}")

    # 2. OCRが利用できない場合のフォールバック
    if not text:
        return {
            "success": False,
            "error": "OCRエンジンが利用できません。以下のいずれかをインストールしてください:\n"
                     "  pip install pytesseract Pillow\n"
                     "  (+ Tesseract OCR本体)\n"
                     "または、手動でデータを入力してください: python kakeibo_pro.py add",
            "ocr_engine": ocr_engine,
        }

    receipt_data = parse_receipt_text(text)
    receipt_data["success"] = True
    receipt_data["ocr_engine"] = ocr_engine
    receipt_data["image_path"] = image_path
    return receipt_data


def receipt_to_expense(receipt_data: dict) -> dict:
    """パース済みレシートデータから支出エントリを作成する"""
    from data_manager import add_expense

    memo_parts = [receipt_data.get("store_name", "")]
    if receipt_data.get("items"):
        top_items = receipt_data["items"][:3]
        memo_parts.append(" / ".join(item["name"] for item in top_items))

    entry = add_expense(
        date_str=receipt_data.get("date", date.today().strftime("%Y-%m-%d")),
        category=receipt_data.get("category_guess", "食費"),
        amount=receipt_data.get("total", 0),
        memo=" - ".join(filter(None, memo_parts)),
    )
    return entry


# === バッチ処理 ===

def scan_receipt_folder(folder_path: str) -> List[dict]:
    """フォルダ内の全レシート画像を一括処理"""
    results = []
    supported = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp")

    for filename in sorted(os.listdir(folder_path)):
        if os.path.splitext(filename)[1].lower() in supported:
            filepath = os.path.join(folder_path, filename)
            print(f"処理中: {filename}")
            try:
                result = scan_receipt_image(filepath)
                result["filename"] = filename
                results.append(result)
            except Exception as e:
                results.append({"filename": filename, "success": False, "error": str(e)})

    return results
