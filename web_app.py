#!/usr/bin/env python3
"""
家計Pro - Web Interface (Flask)
Dashboard, Expense/Income CRUD, Receipt OCR, Image Compression
"""
import os
import sys
import json
import io
import re
import uuid
from datetime import datetime, date
from flask import (
    Flask, render_template_string, request, redirect, url_for,
    flash, jsonify, send_file,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    CATEGORIES, INCOME_CATEGORIES, get_all_expense_categories,
    get_category_group, NECESSITY_SCORES, DEFAULT_BUDGETS,
)
from data_manager import (
    add_expense, add_income, get_expenses, get_incomes,
    delete_expense, set_budgets, get_budgets,
)
from analyzer import (
    monthly_summary, multi_month_trend, budget_vs_actual,
    cost_effectiveness_analysis, anomaly_detection,
)
from excel_reporter import generate_full_report

app = Flask(__name__)
app.secret_key = "kakeibo-pro-secret-key-2026"

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
REPORT_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ============================================================
#  Image Compression Utility
# ============================================================
def compress_image(image_bytes, filename, max_size_kb=500, max_dimension=1600):
    """
    JPEG/PNG画像を圧縮して小さくする
    - max_size_kb: 目標最大ファイルサイズ(KB)
    - max_dimension: 最大辺のピクセル数
    """
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    original_size = len(image_bytes)

    # EXIF回転情報を適用
    try:
        from PIL import ExifTags
        exif = img._getexif()
        if exif:
            for tag, value in exif.items():
                if ExifTags.TAGS.get(tag) == "Orientation":
                    if value == 3:
                        img = img.rotate(180, expand=True)
                    elif value == 6:
                        img = img.rotate(270, expand=True)
                    elif value == 8:
                        img = img.rotate(90, expand=True)
    except Exception:
        pass

    # リサイズ (大きすぎる画像を縮小)
    w, h = img.size
    if max(w, h) > max_dimension:
        ratio = max_dimension / max(w, h)
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # 拡張子から形式判定
    ext = os.path.splitext(filename)[1].lower()
    is_png = ext == ".png"

    # 保存 & 圧縮
    output = io.BytesIO()
    if is_png:
        # PNG: パレット化で圧縮
        if img.mode == "RGBA":
            img.save(output, format="PNG", optimize=True)
        else:
            img = img.convert("RGB")
            img.save(output, format="PNG", optimize=True)
    else:
        # JPEG: 品質を段階的に下げて目標サイズ以下に
        img = img.convert("RGB")
        quality = 85
        while quality >= 20:
            output = io.BytesIO()
            img.save(output, format="JPEG", quality=quality, optimize=True)
            if output.tell() <= max_size_kb * 1024:
                break
            quality -= 10

    compressed_bytes = output.getvalue()
    compressed_size = len(compressed_bytes)

    return {
        "image": img,
        "bytes": compressed_bytes,
        "original_size": original_size,
        "compressed_size": compressed_size,
        "ratio": round((1 - compressed_size / original_size) * 100, 1) if original_size > 0 else 0,
        "format": "PNG" if is_png else "JPEG",
        "dimensions": img.size,
    }


# ============================================================
#  Receipt OCR Engine
# ============================================================
def _check_tesseract():
    """Tesseractが利用可能かチェックする"""
    import shutil
    tesseract_path = shutil.which("tesseract")
    if tesseract_path:
        return True, tesseract_path
    # macOS Homebrew の典型的なパス
    for path in ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"]:
        if os.path.isfile(path):
            return True, path
    return False, None


def ocr_receipt(image, filepath=None):
    """
    レシート画像からテキストを抽出し、
    店舗名・日付・金額・カテゴリを推定する
    Tesseractがない場合はファイル名ベースの簡易モードで動作
    """
    from PIL import Image, ImageFilter, ImageEnhance
    import traceback

    # --- Tesseract の存在チェック ---
    tesseract_available, tesseract_path = _check_tesseract()

    text = ""
    ocr_method = "none"
    ocr_error = ""

    if tesseract_available:
        try:
            import pytesseract

            if tesseract_path:
                pytesseract.pytesseract.tesseract_cmd = tesseract_path

            # tessdataパスを自動検出
            tessdata_candidates = [
                "/opt/homebrew/share/tessdata",
                "/usr/local/share/tessdata",
                "/usr/share/tesseract-ocr/4.00/tessdata",
                "/usr/share/tesseract-ocr/5/tessdata",
                "/usr/share/tessdata",
            ]
            for td in tessdata_candidates:
                if os.path.isdir(td):
                    os.environ["TESSDATA_PREFIX"] = td
                    break

            # 前処理: コントラスト強化 + シャープ化 + グレースケール
            img_processed = image.convert("L")
            enhancer = ImageEnhance.Contrast(img_processed)
            img_processed = enhancer.enhance(2.0)
            enhancer = ImageEnhance.Sharpness(img_processed)
            img_processed = enhancer.enhance(2.0)
            img_processed = img_processed.point(lambda x: 0 if x < 140 else 255)

            # OCR実行
            # jpn があれば日本語+英語、なければ英語のみ
            try:
                available_langs = pytesseract.get_languages()
                lang = "jpn+eng" if "jpn" in available_langs else "eng"
            except Exception:
                lang = "eng"

            custom_config = r"--oem 3 --psm 6"
            text = pytesseract.image_to_string(img_processed, lang=lang, config=custom_config)
            ocr_method = f"tesseract ({lang})"

        except Exception as e:
            ocr_error = f"Tesseractエラー: {e}\n{traceback.format_exc()}"
            text = ""
    else:
        ocr_error = (
            "Tesseract OCRが見つかりません。\n"
            "インストール方法:\n"
            "  brew install tesseract\n"
            "  brew install tesseract-lang  (日本語対応)\n\n"
            "現在は画像情報のみで簡易解析を行います。"
        )

    # テキストが取れなかった場合 → 簡易モード（画像情報 + ファイル名から推定）
    if not text.strip():
        ocr_method = "簡易モード（OCRなし）"
        result = {
            "store_name": "",
            "date": date.today().strftime("%Y-%m-%d"),
            "line_items": [],
            "total": 0,
            "category_guess": "食費",
            "payment_method": "",
            "raw_text": f"[OCRテキストなし]\n\n{ocr_error}" if ocr_error else "[OCRテキストなし]",
            "success": True,
            "ocr_method": ocr_method,
            "ocr_error": ocr_error,
            "needs_manual_input": True,
        }
        # ファイル名から店名を推定
        if filepath:
            fname = os.path.basename(filepath).lower()
            for key, name in [("seven", "セブンイレブン"), ("lawson", "ローソン"),
                              ("famima", "ファミリーマート"), ("aeon", "イオン")]:
                if key in fname:
                    result["store_name"] = name
                    break
        return result

    # テキストからレシート情報を抽出
    result = parse_receipt_ocr(text)
    result["raw_text"] = text
    result["success"] = True
    result["ocr_method"] = ocr_method
    result["ocr_error"] = ""
    result["needs_manual_input"] = False

    return result


def parse_receipt_ocr(text):
    """OCRテキストからレシート情報を解析"""
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    result = {
        "store_name": "",
        "date": "",
        "line_items": [],
        "total": 0,
        "category_guess": "食費",
        "payment_method": "",
    }

    # --- 店舗名の推定 (最初の数行から) ---
    store_keywords = {
        # スーパー・コンビニ
        "seven": "セブンイレブン", "7-eleven": "セブンイレブン", "7-11": "セブンイレブン",
        "lawson": "ローソン", "familymart": "ファミリーマート", "family mart": "ファミリーマート",
        "ministop": "ミニストップ", "daily": "デイリーヤマザキ",
        "aeon": "イオン", "daiei": "ダイエー", "ito-yokado": "イトーヨーカドー",
        "seiyu": "西友", "life": "ライフ", "maruetsu": "マルエツ",
        "summit": "サミット", "ok": "オーケー", "gyomu": "業務スーパー",
        "costco": "コストコ", "donki": "ドン・キホーテ", "don quijote": "ドン・キホーテ",
        # ドラッグストア
        "matsukiyo": "マツモトキヨシ", "welcia": "ウエルシア", "sundrug": "サンドラッグ",
        "tsuruha": "ツルハ", "cocokara": "ココカラファイン",
        # 家電
        "yamada": "ヤマダ電機", "bic": "ビックカメラ", "yodobashi": "ヨドバシカメラ",
        "edion": "エディオン", "kojima": "コジマ",
        # レストラン等
        "mcdonald": "マクドナルド", "starbucks": "スターバックス",
        "sukiya": "すき家", "matsuya": "松屋", "yoshinoya": "吉野家",
        "gusto": "ガスト", "saizeriya": "サイゼリヤ", "denny": "デニーズ",
        # 交通
        "jr": "JR", "suica": "Suica", "pasmo": "PASMO",
        # 決済
        "paypay": "PayPay", "linepay": "LINE Pay", "rakuten": "楽天",
    }

    for line in lines[:5]:
        lower = line.lower()
        for key, name in store_keywords.items():
            if key in lower:
                result["store_name"] = name
                break
        if result["store_name"]:
            break

    if not result["store_name"] and lines:
        # 最初の行を店舗名として扱う (数字でなければ)
        first_line = lines[0]
        if not re.match(r"^[\d\s\-/:.]+$", first_line):
            result["store_name"] = first_line[:30]

    # --- 日付の抽出 ---
    date_patterns = [
        r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})",          # 2026/02/11
        r"(\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})",          # 26/02/11
        r"R(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{1,2})",       # R8/02/11 (令和)
    ]
    for line in lines:
        for i, pattern in enumerate(date_patterns):
            match = re.search(pattern, line)
            if match:
                groups = match.groups()
                if i == 0:  # YYYY/MM/DD
                    y, m, d = int(groups[0]), int(groups[1]), int(groups[2])
                elif i == 1:  # YY/MM/DD
                    y = int(groups[0])
                    y = y + 2000 if y < 50 else y + 1900
                    m, d = int(groups[1]), int(groups[2])
                elif i == 2:  # 令和
                    y = int(groups[0]) + 2018
                    m, d = int(groups[1]), int(groups[2])

                try:
                    result["date"] = f"{y}-{m:02d}-{d:02d}"
                    datetime.strptime(result["date"], "%Y-%m-%d")
                    break
                except ValueError:
                    result["date"] = ""
        if result["date"]:
            break

    if not result["date"]:
        result["date"] = date.today().strftime("%Y-%m-%d")

    # --- 金額の抽出 ---
    amounts = []
    total_keywords = ["total", "合計", "小計", "税込", "taxincl", "sum", "ttl", "お支払"]
    item_pattern = re.compile(r"(.+?)\s+[¥\\]?\s*(\d[\d,]*)\s*$")

    for line in lines:
        # 品目 + 金額のパターン
        m = item_pattern.match(line)
        if m:
            name = m.group(1).strip()
            try:
                amount = int(m.group(2).replace(",", ""))
                if 1 <= amount <= 999999:
                    amounts.append(amount)
                    result["line_items"].append({"name": name, "amount": amount})
            except ValueError:
                pass

        # 数字のみの行からも金額抽出
        nums = re.findall(r"[¥\\]?\s*(\d[\d,]*)", line)
        for n in nums:
            try:
                val = int(n.replace(",", ""))
                if val not in amounts and 1 <= val <= 999999:
                    amounts.append(val)
            except ValueError:
                pass

    # 合計の推定: 「合計」キーワード近くの金額 or 最大金額
    total_found = False
    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in total_keywords):
            nums = re.findall(r"(\d[\d,]*)", line)
            for n in nums:
                try:
                    val = int(n.replace(",", ""))
                    if 10 <= val <= 999999:
                        result["total"] = val
                        total_found = True
                        break
                except ValueError:
                    pass
            if total_found:
                break

    if not total_found and amounts:
        result["total"] = max(amounts)

    # --- カテゴリ推定 ---
    text_lower = text.lower()
    category_patterns = {
        "食費": ["food", "grocery", "スーパー", "コンビニ", "弁当", "おにぎり",
                  "パン", "飲料", "meat", "fish", "vegetable", "rice", "milk",
                  "マクドナルド", "restaurant", "cafe", "coffee", "lunch", "dinner"],
        "日用品": ["drug", "pharmacy", "洗剤", "shampoo", "soap", "tissue",
                   "paper", "cleaning", "ドラッグ", "日用"],
        "交通費": ["jr", "suica", "pasmo", "train", "bus", "taxi", "gas",
                   "parking", "toll", "駐車"],
        "医療費": ["hospital", "clinic", "pharmacy", "medicine", "doctor",
                   "医療", "薬", "処方"],
        "衣服費": ["cloth", "fashion", "wear", "shoes", "uniqlo", "gu ",
                   "zara", "h&m", "衣"],
        "娯楽費": ["movie", "game", "book", "amazon", "entertainment",
                   "hobby", "映画", "ゲーム"],
        "美容費": ["beauty", "salon", "hair", "cosmetic", "nail", "美容"],
        "光熱費": ["electric", "gas bill", "water bill", "電気", "ガス", "水道"],
        "通信費": ["phone", "mobile", "internet", "wifi", "au ", "docomo",
                   "softbank"],
        "家電購入": ["electronics", "appliance", "camera", "pc", "yamada",
                    "bic", "yodobashi", "家電"],
    }

    best_category = "食費"
    best_score = 0
    for cat, keywords in category_patterns.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > best_score:
            best_score = score
            best_category = cat

    # 店舗名からもカテゴリ推定
    store = result["store_name"].lower()
    store_category_map = {
        "セブン": "食費", "ローソン": "食費", "ファミリ": "食費",
        "イオン": "食費", "西友": "食費", "ライフ": "食費",
        "マツモト": "日用品", "ウエルシア": "日用品", "サンドラッグ": "日用品",
        "ヤマダ": "家電購入", "ビック": "家電購入", "ヨドバシ": "家電購入",
        "マクドナルド": "食費", "スターバックス": "食費",
        "ドン・キホーテ": "日用品",
    }
    for key, cat in store_category_map.items():
        if key in result["store_name"]:
            result["category_guess"] = cat
            break
    else:
        result["category_guess"] = best_category

    # --- 決済方法の推定 ---
    payment_keywords = {
        "cash": "現金", "credit": "クレジット", "card": "カード",
        "paypay": "PayPay", "linepay": "LINE Pay", "suica": "Suica",
        "pasmo": "PASMO", "id ": "iD", "quicpay": "QUICPay",
        "visa": "VISA", "master": "Mastercard", "amex": "AMEX",
    }
    for kw, method in payment_keywords.items():
        if kw in text_lower:
            result["payment_method"] = method
            break

    return result


# ============================================================
#  HTML Template
# ============================================================
BASE_HTML = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>家計Pro - {{ page_title }}</title>
    <style>
        :root {
            --primary: #1F4E79;
            --primary-light: #D6E4F0;
            --success: #006100;
            --success-bg: #C6EFCE;
            --warning: #9C0006;
            --warning-bg: #FFC7CE;
            --orange: #ED7D31;
            --orange-bg: #FCE4D6;
            --purple: #7B4F9B;
            --purple-bg: #E4D5F0;
            --bg: #F5F7FA;
            --card: #FFFFFF;
            --text: #333333;
            --text-light: #666666;
            --border: #E0E0E0;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', 'Hiragino Sans', 'Noto Sans JP', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
        }
        /* Navigation */
        nav {
            background: var(--primary);
            color: white;
            padding: 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .nav-inner {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            gap: 0;
        }
        .nav-brand {
            font-size: 1.3rem;
            font-weight: 700;
            padding: 14px 24px;
            white-space: nowrap;
            letter-spacing: 1px;
        }
        .nav-links {
            display: flex;
            gap: 0;
            flex-wrap: wrap;
        }
        .nav-links a {
            color: rgba(255,255,255,0.85);
            text-decoration: none;
            padding: 14px 16px;
            font-size: 0.9rem;
            font-weight: 500;
            transition: all 0.2s;
            border-bottom: 3px solid transparent;
        }
        .nav-links a:hover, .nav-links a.active {
            color: white;
            background: rgba(255,255,255,0.1);
            border-bottom: 3px solid var(--orange);
        }
        /* Main */
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 24px 20px;
        }
        h1 {
            font-size: 1.6rem;
            color: var(--primary);
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 3px solid var(--primary);
        }
        /* Cards */
        .card {
            background: var(--card);
            border-radius: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            padding: 24px;
            margin-bottom: 20px;
        }
        .card h2 {
            font-size: 1.15rem;
            color: var(--primary);
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 2px solid var(--primary-light);
        }
        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: var(--card);
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            border-top: 4px solid var(--primary);
        }
        .stat-card.income { border-top-color: var(--success); }
        .stat-card.expense { border-top-color: var(--warning); }
        .stat-card.balance { border-top-color: var(--orange); }
        .stat-card.saving { border-top-color: var(--purple); }
        .stat-label {
            font-size: 0.85rem;
            color: var(--text-light);
            margin-bottom: 6px;
        }
        .stat-value {
            font-size: 1.6rem;
            font-weight: 700;
        }
        .stat-value.positive { color: var(--success); }
        .stat-value.negative { color: var(--warning); }
        /* Table */
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }
        thead th {
            background: var(--primary);
            color: white;
            padding: 10px 12px;
            text-align: left;
            font-weight: 600;
            font-size: 0.85rem;
        }
        tbody td {
            padding: 8px 12px;
            border-bottom: 1px solid var(--border);
        }
        tbody tr:hover { background: #F0F4F8; }
        .group-fixed { background: #E2EFDA; }
        .group-variable { background: #FCE4D6; }
        .group-special { background: #E4D5F0; }
        .amount { text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; }
        .pct { text-align: right; color: var(--text-light); }
        /* Forms */
        .form-group {
            margin-bottom: 16px;
        }
        .form-group label {
            display: block;
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--text-light);
            margin-bottom: 5px;
        }
        .form-group input, .form-group select, .form-group textarea {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 0.95rem;
            transition: border 0.2s;
        }
        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(31,78,121,0.1);
        }
        .form-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }
        .btn {
            display: inline-block;
            padding: 10px 24px;
            border: none;
            border-radius: 6px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
        }
        .btn-primary { background: var(--primary); color: white; }
        .btn-primary:hover { background: #163D5E; }
        .btn-success { background: var(--success); color: white; }
        .btn-success:hover { background: #004D00; }
        .btn-danger { background: var(--warning); color: white; }
        .btn-danger:hover { background: #7A0005; }
        .btn-orange { background: var(--orange); color: white; }
        .btn-orange:hover { background: #D06820; }
        .btn-sm { padding: 5px 12px; font-size: 0.8rem; }
        /* Flash */
        .flash {
            padding: 12px 16px;
            border-radius: 6px;
            margin-bottom: 16px;
            font-size: 0.9rem;
        }
        .flash-success { background: var(--success-bg); color: var(--success); }
        .flash-error { background: var(--warning-bg); color: var(--warning); }
        /* Upload Area */
        .upload-area {
            border: 2px dashed var(--border);
            border-radius: 10px;
            padding: 40px;
            text-align: center;
            transition: all 0.3s;
            cursor: pointer;
            background: #FAFBFC;
        }
        .upload-area:hover, .upload-area.dragover {
            border-color: var(--primary);
            background: var(--primary-light);
        }
        .upload-area p { color: var(--text-light); margin-top: 8px; font-size: 0.85rem; }
        .upload-icon { font-size: 3rem; }
        /* OCR Result */
        .ocr-result {
            background: #F8F9FA;
            border-left: 4px solid var(--primary);
            padding: 16px;
            border-radius: 0 6px 6px 0;
            margin: 16px 0;
        }
        .ocr-field {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
            font-size: 0.9rem;
        }
        .ocr-label {
            font-weight: 600;
            min-width: 80px;
            color: var(--primary);
        }
        .compression-info {
            background: var(--success-bg);
            color: var(--success);
            padding: 10px 14px;
            border-radius: 6px;
            font-size: 0.85rem;
            margin: 10px 0;
        }
        /* Badge */
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .badge-over { background: var(--warning-bg); color: var(--warning); }
        .badge-ok { background: var(--success-bg); color: var(--success); }
        .badge-warn { background: #FFEB9C; color: #9C6500; }
        .badge-spare { background: var(--primary-light); color: var(--primary); }
        /* Progress bar */
        .progress-bar {
            background: #E8E8E8;
            border-radius: 10px;
            height: 8px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            border-radius: 10px;
            transition: width 0.3s;
        }
        .progress-ok { background: var(--success); }
        .progress-warn { background: var(--orange); }
        .progress-over { background: var(--warning); }
        /* Chart placeholder using CSS */
        .bar-chart {
            display: flex;
            align-items: flex-end;
            gap: 4px;
            height: 120px;
            padding-top: 10px;
        }
        .bar-item {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
        }
        .bar {
            width: 100%;
            max-width: 40px;
            border-radius: 4px 4px 0 0;
            transition: height 0.5s;
        }
        .bar-label {
            font-size: 0.65rem;
            color: var(--text-light);
            text-align: center;
            writing-mode: vertical-rl;
            max-height: 60px;
            overflow: hidden;
        }
        /* Responsive */
        @media (max-width: 768px) {
            .nav-inner { flex-direction: column; }
            .nav-links { width: 100%; justify-content: center; }
            .form-row { grid-template-columns: 1fr; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <nav>
        <div class="nav-inner">
            <div class="nav-brand">💰 家計Pro</div>
            <div class="nav-links">
                <a href="/" class="{{ 'active' if active_page == 'dashboard' }}">ダッシュボード</a>
                <a href="/expenses" class="{{ 'active' if active_page == 'expenses' }}">支出一覧</a>
                <a href="/add" class="{{ 'active' if active_page == 'add' }}">支出追加</a>
                <a href="/add-income" class="{{ 'active' if active_page == 'add_income' }}">収入追加</a>
                <a href="/receipt" class="{{ 'active' if active_page == 'receipt' }}">レシート読取</a>
                <a href="/budget" class="{{ 'active' if active_page == 'budget' }}">予算管理</a>
                <a href="/analysis" class="{{ 'active' if active_page == 'analysis' }}">分析</a>
                <a href="/report" class="{{ 'active' if active_page == 'report' }}">Excel出力</a>
            </div>
        </div>
    </nav>
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
            <div class="flash flash-{{ category }}">{{ message }}</div>
            {% endfor %}
        {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
</body>
</html>
"""

# ============================================================
#  Routes
# ============================================================

@app.route("/")
def dashboard():
    today = date.today()
    y, m = today.year, today.month

    # クエリパラメータで年月指定
    y = int(request.args.get("year", y))
    m = int(request.args.get("month", m))

    summary = monthly_summary(y, m)
    bva = budget_vs_actual(y, m)
    ce = cost_effectiveness_analysis(y, m)
    trend = multi_month_trend(y, 6, end_month=m)

    template = BASE_HTML.replace("{% block content %}{% endblock %}", """
    <h1>ダッシュボード - {{ year }}年{{ month }}月</h1>

    <!-- 月ナビ -->
    <div style="margin-bottom:20px; display:flex; gap:10px; align-items:center;">
        <a href="/?year={{ prev_year }}&month={{ prev_month }}" class="btn btn-primary btn-sm">&laquo; 前月</a>
        <span style="font-weight:600;">{{ year }}年{{ month }}月</span>
        <a href="/?year={{ next_year }}&month={{ next_month }}" class="btn btn-primary btn-sm">翌月 &raquo;</a>
        <a href="/" class="btn btn-orange btn-sm" style="margin-left:auto;">今月</a>
        <a href="/add" class="btn btn-success btn-sm">+ 支出追加</a>
    </div>

    <!-- 統計カード -->
    <div class="stats-grid">
        <div class="stat-card income">
            <div class="stat-label">総収入</div>
            <div class="stat-value positive">{{ "{:,}".format(summary.total_income) }}円</div>
        </div>
        <div class="stat-card expense">
            <div class="stat-label">総支出</div>
            <div class="stat-value negative">{{ "{:,}".format(summary.total_expense) }}円</div>
        </div>
        <div class="stat-card balance">
            <div class="stat-label">収支</div>
            <div class="stat-value {{ 'positive' if summary.balance >= 0 else 'negative' }}">
                {{ "{:,}".format(summary.balance) }}円
            </div>
        </div>
        <div class="stat-card saving">
            <div class="stat-label">貯蓄率</div>
            <div class="stat-value">{{ summary.saving_rate }}%</div>
        </div>
    </div>

    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px;">
        <!-- カテゴリ別支出 -->
        <div class="card">
            <h2>カテゴリ別支出</h2>
            {% if summary.by_category %}
            <table>
                <thead><tr><th>カテゴリ</th><th>分類</th><th style="text-align:right">金額</th><th style="text-align:right">構成比</th></tr></thead>
                <tbody>
                {% for cat, info in sorted_categories %}
                <tr class="group-{{ 'fixed' if info.group == '固定費' else ('variable' if info.group == '変動費' else 'special') }}">
                    <td>{{ cat }}</td>
                    <td>{{ info.group }}</td>
                    <td class="amount">{{ "{:,}".format(info.amount) }}円</td>
                    <td class="pct">{{ "%.1f"|format(info.amount / summary.total_expense * 100 if summary.total_expense > 0 else 0) }}%</td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p style="color:var(--text-light);">データがありません。<a href="/add" style="color:var(--primary);">支出追加</a>から登録してください。</p>
            {% endif %}
        </div>

        <!-- 分類別＆効率 -->
        <div>
            <div class="card">
                <h2>分類別合計</h2>
                {% for grp, amt in summary.by_group.items() %}
                <div style="display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--border);">
                    <span style="font-weight:600;">{{ grp }}</span>
                    <span class="amount">{{ "{:,}".format(amt) }}円</span>
                </div>
                {% endfor %}
            </div>
            <div class="card">
                <h2>費用対効果</h2>
                <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                    <span>効率スコア</span>
                    <span style="font-weight:700; color:var(--primary);">{{ ce.efficiency_score }}%</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
                    <span>節約可能額</span>
                    <span style="font-weight:700; color:var(--warning);">{{ "{:,}".format(ce.savings_potential) }}円</span>
                </div>
                {% for item in ce.waste_items[:3] %}
                <div style="background:var(--warning-bg); padding:8px; border-radius:4px; margin-bottom:6px; font-size:0.85rem;">
                    ⚠️ {{ item.suggestion }}
                </div>
                {% endfor %}
            </div>
        </div>
    </div>

    <!-- 月次トレンド -->
    <div class="card">
        <h2>月次トレンド（過去6ヶ月）</h2>
        <div class="bar-chart" style="height:160px;">
            {% for t in trend %}
            <div class="bar-item">
                <div style="font-size:0.7rem; color:var(--text-light);">{{ "{:,}".format(t.total_expense) }}</div>
                <div class="bar" style="height:{{ (t.total_expense / max_expense * 100) if max_expense > 0 else 0 }}%; background: {{ 'var(--warning)' if t.balance < 0 else 'var(--primary)' }};"></div>
                <div class="bar-label">{{ t.month }}月</div>
            </div>
            {% endfor %}
        </div>
    </div>
    """)

    prev_m = m - 1
    prev_y = y
    if prev_m < 1:
        prev_m = 12
        prev_y -= 1
    next_m = m + 1
    next_y = y
    if next_m > 12:
        next_m = 1
        next_y += 1

    sorted_cats = sorted(
        summary["by_category"].items(),
        key=lambda x: x[1]["amount"], reverse=True,
    )
    max_expense = max((t["total_expense"] for t in trend), default=1)

    return render_template_string(
        template,
        page_title="ダッシュボード",
        active_page="dashboard",
        year=y, month=m,
        prev_year=prev_y, prev_month=prev_m,
        next_year=next_y, next_month=next_m,
        summary=summary,
        sorted_categories=sorted_cats,
        ce=ce,
        trend=trend,
        max_expense=max_expense,
    )






@app.route("/expenses")
def expenses_list():
    today = date.today()
    y = int(request.args.get("year", today.year))
    m = int(request.args.get("month", today.month))

    expenses = get_expenses(y, m)

    template = BASE_HTML.replace("{% block content %}{% endblock %}", """
    <h1>支出一覧 - {{ year }}年{{ month }}月</h1>
    <div style="margin-bottom:16px; display:flex; gap:10px; align-items:center;">
        <a href="/expenses?year={{ prev_year }}&month={{ prev_month }}" class="btn btn-primary btn-sm">&laquo; 前月</a>
        <span style="font-weight:600;">{{ year }}年{{ month }}月</span>
        <a href="/expenses?year={{ next_year }}&month={{ next_month }}" class="btn btn-primary btn-sm">翌月 &raquo;</a>
        <a href="/add" class="btn btn-success btn-sm" style="margin-left:auto;">+ 支出追加</a>
    </div>
    <div class="card">
        {% if rows|length > 0 %}
        <table>
            <thead><tr>
                <th>ID</th><th>日付</th><th>カテゴリ</th><th>分類</th>
                <th style="text-align:right">金額</th><th>メモ</th><th></th>
            </tr></thead>
            <tbody>
            {% for row in rows %}
            <tr class="group-{{ 'fixed' if row.group == '固定費' else ('variable' if row.group == '変動費' else 'special') }}">
                <td>{{ row.id }}</td>
                <td>{{ row.date_str }}</td>
                <td>{{ row.category }}</td>
                <td>{{ row.group }}</td>
                <td class="amount">{{ "{:,}".format(row.amount) }}円</td>
                <td>{{ row.memo }}</td>
                <td><a href="/delete/{{ row.id }}?year={{ year }}&month={{ month }}" class="btn btn-danger btn-sm" onclick="return confirm('削除しますか？')">削除</a></td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        <div style="text-align:right; margin-top:12px; font-size:1.1rem; font-weight:700;">
            合計: {{ "{:,}".format(total) }}円 ({{ rows|length }}件)
        </div>
        {% else %}
        <p style="color:var(--text-light);">この月の支出データはありません。</p>
        {% endif %}
    </div>
    """)

    prev_m = m - 1
    prev_y = y
    if prev_m < 1: prev_m, prev_y = 12, y - 1
    next_m = m + 1
    next_y = y
    if next_m > 12: next_m, next_y = 1, y + 1

    rows = []
    total = 0
    if not expenses.empty:
        for _, row in expenses.iterrows():
            rows.append({
                "id": row["id"],
                "date_str": row["date"].strftime("%Y-%m-%d"),
                "category": row["category"],
                "group": row.get("group", ""),
                "amount": int(row["amount"]),
                "memo": row.get("memo", ""),
            })
        total = int(expenses["amount"].sum())

    return render_template_string(
        template,
        page_title="支出一覧",
        active_page="expenses",
        year=y, month=m,
        prev_year=prev_y, prev_month=prev_m,
        next_year=next_y, next_month=next_m,
        rows=rows, total=total,
    )


@app.route("/delete/<int:entry_id>")
def delete_entry(entry_id):
    y = request.args.get("year", date.today().year)
    m = request.args.get("month", date.today().month)
    if delete_expense(entry_id):
        flash(f"ID {entry_id} の支出を削除しました。", "success")
    else:
        flash(f"ID {entry_id} が見つかりません。", "error")
    return redirect(f"/expenses?year={y}&month={m}")


@app.route("/add", methods=["GET", "POST"])
def add_expense_page():
    if request.method == "POST":
        try:
            date_str = request.form.get("date") or date.today().strftime("%Y-%m-%d")
            category = request.form["category"]
            amount = int(request.form["amount"])
            memo = request.form.get("memo", "")
            entry = add_expense(date_str, category, amount, memo)
            flash(f"追加: {entry['date']} {category} {amount:,}円 {memo}", "success")
            return redirect(url_for("add_expense_page"))
        except Exception as e:
            flash(f"エラー: {e}", "error")

    template = BASE_HTML.replace("{% block content %}{% endblock %}", """
    <h1>支出追加</h1>
    <div class="card">
        <form method="POST">
            <div class="form-row">
                <div class="form-group">
                    <label>日付</label>
                    <input type="date" name="date" value="{{ today }}">
                </div>
                <div class="form-group">
                    <label>カテゴリ</label>
                    <select name="category" required>
                        {% for group_name, cats in categories.items() %}
                        <optgroup label="{{ group_name }}">
                            {% for cat in cats %}
                            <option value="{{ cat }}">{{ cat }}</option>
                            {% endfor %}
                        </optgroup>
                        {% endfor %}
                    </select>
                </div>
                <div class="form-group">
                    <label>金額（円）</label>
                    <input type="number" name="amount" min="1" required placeholder="例: 1500">
                </div>
            </div>
            <div class="form-group">
                <label>メモ</label>
                <input type="text" name="memo" placeholder="スーパーで買い物 等">
            </div>
            <button type="submit" class="btn btn-primary">追加する</button>
        </form>
    </div>
    """)

    return render_template_string(
        template,
        page_title="支出追加",
        active_page="add",
        today=date.today().strftime("%Y-%m-%d"),
        categories=CATEGORIES,
    )


@app.route("/add-income", methods=["GET", "POST"])
def add_income_page():
    if request.method == "POST":
        try:
            date_str = request.form.get("date") or date.today().strftime("%Y-%m-%d")
            category = request.form["category"]
            amount = int(request.form["amount"])
            memo = request.form.get("memo", "")
            entry = add_income(date_str, category, amount, memo)
            flash(f"追加: {entry['date']} {category} {amount:,}円 {memo}", "success")
            return redirect(url_for("add_income_page"))
        except Exception as e:
            flash(f"エラー: {e}", "error")

    template = BASE_HTML.replace("{% block content %}{% endblock %}", """
    <h1>収入追加</h1>
    <div class="card">
        <form method="POST">
            <div class="form-row">
                <div class="form-group">
                    <label>日付</label>
                    <input type="date" name="date" value="{{ today }}">
                </div>
                <div class="form-group">
                    <label>カテゴリ</label>
                    <select name="category" required>
                        {% for cat in income_categories %}
                        <option value="{{ cat }}">{{ cat }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="form-group">
                    <label>金額（円）</label>
                    <input type="number" name="amount" min="1" required placeholder="例: 300000">
                </div>
            </div>
            <div class="form-group">
                <label>メモ</label>
                <input type="text" name="memo" placeholder="1月分給与 等">
            </div>
            <button type="submit" class="btn btn-success">追加する</button>
        </form>
    </div>
    """)

    return render_template_string(
        template,
        page_title="収入追加",
        active_page="add_income",
        today=date.today().strftime("%Y-%m-%d"),
        income_categories=list(INCOME_CATEGORIES.keys()),
    )


@app.route("/receipt", methods=["GET", "POST"])
def receipt_page():
    ocr_result = None
    compression_info = None
    error_detail = None

    if request.method == "POST":
        if "receipt_image" in request.files:
            file = request.files["receipt_image"]
            if file.filename:
                import traceback

                # Step 1: 画像読み込み
                try:
                    image_bytes = file.read()
                    filename = file.filename
                    if not image_bytes:
                        error_detail = "ファイルが空です。画像を選び直してください。"
                        flash(error_detail, "error")
                except Exception as e:
                    error_detail = f"画像読み込みエラー: {e}\n{traceback.format_exc()}"
                    flash(f"画像読み込みエラー: {e}", "error")
                    image_bytes = None

                # Step 2: 画像圧縮
                if image_bytes and not error_detail:
                    try:
                        comp = compress_image(image_bytes, filename)
                        compression_info = comp
                    except Exception as e:
                        error_detail = f"画像圧縮エラー: {e}\n{traceback.format_exc()}"
                        flash(f"画像圧縮エラー: {e}", "error")
                        comp = None

                # Step 3: 保存
                if image_bytes and compression_info and not error_detail:
                    try:
                        ext = os.path.splitext(filename)[1].lower()
                        if ext not in (".jpg", ".jpeg", ".png"):
                            ext = ".jpg"
                        save_name = f"receipt_{uuid.uuid4().hex[:8]}{ext}"
                        save_path = os.path.join(UPLOAD_DIR, save_name)
                        with open(save_path, "wb") as f:
                            f.write(comp["bytes"])
                    except Exception as e:
                        error_detail = f"ファイル保存エラー: {e}\n{traceback.format_exc()}"
                        flash(f"ファイル保存エラー: {e}", "error")
                        save_path = None

                # Step 4: OCR実行
                if compression_info and not error_detail:
                    try:
                        ocr_result = ocr_receipt(comp["image"], save_path)
                        ocr_result["saved_path"] = save_path if save_path else ""
                        ocr_result["saved_name"] = save_name if save_path else ""
                    except Exception as e:
                        error_detail = f"OCRエラー: {e}\n{traceback.format_exc()}"
                        flash(f"OCRエラー: {e}", "error")
            else:
                error_detail = "ファイルが選択されていません。"
                flash("ファイルが選択されていません。", "error")

        elif "register" in request.form:
            # OCR結果を支出として登録
            try:
                date_str = request.form.get("date") or date.today().strftime("%Y-%m-%d")
                category = request.form["category"]
                amount = int(request.form["amount"])
                store = request.form.get("store", "")
                payment = request.form.get("payment", "")
                memo = f"{store} ({payment})" if payment else store
                entry = add_expense(date_str, category, amount, memo)
                flash(f"登録しました: {entry['date']} {category} {amount:,}円 {memo}", "success")
                return redirect(url_for("receipt_page"))
            except Exception as e:
                flash(f"登録エラー: {e}", "error")

    template = BASE_HTML.replace("{% block content %}{% endblock %}", """
    <h1>レシート読取（OCR）</h1>

    <!-- エラー表示（大きく目立つ） -->
    {% if error_detail %}
    <div class="card" style="border-left:5px solid var(--warning); background:#FFF5F5;">
        <h2 style="color:var(--warning);">エラーが発生しました</h2>
        <pre style="padding:12px; background:#FFF0F0; border-radius:6px; font-size:0.85rem; white-space:pre-wrap; color:#333;">{{ error_detail }}</pre>
    </div>
    {% endif %}

    <div class="card">
        <h2>レシート画像をアップロード</h2>
        <form method="POST" enctype="multipart/form-data" id="uploadForm">
            <div class="upload-area" id="dropZone" onclick="document.getElementById('fileInput').click();">
                <div class="upload-icon">📷</div>
                <div style="font-size:1.1rem; font-weight:600; margin:8px 0;">
                    クリックまたはドラッグ&ドロップ
                </div>
                <p>JPEG / PNG 対応 ・ 自動圧縮あり</p>
                <input type="file" name="receipt_image" id="fileInput" accept="image/jpeg,image/png"
                       style="display:none" onchange="document.getElementById('uploadForm').submit();">
            </div>
        </form>
    </div>

    {% if compression_info %}
    <div class="compression-info">
        📦 画像圧縮: {{ compression_info.format }} |
        {{ "%.1f"|format(compression_info.original_size / 1024) }}KB →
        {{ "%.1f"|format(compression_info.compressed_size / 1024) }}KB
        ({{ compression_info.ratio }}%削減) |
        {{ compression_info.dimensions[0] }}×{{ compression_info.dimensions[1] }}px
    </div>
    {% endif %}

    {% if ocr_result %}
    <div class="card">
        <h2>読み取り結果</h2>

        <!-- OCRモード表示 -->
        <div style="margin-bottom:12px; padding:8px 12px; background:var(--primary-light); border-radius:6px; font-size:0.85rem;">
            🔍 読取モード: <strong>{{ ocr_result.ocr_method }}</strong>
            {% if ocr_result.needs_manual_input %}
            <span style="color:var(--orange); margin-left:8px;">※ OCRが使えないため、手動入力してください</span>
            {% endif %}
        </div>

        <!-- OCRエラーがある場合の警告 -->
        {% if ocr_result.ocr_error %}
        <div style="background:#FFF8E1; border-left:4px solid var(--orange); padding:12px; border-radius:0 6px 6px 0; margin-bottom:12px; font-size:0.85rem;">
            <strong style="color:var(--orange);">⚠️ OCR注意:</strong>
            <pre style="margin-top:6px; white-space:pre-wrap; color:#555;">{{ ocr_result.ocr_error }}</pre>
        </div>
        {% endif %}

        <div class="ocr-result">
            <div class="ocr-field"><span class="ocr-label">店舗名:</span> {{ ocr_result.store_name or '（不明）' }}</div>
            <div class="ocr-field"><span class="ocr-label">日付:</span> {{ ocr_result.date }}</div>
            <div class="ocr-field"><span class="ocr-label">合計金額:</span> <strong>{{ "{:,}".format(ocr_result.total) }}円</strong></div>
            <div class="ocr-field"><span class="ocr-label">カテゴリ:</span> {{ ocr_result.category_guess }}</div>
            <div class="ocr-field"><span class="ocr-label">決済方法:</span> {{ ocr_result.payment_method or '（不明）' }}</div>
        </div>

        {% if ocr_result.line_items %}
        <div style="margin:12px 0;">
            <strong>品目 ({{ ocr_result.line_items|length }}件):</strong>
            <table style="margin-top:8px;">
                <thead><tr><th>品名</th><th style="text-align:right">金額</th></tr></thead>
                <tbody>
                {% for item in ocr_result.line_items[:10] %}
                <tr><td>{{ item.name }}</td><td class="amount">{{ "{:,}".format(item.amount) }}円</td></tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}

        <!-- 登録フォーム (OCRありでもなしでも表示) -->
        <form method="POST" style="margin-top:16px; padding-top:16px; border-top:1px solid var(--border);">
            <input type="hidden" name="register" value="1">
            <p style="font-size:0.85rem; color:var(--text-light); margin-bottom:12px;">
                {% if ocr_result.needs_manual_input %}
                画像は保存されました。以下のフォームに手動で入力して登録できます。
                {% else %}
                読み取り結果を確認・修正して登録してください。
                {% endif %}
            </p>
            <div class="form-row">
                <div class="form-group">
                    <label>日付</label>
                    <input type="date" name="date" value="{{ ocr_result.date }}">
                </div>
                <div class="form-group">
                    <label>カテゴリ</label>
                    <select name="category">
                        {% for group_name, cats in categories.items() %}
                        <optgroup label="{{ group_name }}">
                            {% for cat in cats %}
                            <option value="{{ cat }}" {{ 'selected' if cat == ocr_result.category_guess }}>{{ cat }}</option>
                            {% endfor %}
                        </optgroup>
                        {% endfor %}
                    </select>
                </div>
                <div class="form-group">
                    <label>金額（円）</label>
                    <input type="number" name="amount" value="{{ ocr_result.total if ocr_result.total > 0 else '' }}" min="1" required
                           placeholder="レシートの合計金額を入力">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>店舗名</label>
                    <input type="text" name="store" value="{{ ocr_result.store_name }}" placeholder="例: セブンイレブン">
                </div>
                <div class="form-group">
                    <label>決済方法</label>
                    <input type="text" name="payment" value="{{ ocr_result.payment_method }}" placeholder="例: 現金, PayPay">
                </div>
            </div>
            <button type="submit" class="btn btn-success">この内容で支出登録する</button>
        </form>
    </div>

    <!-- OCR Raw Text (折りたたみ) -->
    <details class="card" style="cursor:pointer;">
        <summary style="font-weight:600; color:var(--primary);">デバッグ情報</summary>
        <pre style="margin-top:12px; padding:12px; background:#F0F0F0; border-radius:6px; font-size:0.8rem; white-space:pre-wrap; max-height:300px; overflow:auto;">{{ ocr_result.raw_text }}</pre>
    </details>
    {% endif %}

    <script>
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    ['dragenter','dragover'].forEach(e => {
        dropZone.addEventListener(e, (ev) => { ev.preventDefault(); dropZone.classList.add('dragover'); });
    });
    ['dragleave','drop'].forEach(e => {
        dropZone.addEventListener(e, (ev) => { ev.preventDefault(); dropZone.classList.remove('dragover'); });
    });
    dropZone.addEventListener('drop', (ev) => {
        fileInput.files = ev.dataTransfer.files;
        document.getElementById('uploadForm').submit();
    });
    </script>
    """)

    return render_template_string(
        template,
        page_title="レシート読取",
        active_page="receipt",
        ocr_result=ocr_result,
        compression_info=compression_info,
        error_detail=error_detail,
        categories=CATEGORIES,
    )


@app.route("/budget", methods=["GET", "POST"])
def budget_page():
    today = date.today()
    y = int(request.args.get("year", today.year))
    m = int(request.args.get("month", today.month))

    if request.method == "POST":
        new_budgets = {}
        for cat in get_all_expense_categories():
            val = request.form.get(f"budget_{cat}", "0")
            try:
                new_budgets[cat] = int(val) if val else 0
            except ValueError:
                new_budgets[cat] = 0
        set_budgets(new_budgets, y, m)
        flash("予算を更新しました。", "success")
        return redirect(f"/budget?year={y}&month={m}")

    budgets = get_budgets(y, m)
    bva = budget_vs_actual(y, m)

    template = BASE_HTML.replace("{% block content %}{% endblock %}", """
    <h1>予算管理 - {{ year }}年{{ month }}月</h1>
    <div class="card">
        <h2>予算 vs 実績</h2>
        <table>
            <thead><tr>
                <th>カテゴリ</th><th>分類</th><th style="text-align:right">予算</th>
                <th style="text-align:right">実績</th><th style="text-align:right">差額</th>
                <th style="text-align:right">達成率</th><th>状態</th><th>進捗</th>
            </tr></thead>
            <tbody>
            {% for item in bva %}
            {% if item.budget > 0 or item.actual > 0 %}
            <tr>
                <td>{{ item.category }}</td>
                <td>{{ item.group }}</td>
                <td class="amount">{{ "{:,}".format(item.budget) }}円</td>
                <td class="amount">{{ "{:,}".format(item.actual) }}円</td>
                <td class="amount" style="color:{{ 'var(--success)' if item.diff >= 0 else 'var(--warning)' }}">
                    {{ "{:,}".format(item.diff) }}円
                </td>
                <td class="pct">{{ item.rate }}%</td>
                <td>
                    <span class="badge badge-{{ 'over' if item.status in ['大幅超過','超過'] else ('ok' if item.status == '適正' else 'spare') }}">
                        {{ item.status }}
                    </span>
                </td>
                <td style="min-width:80px;">
                    <div class="progress-bar">
                        <div class="progress-fill progress-{{ 'over' if item.rate > 100 else ('warn' if item.rate > 80 else 'ok') }}"
                             style="width:{{ [item.rate, 100]|min }}%;"></div>
                    </div>
                </td>
            </tr>
            {% endif %}
            {% endfor %}
            </tbody>
        </table>
    </div>

    <div class="card">
        <h2>予算設定</h2>
        <form method="POST">
            <table>
                <thead><tr><th>カテゴリ</th><th>分類</th><th style="text-align:right">予算額（円）</th></tr></thead>
                <tbody>
                {% for cat in all_categories %}
                <tr>
                    <td>{{ cat }}</td>
                    <td>{{ get_group(cat) }}</td>
                    <td style="text-align:right;">
                        <input type="number" name="budget_{{ cat }}" value="{{ budgets.get(cat, 0) }}"
                               min="0" style="width:120px; text-align:right;">
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
            <div style="margin-top:16px;">
                <button type="submit" class="btn btn-primary">予算を保存</button>
            </div>
        </form>
    </div>
    """)

    return render_template_string(
        template,
        page_title="予算管理",
        active_page="budget",
        year=y, month=m,
        budgets=budgets,
        bva=bva,
        all_categories=get_all_expense_categories(),
        get_group=get_category_group,
    )


@app.route("/analysis")
def analysis_page():
    today = date.today()
    y = int(request.args.get("year", today.year))
    m = int(request.args.get("month", today.month))

    ce = cost_effectiveness_analysis(y, m)
    anomalies = anomaly_detection(y, m)

    template = BASE_HTML.replace("{% block content %}{% endblock %}", """
    <h1>分析 - {{ year }}年{{ month }}月</h1>

    <div style="margin-bottom:16px; display:flex; gap:10px;">
        <a href="/analysis?year={{ prev_year }}&month={{ prev_month }}" class="btn btn-primary btn-sm">&laquo; 前月</a>
        <span style="font-weight:600;">{{ year }}年{{ month }}月</span>
        <a href="/analysis?year={{ next_year }}&month={{ next_month }}" class="btn btn-primary btn-sm">翌月 &raquo;</a>
    </div>

    <div class="stats-grid" style="grid-template-columns: repeat(3, 1fr);">
        <div class="stat-card">
            <div class="stat-label">効率スコア</div>
            <div class="stat-value" style="color:var(--primary);">{{ ce.efficiency_score }}%</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">節約可能額</div>
            <div class="stat-value negative">{{ "{:,}".format(ce.savings_potential) }}円</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">異常値検出数</div>
            <div class="stat-value" style="color:var(--orange);">{{ anomalies|length }}件</div>
        </div>
    </div>

    <!-- 費用対効果 -->
    <div class="card">
        <h2>無駄な支出の検出</h2>
        {% if ce.waste_items %}
        <table>
            <thead><tr><th>カテゴリ</th><th style="text-align:right">金額</th><th style="text-align:center">必要度</th><th>改善提案</th></tr></thead>
            <tbody>
            {% for item in ce.waste_items %}
            <tr style="background:var(--warning-bg);">
                <td>{{ item.category }}</td>
                <td class="amount">{{ "{:,}".format(item.amount) }}円</td>
                <td style="text-align:center;">{{ item.necessity_score }}/10</td>
                <td style="font-size:0.85rem;">{{ item.suggestion }}</td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p style="color:var(--success);">無駄な支出は検出されませんでした。</p>
        {% endif %}
    </div>

    <!-- 異常値検出 -->
    <div class="card">
        <h2>異常値検出（Z-score 1.5σ以上）</h2>
        {% if anomalies %}
        <table>
            <thead><tr><th>カテゴリ</th><th style="text-align:right">今月</th><th style="text-align:right">平均</th>
            <th style="text-align:right">標準偏差</th><th style="text-align:right">Z値</th><th>方向</th></tr></thead>
            <tbody>
            {% for a in anomalies %}
            <tr style="background:{{ 'var(--warning-bg)' if a.direction == '増加' else 'var(--success-bg)' }};">
                <td>{{ a.category }}</td>
                <td class="amount">{{ "{:,}".format(a.current) }}円</td>
                <td class="amount">{{ "{:,}".format(a.average) }}円</td>
                <td class="amount">{{ "{:,}".format(a.std_dev) }}円</td>
                <td class="amount">{{ a.z_score }}</td>
                <td>{{ '📈' if a.direction == '増加' else '📉' }} {{ a.direction }}</td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p style="color:var(--success);">統計的な異常値は検出されませんでした。</p>
        {% endif %}
    </div>
    """)

    prev_m, prev_y = (m - 1, y) if m > 1 else (12, y - 1)
    next_m, next_y = (m + 1, y) if m < 12 else (1, y + 1)

    return render_template_string(
        template,
        page_title="分析",
        active_page="analysis",
        year=y, month=m,
        prev_year=prev_y, prev_month=prev_m,
        next_year=next_y, next_month=next_m,
        ce=ce, anomalies=anomalies,
    )


@app.route("/report")
def report_page():
    today = date.today()
    y = int(request.args.get("year", today.year))
    m = int(request.args.get("month", today.month))

    template = BASE_HTML.replace("{% block content %}{% endblock %}", """
    <h1>Excelレポート出力</h1>
    <div class="card">
        <h2>レポート生成</h2>
        <p style="margin-bottom:16px; color:var(--text-light);">7シート構成のExcelレポートを生成します（ダッシュボード、支出明細、収入明細、予算vs実績、月次トレンド、費用対効果、異常値検出）</p>
        <a href="/generate-report?year={{ year }}&month={{ month }}" class="btn btn-primary">
            {{ year }}年{{ month }}月のレポートを生成
        </a>
    </div>
    """)

    return render_template_string(
        template,
        page_title="Excel出力",
        active_page="report",
        year=y, month=m,
    )


@app.route("/generate-report")
def generate_report():
    today = date.today()
    y = int(request.args.get("year", today.year))
    m = int(request.args.get("month", today.month))

    output_path = os.path.join(REPORT_DIR, f"家計Pro_レポート_{y}{m:02d}.xlsx")
    try:
        generate_full_report(y, m, output_path)
        flash(f"レポートを生成しました: 家計Pro_レポート_{y}{m:02d}.xlsx", "success")
    except Exception as e:
        flash(f"レポート生成エラー: {e}", "error")
    return redirect(url_for("report_page"))


# ============================================================
#  API endpoints (JSON)
# ============================================================
@app.route("/api/summary/<int:year>/<int:month>")
def api_summary(year, month):
    return jsonify(monthly_summary(year, month))


@app.route("/api/expenses/<int:year>/<int:month>")
def api_expenses(year, month):
    expenses = get_expenses(year, month)
    if expenses.empty:
        return jsonify([])
    expenses["date"] = expenses["date"].dt.strftime("%Y-%m-%d")
    return jsonify(expenses.to_dict("records"))


# ============================================================
#  Main
# ============================================================
if __name__ == "__main__":
    port = 8080
    print("=" * 50)
    print(f"  家計Pro Web - http://localhost:{port}")
    print("  停止: Ctrl+C")
    print("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=True)
