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
#  HEIC/HEIF サポート登録 (iPhone標準フォーマット)
#  pillow-heif が入っていれば Pillow で .heic を直接開ける。
#  未導入でも他形式は通常通り動作するよう、失敗は黙って無視する。
# ============================================================
HEIC_SUPPORTED = False
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except Exception:
    HEIC_SUPPORTED = False

HEIC_EXTS = (".heic", ".heif")


# ============================================================
#  Image Compression Utility
# ============================================================
def compress_image(image_bytes, filename, max_size_kb=500, max_dimension=1600):
    """
    アップロード画像を圧縮して小さくする。
    - JPEG/PNG: そのままの形式を維持して圧縮
    - HEIC/HEIF: JPEG へ変換（写真用途でサイズ最小かつ高画質、OCR互換）
    - max_size_kb: 目標最大ファイルサイズ(KB)
    - max_dimension: 最大辺のピクセル数
    """
    from PIL import Image

    ext = os.path.splitext(filename)[1].lower()
    is_heic = ext in HEIC_EXTS

    if is_heic and not HEIC_SUPPORTED:
        raise RuntimeError(
            "HEIC画像を読み込むには pillow-heif が必要です。"
            "`pip install pillow-heif` を実行するか、JPEG/PNGで再アップロードしてください。"
        )

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

    # 形式判定: PNGはPNG維持、それ以外(JPEG/HEIC等)はJPEGへ
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
#  Receipt OCR Engine (v2 - 改善版)
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


def _preprocess_receipt_image(image):
    """
    レシート画像の前処理 - 複数戦略を試して最良の結果を返す
    感熱紙レシートに最適化
    """
    from PIL import Image, ImageFilter, ImageEnhance, ImageOps
    import numpy as np

    results = []

    # 元画像をグレースケールに
    gray = image.convert("L")

    # 解像度が低い場合はアップスケール（OCR精度向上）
    w, h = gray.size
    if max(w, h) < 1500:
        scale = 1500 / max(w, h)
        gray = gray.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    # --- 戦略1: コントラスト強化 + Otsu風しきい値 ---
    try:
        img1 = gray.copy()
        enhancer = ImageEnhance.Contrast(img1)
        img1 = enhancer.enhance(1.8)
        enhancer = ImageEnhance.Sharpness(img1)
        img1 = enhancer.enhance(1.5)
        # ヒストグラムからOtsu風しきい値を計算
        hist = img1.histogram()
        pixels = np.array(hist)
        total = pixels.sum()
        if total > 0:
            cumsum = np.cumsum(pixels)
            cumsum_val = np.cumsum(pixels * np.arange(256))
            mean_total = cumsum_val[-1] / total
            max_var = 0
            threshold = 128
            for t in range(1, 255):
                w0 = cumsum[t]
                w1 = total - w0
                if w0 == 0 or w1 == 0:
                    continue
                m0 = cumsum_val[t] / w0
                m1 = (cumsum_val[-1] - cumsum_val[t]) / w1
                var = w0 * w1 * (m0 - m1) ** 2
                if var > max_var:
                    max_var = var
                    threshold = t
            img1 = img1.point(lambda x: 0 if x < threshold else 255)
        else:
            img1 = img1.point(lambda x: 0 if x < 128 else 255)
        results.append(("otsu", img1))
    except Exception:
        pass

    # --- 戦略2: 適応的しきい値（ブロックごと） ---
    try:
        img2 = gray.copy()
        enhancer = ImageEnhance.Contrast(img2)
        img2 = enhancer.enhance(1.5)
        # ガウスぼかしで局所平均を計算し、適応的二値化
        blurred = img2.filter(ImageFilter.GaussianBlur(radius=15))
        img2_arr = np.array(img2, dtype=np.int16)
        blur_arr = np.array(blurred, dtype=np.int16)
        # 局所平均より暗いピクセルを黒に
        diff = img2_arr - blur_arr
        binary = np.where(diff < -10, 0, 255).astype(np.uint8)
        img2 = Image.fromarray(binary, mode="L")
        results.append(("adaptive", img2))
    except Exception:
        pass

    # --- 戦略3: シンプルな高コントラスト（従来の改良版） ---
    try:
        img3 = gray.copy()
        enhancer = ImageEnhance.Contrast(img3)
        img3 = enhancer.enhance(2.5)
        enhancer = ImageEnhance.Sharpness(img3)
        img3 = enhancer.enhance(2.0)
        img3 = img3.point(lambda x: 0 if x < 160 else 255)
        results.append(("simple", img3))
    except Exception:
        pass

    # --- 戦略4: ノイズ除去 + コントラスト ---
    try:
        img4 = gray.copy()
        img4 = img4.filter(ImageFilter.MedianFilter(size=3))
        enhancer = ImageEnhance.Contrast(img4)
        img4 = enhancer.enhance(2.0)
        enhancer = ImageEnhance.Sharpness(img4)
        img4 = enhancer.enhance(1.5)
        img4 = img4.point(lambda x: 0 if x < 140 else 255)
        results.append(("denoise", img4))
    except Exception:
        pass

    return results if results else [("fallback", gray)]


def _normalize_text(text):
    """全角数字・記号を半角に正規化"""
    # 全角数字 → 半角数字
    table = str.maketrans(
        "０１２３４５６７８９￥＊（）．，／−",
        "0123456789¥*().,-/"
    )
    text = text.translate(table)
    # 全角スペース → 半角
    text = text.replace("\u3000", " ")
    # 連続空白を1つに
    text = re.sub(r"  +", " ", text)
    return text


def _ocr_with_tesseract(image):
    """Tesseract で OCR を実行（フォールバック用）"""
    from PIL import Image, ImageFilter, ImageEnhance
    import traceback

    tesseract_available, tesseract_path = _check_tesseract()
    if not tesseract_available:
        return "", "tesseract_unavailable"

    try:
        import pytesseract
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

        tessdata_candidates = [
            "/opt/homebrew/share/tessdata", "/usr/local/share/tessdata",
            "/usr/share/tesseract-ocr/4.00/tessdata",
            "/usr/share/tesseract-ocr/5/tessdata", "/usr/share/tessdata",
        ]
        for td in tessdata_candidates:
            if os.path.isdir(td):
                os.environ["TESSDATA_PREFIX"] = td
                break

        try:
            available_langs = pytesseract.get_languages()
            lang = "jpn+eng" if "jpn" in available_langs else "eng"
        except Exception:
            lang = "eng"

        preprocessed = _preprocess_receipt_image(image)
        best_text = ""
        best_score = 0
        best_strategy = ""

        for strategy_name, img_processed in preprocessed:
            for psm in [6, 4, 3]:
                try:
                    config = f"--oem 3 --psm {psm}"
                    text = pytesseract.image_to_string(img_processed, lang=lang, config=config)
                    text = _normalize_text(text)
                    jpn_chars = len(re.findall(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]", text))
                    digits = len(re.findall(r"\d", text))
                    yen_marks = text.count("¥") + text.count("￥")
                    has_total = 1 if re.search(r"合\s*計", text) else 0
                    has_date = 1 if re.search(r"\d{4}[年/\-.]", text) else 0
                    score = jpn_chars * 2 + digits + yen_marks * 5 + has_total * 50 + has_date * 30
                    if score > best_score:
                        best_score = score
                        best_text = text
                        best_strategy = f"{strategy_name}/psm{psm}"
                except Exception:
                    continue

        return best_text, f"tesseract ({lang}, {best_strategy})"
    except Exception as e:
        return "", f"tesseract_error: {e}"


def ocr_receipt(image, filepath=None, image_bytes=None):
    """
    レシート画像からテキストを抽出し、
    店舗名・日付・金額・カテゴリ・決済方法を推定する

    優先順位:
      1. Google Cloud Vision API（月1,000回無料）
      2. Tesseract OCR（フォールバック）
      3. 簡易モード（OCRなし）
    """
    import traceback

    best_text = ""
    ocr_method = "none"
    ocr_error = ""
    vision_usage = None

    # === 1. Google Cloud Vision API を試す ===
    try:
        from vision_ocr import vision_ocr_image, get_usage_status, check_vision_api

        api_check = check_vision_api()
        if api_check["available"]:
            usage_status = get_usage_status()

            if not usage_status["blocked"]:
                # image_bytes が渡されていない場合は image から生成
                if image_bytes is None and filepath:
                    with open(filepath, "rb") as f:
                        image_bytes = f.read()
                elif image_bytes is None:
                    buf = io.BytesIO()
                    image.save(buf, format="JPEG", quality=90)
                    image_bytes = buf.getvalue()

                vision_result = vision_ocr_image(image_bytes)
                vision_usage = vision_result.get("usage")

                if vision_result["success"] and vision_result["text"].strip():
                    best_text = _normalize_text(vision_result["text"])
                    ocr_method = "Google Cloud Vision API"

                    # 使用量警告をエラー欄に表示
                    if vision_usage and vision_usage.get("warning"):
                        ocr_error = vision_usage["message"]
                elif vision_result.get("fallback_to_tesseract"):
                    ocr_error = vision_result.get("error", "")
                    # → Tesseract にフォールバック
            else:
                ocr_error = usage_status["message"]
                vision_usage = usage_status
                # → Tesseract にフォールバック
    except ImportError:
        pass  # vision_ocr モジュールがない → Tesseract にフォールバック
    except Exception as e:
        ocr_error = f"Vision API エラー: {e}"

    # === 2. Tesseract OCR フォールバック ===
    if not best_text.strip():
        tess_text, tess_method = _ocr_with_tesseract(image)
        if tess_text.strip():
            best_text = tess_text
            if "Vision" not in ocr_method:
                ocr_method = tess_method
            else:
                ocr_method = f"{tess_method} (Vision API フォールバック)"

    # === 3. テキストが取れなかった場合 → 簡易モード ===
    if not best_text.strip():
        ocr_method = "簡易モード（OCRなし）"
        err_parts = []
        if ocr_error:
            err_parts.append(ocr_error)
        if not _check_tesseract()[0]:
            err_parts.append(
                "Tesseract OCRも見つかりません。\n"
                "  brew install tesseract && brew install tesseract-lang"
            )
        result = {
            "store_name": "",
            "date": date.today().strftime("%Y-%m-%d"),
            "line_items": [],
            "total": 0,
            "category_guess": "食費",
            "payment_method": "",
            "raw_text": "[OCRテキストなし]\n\n" + "\n".join(err_parts) if err_parts else "[OCRテキストなし]",
            "success": True,
            "ocr_method": ocr_method,
            "ocr_error": "\n".join(err_parts),
            "needs_manual_input": True,
            "vision_usage": vision_usage,
        }
        if filepath:
            fname = os.path.basename(filepath).lower()
            for key, name in [("seven", "セブンイレブン"), ("lawson", "ローソン"),
                              ("famima", "ファミリーマート"), ("aeon", "イオン")]:
                if key in fname:
                    result["store_name"] = name
                    break
        return result

    # === テキストからレシート情報を抽出 ===
    result = parse_receipt_ocr(best_text)
    result["raw_text"] = best_text
    result["success"] = True
    result["ocr_method"] = ocr_method
    result["ocr_error"] = ocr_error
    result["needs_manual_input"] = False
    result["vision_usage"] = vision_usage

    return result


def parse_receipt_ocr(text):
    """
    OCRテキストからレシート情報を解析 (v2 - 改善版)
    - 日本語店名の直接マッチング
    - 年月日形式の日付対応
    - 全角文字正規化
    - 日本語決済手段対応
    """
    # 全角正規化
    text = _normalize_text(text)
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    result = {
        "store_name": "",
        "date": "",
        "line_items": [],
        "total": 0,
        "category_guess": "食費",
        "payment_method": "",
    }

    # ==============================================
    # 1. 店舗名の推定（日本語キーワード優先）
    # ==============================================
    # 日本語の店名キーワード（テキスト全体から検索）
    jp_store_keywords = {
        # スーパー・食料品
        "生鮮市場": "生鮮市場", "業務スーパー": "業務スーパー",
        "イオン": "イオン", "西友": "西友", "ライフ": "ライフ",
        "マルエツ": "マルエツ", "サミット": "サミット",
        "オーケー": "オーケー", "コストコ": "コストコ",
        "いなげや": "いなげや", "ヤオコー": "ヤオコー",
        "ベイシア": "ベイシア", "バロー": "バロー",
        "万代": "万代", "フレスコ": "フレスコ",
        "成城石井": "成城石井", "紀ノ国屋": "紀ノ国屋",
        "まいばすけっと": "まいばすけっと",
        "イトーヨーカドー": "イトーヨーカドー",
        # コンビニ
        "セブン-イレブン": "セブンイレブン", "セブンイレブン": "セブンイレブン",
        "ファミリーマート": "ファミリーマート", "ローソン": "ローソン",
        "ミニストップ": "ミニストップ", "デイリーヤマザキ": "デイリーヤマザキ",
        "セイコーマート": "セイコーマート", "ポプラ": "ポプラ",
        # 飲食店
        "三浦のハンバーグ": "三浦のハンバーグ",
        "タリーズ": "タリーズコーヒー", "tully": "タリーズコーヒー",
        "スターバックス": "スターバックス", "starbucks": "スターバックス",
        "ドトール": "ドトール", "コメダ": "コメダ珈琲",
        "サンマルク": "サンマルクカフェ", "ベローチェ": "ベローチェ",
        "マクドナルド": "マクドナルド", "mcdonald": "マクドナルド",
        "モスバーガー": "モスバーガー", "バーガーキング": "バーガーキング",
        "すき家": "すき家", "吉野家": "吉野家", "松屋": "松屋",
        "ガスト": "ガスト", "サイゼリヤ": "サイゼリヤ",
        "ジョナサン": "ジョナサン", "デニーズ": "デニーズ",
        "ココス": "ココス", "ロイヤルホスト": "ロイヤルホスト",
        "大戸屋": "大戸屋", "やよい軒": "やよい軒",
        "丸亀製麺": "丸亀製麺", "はなまるうどん": "はなまるうどん",
        "天下一品": "天下一品", "一蘭": "一蘭", "一風堂": "一風堂",
        "日高屋": "日高屋", "幸楽苑": "幸楽苑",
        "餃子の王将": "餃子の王将", "リンガーハット": "リンガーハット",
        "CoCo壱番屋": "CoCo壱番屋", "かつや": "かつや",
        "新時代": "新時代", "鳥貴族": "鳥貴族",
        "串カツ田中": "串カツ田中", "和民": "和民",
        "魚民": "魚民", "白木屋": "白木屋",
        # ドラッグストア
        "マツモトキヨシ": "マツモトキヨシ", "ウエルシア": "ウエルシア",
        "サンドラッグ": "サンドラッグ", "ツルハ": "ツルハドラッグ",
        "ココカラファイン": "ココカラファイン", "スギ薬局": "スギ薬局",
        "クリエイト": "クリエイトSD",
        # ドン・キホーテ
        "ドン・キホーテ": "ドン・キホーテ", "ドンキ": "ドン・キホーテ",
        "don quijote": "ドン・キホーテ",
        # 家電
        "ヤマダ電機": "ヤマダ電機", "ビックカメラ": "ビックカメラ",
        "ヨドバシ": "ヨドバシカメラ", "エディオン": "エディオン",
        "ケーズデンキ": "ケーズデンキ", "ノジマ": "ノジマ",
        # 衣料
        "ユニクロ": "ユニクロ", "uniqlo": "ユニクロ",
        "GU": "GU", "しまむら": "しまむら",
        "H&M": "H&M", "ZARA": "ZARA",
        # 100円ショップ
        "ダイソー": "ダイソー", "セリア": "セリア",
        "キャンドゥ": "キャンドゥ",
        # ホームセンター
        "カインズ": "カインズ", "コーナン": "コーナン",
        "ニトリ": "ニトリ", "無印良品": "無印良品",
    }

    # 英語キーワード（小文字マッチ）
    en_store_keywords = {
        "seven": "セブンイレブン", "7-eleven": "セブンイレブン", "7-11": "セブンイレブン",
        "lawson": "ローソン", "familymart": "ファミリーマート",
        "aeon": "イオン", "costco": "コストコ",
        "fresh food": "生鮮市場",
    }

    # まず全テキストから日本語店名を検索（長いキーワードを優先）
    text_for_store = "\n".join(lines[:10])
    found_stores = []
    for key, name in sorted(jp_store_keywords.items(), key=lambda x: len(x[0]), reverse=True):
        if key in text_for_store:
            found_stores.append((text_for_store.index(key), name, key))
    if found_stores:
        # テキスト中の出現位置が最も早いものを採用
        found_stores.sort(key=lambda x: x[0])
        base_name = found_stores[0][1]
        result["store_name"] = base_name
        # 支店名も取得試行
        match_key = found_stores[0][2]
        branch_found = False
        for i, line in enumerate(lines[:10]):
            if match_key in line:
                # 同じ行に支店名があれば追加（例: "三浦のハンバーグ池袋店"）
                after = line.split(match_key)[-1].strip()
                if after and len(after) <= 20 and not re.match(r"^[\d\s]+$", after):
                    # 店名の一部が重複しないようチェック
                    if after not in base_name and base_name not in after:
                        result["store_name"] = base_name + " " + after
                    elif "店" in after and "店" not in base_name:
                        result["store_name"] = base_name + " " + after
                    branch_found = True
                # 次の行に支店名がある場合（例: "業務スーパー" 改行 "六角橋店"）
                if not branch_found and i + 1 < len(lines[:10]):
                    next_line = lines[i + 1].strip()
                    if re.search(r".+店$", next_line) and len(next_line) <= 20:
                        result["store_name"] = base_name + " " + next_line
                        branch_found = True
                break

    # 英語キーワード検索
    if not result["store_name"]:
        text_lower_store = text_for_store.lower()
        for key, name in en_store_keywords.items():
            if key in text_lower_store:
                result["store_name"] = name
                break

    # フォールバック: レシート最上部から店名を推定
    # レシートの構造: 店名 → 住所 → 電話番号 → 日付 → 品目...
    # 最上部の「意味のある文字列」が店名である可能性が高い
    if not result["store_name"] and lines:
        for line in lines[:7]:
            # 明らかにスキップすべき行
            if re.match(r"^[\d\s\-/:.TELtelFAXfax#＃T※〒]+$", line):
                continue
            if re.match(r"^(登録番号|レジ|TEL|FAX|電話|〒|住所|領収)", line):
                continue
            if len(line) <= 1:
                continue
            # 日付行はスキップ（2025/02/11 など）
            if re.match(r"^\d{2,4}[/\-年]\d{1,2}[/\-月]\d{1,2}", line):
                continue
            # 住所行をスキップ（都道府県・市区町村で始まる行）
            if re.match(r"^.{0,3}(都|道|府|県|市|区|町|村|郡)", line):
                continue
            # 長すぎる行は住所の可能性が高い（店名は通常短い）
            if len(line) > 30:
                continue
            result["store_name"] = line[:30]
            break

    # 支店名を別の行から補完
    if result["store_name"] and "店" not in result["store_name"]:
        base = result["store_name"]
        for line in lines[:10]:
            stripped = line.strip()
            if re.search(r".+店$", stripped) and len(stripped) <= 20:
                if stripped != base:
                    # 基本店名がstrippedに含まれている場合は、支店部分のみ抽出
                    if base in stripped:
                        branch_part = stripped.replace(base, "").strip()
                        if branch_part:
                            result["store_name"] = base + " " + branch_part
                    else:
                        result["store_name"] = base + " " + stripped
                    break

    # ==============================================
    # 2. 日付の抽出（年月日形式を最優先）
    # ==============================================
    date_patterns = [
        # 2026年2月8日 / 2026年02月10日
        (r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", "nen"),
        # 2026/02/11 / 2026-02-11 / 2026.02.11
        (r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", "slash"),
        # R8.02.11 / R8/02/11 (令和)
        (r"[RＲ]\s*(\d{1,2})\s*[/\-.年]\s*(\d{1,2})\s*[/\-.月]\s*(\d{1,2})", "reiwa"),
        # 令和8年2月11日
        (r"令和\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", "reiwa_kanji"),
        # 26/02/11
        (r"(?<!\d)(\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})(?!\d)", "yy"),
    ]

    for line in lines:
        if result["date"]:
            break
        for pattern, ptype in date_patterns:
            match = re.search(pattern, line)
            if match:
                groups = match.groups()
                try:
                    if ptype == "nen" or ptype == "slash":
                        y, m, d = int(groups[0]), int(groups[1]), int(groups[2])
                        # 登録番号 T2020... などの誤検出を防止
                        if y < 2000 or y > 2100:
                            continue
                    elif ptype == "reiwa" or ptype == "reiwa_kanji":
                        y = int(groups[0]) + 2018
                        m, d = int(groups[1]), int(groups[2])
                    elif ptype == "yy":
                        y = int(groups[0])
                        y = y + 2000 if y < 50 else y + 1900
                        m, d = int(groups[1]), int(groups[2])
                    else:
                        continue

                    # 日付の妥当性チェック
                    if 1 <= m <= 12 and 1 <= d <= 31:
                        test_date = f"{y}-{m:02d}-{d:02d}"
                        datetime.strptime(test_date, "%Y-%m-%d")
                        result["date"] = test_date
                        break
                except (ValueError, IndexError):
                    continue

    if not result["date"]:
        result["date"] = date.today().strftime("%Y-%m-%d")

    # ==============================================
    # 3. 金額の抽出（改善版）
    # ==============================================
    result["line_items"] = []

    # 合計キーワード（スペース入り・全角対応）
    total_keywords = [
        "合計", "合 計", "合　計", "合言十", "合訂",  # OCR誤読対応
        "お支払", "お支払い", "税込合計", "請求額",
        "total", "TOTAL", "ttl",
    ]
    subtotal_keywords = ["小計", "小 計"]
    skip_keywords = [
        "お釣", "おつり", "お預", "預り", "お預り",
        "点数", "買上点数", "商品点数",
        "ポイント", "税率", "対象額", "税等", "消費税",
        "内税", "外税", "軽減", "8%", "10%",
        "登録番号", "取引", "電話", "TEL", "FAX",
        # 決済方法キーワード（品目と間違えないため）
        "コード決済", "楽天ペイ", "PayPay", "paypay", "LINE Pay",
        "メルペイ", "d払い", "au PAY", "電子マネー", "楽天ポイント",
        "クレジット", "VISA", "Mastercard", "JCB", "AMEX",
        "Suica", "PASMO", "nanaco", "WAON", "現金",
    ]

    # ¥マーク付き金額パターン
    yen_pattern = re.compile(r"[¥￥\\]\s*([0-9][0-9,]*)")
    # 行末の金額パターン
    line_amount_pattern = re.compile(r"(.+?)\s+[¥￥\\]?\s*([0-9][0-9,]*)\s*$")
    # 割引パターン
    discount_pattern = re.compile(r"[-ー−]\s*([0-9][0-9,]*)")

    # 合計金額の検出（改善版 v3）
    # 優先度:
    #   P1: 「税込合計」「合計(税込)」 + ¥金額
    #   P2: 「合計」(小計以外) + ¥金額
    #   P3: 「お支払」「請求額」 + ¥金額
    #   P4: 「合計」 + 金額（¥なし）→ +10 penalty
    #   P5: 「小計」 + ¥金額
    #   ※ 同じ優先度なら後（下の行）に出たものを採用
    #   ※ 「合計」行の直後に¥金額のみの行がある場合も対応
    total_found = False
    total_candidates = []

    # 優先度付きキーワード
    priority_keywords = [
        (1, ["税込合計", "税込 合計", "合計(税込)", "合計（税込）"]),
        (2, ["合計", "合 計", "合　計", "合言十", "合訂"]),
        (3, ["お支払", "お支払い", "請求額", "total", "TOTAL"]),
        (5, ["小計", "小 計"]),
    ]

    # 「合計 ¥金額」を直接探すパターン（スペース・全角対応）
    direct_total_pattern = re.compile(
        r"(?:税込\s*)?合計\s*[¥￥\\]\s*([0-9][0-9,]*)"
    )

    for i, line in enumerate(lines):
        # スキップ対象行（ただし合計キーワードを含む行は除外しない）
        is_total_line = any(kw in line for kw in total_keywords)
        if any(kw in line for kw in skip_keywords) and not is_total_line:
            continue

        if not is_total_line:
            continue

        # この行のキーワード優先度を決定
        line_priority = 99
        for pri, kws in priority_keywords:
            if any(kw in line for kw in kws):
                # 「小計」が含まれる場合、「合計」でも「小計」扱い
                if pri == 2 and any(sk in line for sk in ["小計", "小 計"]):
                    line_priority = min(line_priority, 5)
                else:
                    line_priority = min(line_priority, pri)
                break

        # 直接パターン「合計 ¥金額」を最優先で探す
        dm = direct_total_pattern.search(line)
        if dm:
            try:
                val = int(dm.group(1).replace(",", ""))
                if 10 <= val <= 999999:
                    total_candidates.append((line_priority, "direct", val, line))
                    continue
            except ValueError:
                pass

        # ¥付き金額を探す
        yen_matches = yen_pattern.findall(line)
        if yen_matches:
            for m in yen_matches:
                try:
                    val = int(m.replace(",", ""))
                    if 10 <= val <= 999999:
                        total_candidates.append((line_priority, "yen", val, line))
                except ValueError:
                    pass
        else:
            # 数字のみの抽出（¥なし）
            nums = re.findall(r"(\d[\d,]*)", line)
            for n in nums:
                try:
                    val = int(n.replace(",", ""))
                    if 10 <= val <= 999999:
                        # ¥なしは優先度を+10して区別
                        total_candidates.append((line_priority + 10, "num", val, line))
                except ValueError:
                    pass

            # 合計行に金額がない場合、次の行に¥金額がある可能性をチェック
            if not nums and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                next_yen = yen_pattern.findall(next_line)
                if next_yen:
                    for m in next_yen:
                        try:
                            val = int(m.replace(",", ""))
                            if 10 <= val <= 999999:
                                total_candidates.append((line_priority, "next_line", val, line + " " + next_line))
                        except ValueError:
                            pass

    # 合計候補から最適なものを選択
    # 最も優先度が高い（数字が小さい）ものを採用。同優先度なら最後のもの
    if total_candidates:
        best_priority = min(c[0] for c in total_candidates)
        best_candidates = [c for c in total_candidates if c[0] == best_priority]
        # 同優先度の中で「direct」タイプを優先、なければ最後のものを採用
        direct_matches = [c for c in best_candidates if c[1] == "direct"]
        if direct_matches:
            _, _, best_val, _ = direct_matches[-1]
        else:
            # レシートは下に行くほど最終合計なので最後のものを採用
            _, _, best_val, _ = best_candidates[-1]
        result["total"] = best_val
        total_found = True

    # 品目の抽出
    for line in lines:
        # スキップ行（合計・小計・税・お釣りなど）
        if any(kw in line for kw in total_keywords + subtotal_keywords + skip_keywords):
            continue
        # 純粋な数字のみの行をスキップ（レシート番号など）
        if re.match(r"^[\d\s,.\-/:#PpTt]+$", line):
            continue
        # バーコード・登録番号行をスキップ
        if re.match(r"^[PT]\d{10,}", line):
            continue
        # 括弧で始まる補足行をスキップ（「(2個 x @238)」など）
        if re.match(r"^\s*[（(]", line):
            continue
        # 割引行
        if re.match(r"^\s*割引", line):
            dm = discount_pattern.search(line)
            if dm:
                try:
                    discount_val = int(dm.group(1).replace(",", ""))
                    if discount_val > 0 and result["line_items"]:
                        result["line_items"].append({"name": "割引", "amount": -discount_val})
                except ValueError:
                    pass
            continue

        # 品目 + ¥金額パターン
        m = line_amount_pattern.match(line)
        if m:
            name = m.group(1).strip()
            # 品目名のクリーニング（先頭の内8, ※, コードなど除去）
            name = re.sub(r"^(内\d+\s*|※\s*|\*\s*)", "", name)
            name = re.sub(r"^\d{4}\s+", "", name)  # 先頭4桁コード除去
            name = name.strip()
            # 品目名が数字のみの場合はスキップ
            if re.match(r"^[\d\s,]+$", name):
                continue
            try:
                amount = int(m.group(2).replace(",", ""))
                if name and 1 <= amount <= 999999 and len(name) >= 2:
                    result["line_items"].append({"name": name, "amount": amount})
            except ValueError:
                pass

    # 合計がなければ品目合計 or 最大金額
    if not total_found:
        if result["line_items"]:
            positive_items = [it["amount"] for it in result["line_items"] if it["amount"] > 0]
            if positive_items:
                result["total"] = sum(positive_items)
        else:
            # テキスト全体から¥付き金額を収集し最大値
            all_amounts = []
            for line in lines:
                for m in yen_pattern.finditer(line):
                    try:
                        val = int(m.group(1).replace(",", ""))
                        if 10 <= val <= 999999:
                            all_amounts.append(val)
                    except ValueError:
                        pass
            if all_amounts:
                result["total"] = max(all_amounts)

    # ==============================================
    # 4. カテゴリ推定（店名 → テキスト内容）
    # ==============================================
    store_name = result["store_name"]
    text_lower = text.lower()

    # 店名ベースカテゴリ（優先）
    store_category_map = {
        # 食品スーパー
        "生鮮市場": "食費", "業務スーパー": "食費", "イオン": "食費",
        "西友": "食費", "ライフ": "食費", "マルエツ": "食費",
        "サミット": "食費", "オーケー": "食費", "コストコ": "食費",
        "成城石井": "食費", "まいばすけっと": "食費",
        "イトーヨーカドー": "食費",
        # コンビニ
        "セブンイレブン": "食費", "ローソン": "食費", "ファミリーマート": "食費",
        "ミニストップ": "食費",
        # 外食
        "三浦のハンバーグ": "外食費", "タリーズ": "外食費",
        "スターバックス": "外食費", "ドトール": "外食費",
        "コメダ": "外食費", "マクドナルド": "外食費",
        "すき家": "外食費", "吉野家": "外食費", "松屋": "外食費",
        "ガスト": "外食費", "サイゼリヤ": "外食費",
        "大戸屋": "外食費", "やよい軒": "外食費",
        "新時代": "外食費", "鳥貴族": "外食費",
        "日高屋": "外食費", "一蘭": "外食費",
        "丸亀製麺": "外食費", "はなまるうどん": "外食費",
        "CoCo壱番屋": "外食費", "かつや": "外食費",
        "天丼てんや": "外食費", "なか卯": "外食費",
        "餃子の王将": "外食費", "幸楽苑": "外食費",
        "リンガーハット": "外食費", "磯丸水産": "外食費",
        "一風堂": "外食費", "天下一品": "外食費",
        "バーミヤン": "外食費", "ジョナサン": "外食費",
        "デニーズ": "外食費", "ココス": "外食費",
        "ロイヤルホスト": "外食費",
        "モスバーガー": "外食費", "バーガーキング": "外食費",
        "串カツ田中": "外食費", "和民": "外食費",
        "魚民": "外食費", "白木屋": "外食費",
        "サンマルク": "外食費", "ベローチェ": "外食費",
        # ドラッグストア
        "マツモトキヨシ": "日用品", "ウエルシア": "日用品",
        "サンドラッグ": "日用品", "ツルハ": "日用品",
        "ココカラファイン": "日用品", "スギ薬局": "日用品",
        # 家電
        "ヤマダ電機": "家電購入", "ビックカメラ": "家電購入",
        "ヨドバシ": "家電購入", "エディオン": "家電購入",
        "ケーズデンキ": "家電購入",
        # 衣料
        "ユニクロ": "衣服費", "GU": "衣服費", "しまむら": "衣服費",
        "H&M": "衣服費", "ZARA": "衣服費",
        # ドン・キホーテ
        "ドン・キホーテ": "日用品",
        # 100均
        "ダイソー": "日用品", "セリア": "日用品", "キャンドゥ": "日用品",
        # 家具
        "ニトリ": "日用品", "無印良品": "日用品",
    }

    category_set = False
    for key, cat in store_category_map.items():
        if key in store_name:
            result["category_guess"] = cat
            category_set = True
            break

    if not category_set:
        # テキスト内容からカテゴリ推定
        category_patterns = {
            "食費": ["food", "grocery", "スーパー", "コンビニ", "弁当", "おにぎり",
                      "パン", "飲料", "meat", "fish", "vegetable", "rice", "milk",
                      "鮮魚", "青果", "精肉", "惣菜", "生鮮"],
            "外食費": ["restaurant", "cafe", "coffee", "lunch", "dinner",
                       "ランチ", "ディナー", "カフェ", "コーヒー", "居酒屋",
                       "ハンバーグ", "ラーメン", "うどん", "そば", "寿司"],
            "日用品": ["drug", "pharmacy", "洗剤", "shampoo", "soap", "tissue",
                       "paper", "cleaning", "ドラッグ", "日用", "ティッシュ"],
            "交通費": ["jr", "suica", "pasmo", "train", "bus", "taxi",
                       "parking", "toll", "駐車", "鉄道", "電車", "バス"],
            "医療費": ["hospital", "clinic", "medicine", "doctor",
                       "医療", "薬", "処方", "診療"],
            "衣服費": ["cloth", "fashion", "wear", "shoes",
                       "衣", "服", "靴", "ファッション"],
            "娯楽費": ["movie", "game", "book", "entertainment",
                       "hobby", "映画", "ゲーム", "書籍"],
            "美容費": ["beauty", "salon", "hair", "cosmetic", "nail", "美容"],
            "光熱費": ["electric", "gas", "water", "電気", "ガス", "水道"],
            "通信費": ["phone", "mobile", "internet", "wifi", "docomo",
                       "softbank", "au ", "携帯", "通信"],
            "家電購入": ["electronics", "appliance", "camera", "家電"],
        }

        best_category = "食費"
        best_score = 0
        for cat, keywords in category_patterns.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > best_score:
                best_score = score
                best_category = cat

        result["category_guess"] = best_category

    # ==============================================
    # 5. 決済方法の推定（日本語キーワード優先）
    # ==============================================
    # 決済キーワードとパターン（金額付きの行から優先検出）
    payment_line_patterns = [
        (r"コード決済", "コード決済"),
        (r"楽天ペイ", "楽天ペイ"),
        (r"楽天pay", "楽天ペイ"),
        (r"PayPay|paypay|ペイペイ", "PayPay"),
        (r"LINE\s*Pay|linepay|ラインペイ", "LINE Pay"),
        (r"メルペイ", "メルペイ"),
        (r"d払い|ｄ払い", "d払い"),
        (r"au\s*PAY|auペイ", "au PAY"),
        (r"楽天ポイント", "楽天ポイント"),
        (r"電子マネー", "電子マネー"),
        (r"(?:クレジット|CREDIT)", "クレジットカード"),
        (r"(?:VISA|Visa|visa)", "VISA"),
        (r"(?:Mastercard|mastercard|MASTER)", "Mastercard"),
        (r"(?:JCB|jcb)", "JCB"),
        (r"(?:AMEX|amex|アメックス)", "AMEX"),
        (r"Suica|suica|スイカ", "Suica"),
        (r"PASMO|pasmo|パスモ", "PASMO"),
        (r"(?:^|\s)iD(?:\s|$)", "iD"),
        (r"QUICPay|quicpay|クイックペイ", "QUICPay"),
        (r"nanaco|ナナコ", "nanaco"),
        (r"WAON|waon|ワオン", "WAON"),
        (r"お預り|お預かり|預り金", "現金"),
        (r"現金", "現金"),
    ]

    # 決済方法を金額付きで検出し、最大金額のものを採用
    payment_candidates = []
    for line in lines:
        for pattern, method in payment_line_patterns:
            if re.search(pattern, line):
                # この行の¥金額を取得
                yen_m = re.findall(r"[¥￥]\s*([0-9][0-9,]*)", line)
                amount = 0
                if yen_m:
                    try:
                        amount = int(yen_m[0].replace(",", ""))
                    except ValueError:
                        pass
                payment_candidates.append((method, amount))
                break

    if payment_candidates:
        # 金額が最大の決済方法を採用（0の場合は最初にマッチしたもの）
        with_amount = [(m, a) for m, a in payment_candidates if a > 0]
        if with_amount:
            best_payment = max(with_amount, key=lambda x: x[1])
            result["payment_method"] = best_payment[0]
        else:
            result["payment_method"] = payment_candidates[0][0]

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


def _process_receipt_file(file):
    """
    1枚のレシート画像を 読み込み→圧縮→保存→OCR まで処理し、
    結果を1件分の dict で返す。複数アップロードのループから呼ばれる。
    """
    import traceback

    res = {
        "filename": file.filename,
        "ocr_result": None,
        "compression_info": None,
        "error": None,        # 詳細(トレース付き)
        "error_short": None,  # flash用の短いメッセージ
    }

    # Step 1: 画像読み込み
    try:
        image_bytes = file.read()
        if not image_bytes:
            res["error_short"] = "ファイルが空です。"
            res["error"] = res["error_short"]
            return res
    except Exception as e:
        res["error_short"] = f"読み込みエラー: {e}"
        res["error"] = f"画像読み込みエラー: {e}\n{traceback.format_exc()}"
        return res

    # Step 2: 画像圧縮 (HEICはJPEGへ変換)
    try:
        comp = compress_image(image_bytes, file.filename)
        res["compression_info"] = comp
    except Exception as e:
        res["error_short"] = f"圧縮エラー: {e}"
        res["error"] = f"画像圧縮エラー: {e}\n{traceback.format_exc()}"
        return res

    # Step 3: 保存
    try:
        ext = ".png" if comp["format"] == "PNG" else ".jpg"
        save_name = f"receipt_{uuid.uuid4().hex[:8]}{ext}"
        save_path = os.path.join(UPLOAD_DIR, save_name)
        with open(save_path, "wb") as f:
            f.write(comp["bytes"])
    except Exception as e:
        res["error_short"] = f"保存エラー: {e}"
        res["error"] = f"ファイル保存エラー: {e}\n{traceback.format_exc()}"
        return res

    # Step 4: OCR実行
    try:
        ocr_result = ocr_receipt(comp["image"], save_path, image_bytes=comp["bytes"])
        ocr_result["saved_path"] = save_path
        ocr_result["saved_name"] = save_name
        res["ocr_result"] = ocr_result
    except Exception as e:
        res["error_short"] = f"OCRエラー: {e}"
        res["error"] = f"OCRエラー: {e}\n{traceback.format_exc()}"

    return res


@app.route("/receipt", methods=["GET", "POST"])
def receipt_page():
    results = []
    error_detail = None

    if request.method == "POST":
        if "receipt_image" in request.files:
            # 複数選択対応: getlist で全ファイルを取得
            files = [f for f in request.files.getlist("receipt_image") if f and f.filename]
            if files:
                for file in files:
                    res = _process_receipt_file(file)
                    results.append(res)
                    if res["error"]:
                        flash(f"{res['filename']}: {res['error_short']}", "error")
                    else:
                        flash(
                            f"{res['filename']}: 読み取り完了"
                            f"（{res['ocr_result']['store_name'] or '店舗不明'} / "
                            f"{res['ocr_result']['total']:,}円）",
                            "success",
                        )
                # 全件失敗した場合のみ、画面上部の大きなエラー枠に詳細を出す
                if results and all(r["error"] for r in results):
                    error_detail = results[0]["error"]
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
                <p>JPEG / PNG / HEIC 対応 ・ 複数選択OK ・ 自動圧縮あり（HEICはJPEGへ自動変換）</p>
                <input type="file" name="receipt_image" id="fileInput" multiple
                       accept="image/jpeg,image/png,image/heic,image/heif,.heic,.heif"
                       style="display:none" onchange="document.getElementById('uploadForm').submit();">
            </div>
        </form>
    </div>

    {% if results %}
    <h2 style="margin-top:24px;">読み取り結果（{{ results|length }}件）</h2>
    {% endif %}

    {% for r in results %}
    <div style="margin-bottom:8px;">
        <div style="font-weight:600; margin:18px 0 8px; color:var(--primary); word-break:break-all;">
            📄 {{ r.filename }}
        </div>
        {% if r.error %}
        <div class="card" style="border-left:4px solid var(--warning); background:#FFF5F5;">
            <strong style="color:var(--warning);">読み取りに失敗しました</strong>
            <pre style="margin-top:6px; white-space:pre-wrap; color:#555; font-size:0.85rem; max-height:200px; overflow:auto;">{{ r.error }}</pre>
        </div>
        {% else %}
        {% set compression_info = r.compression_info %}
        {% set ocr_result = r.ocr_result %}
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
        <!-- OCRモード表示 -->
        <div style="margin-bottom:12px; padding:8px 12px; background:var(--primary-light); border-radius:6px; font-size:0.85rem;">
            🔍 読取モード: <strong>{{ ocr_result.ocr_method }}</strong>
            {% if ocr_result.needs_manual_input %}
            <span style="color:var(--orange); margin-left:8px;">※ OCRが使えないため、手動入力してください</span>
            {% endif %}
        </div>

        <!-- Vision API 使用量バー -->
        {% if ocr_result.vision_usage %}
        {% set vu = ocr_result.vision_usage %}
        <div style="margin-bottom:12px; padding:8px 12px; background:#f8f9fa; border-radius:6px; font-size:0.8rem;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                <span>📊 Vision API 使用量 ({{ vu.month }})</span>
                <span {% if vu.warning %}style="color:var(--orange); font-weight:bold;"{% endif %}>
                    {{ vu.count }}/{{ "{:,}".format(vu.limit) }}回
                    （残り{{ vu.remaining }}回）
                </span>
            </div>
            <div style="height:6px; background:#e0e0e0; border-radius:3px; overflow:hidden;">
                <div style="height:100%; width:{{ vu.percentage }}%;
                    background:{% if vu.percentage >= 90 %}var(--danger){% elif vu.percentage >= 80 %}var(--orange){% else %}var(--success){% endif %};
                    border-radius:3px; transition:width 0.3s;"></div>
            </div>
            {% if vu.warning %}
            <div style="color:var(--orange); margin-top:4px; font-weight:bold;">
                ⚠️ {{ vu.message }}
            </div>
            {% endif %}
        </div>
        {% endif %}

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
        {% endif %}
    </div>
    {% endfor %}

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
        results=results,
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
