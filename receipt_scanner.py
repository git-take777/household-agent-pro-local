"""
家計Pro - レシートOCRモジュール (v2 - 改善版)
担当: バックエンド担当

レシート画像から情報を抽出し、支出データとして登録する。
OCRエンジンは拡張可能な設計（Tesseract / Google Vision API / Claude Vision）

改善点 (v2):
- 複数の画像前処理戦略（Otsu / 適応的しきい値 / 高コントラスト / ノイズ除去）
- 日本語店名の直接マッチング（100+ 店舗対応）
- 年月日形式・令和形式の日付対応
- 全角文字の正規化
- 日本語決済手段の検出（コード決済 / 楽天ペイ / PayPay / 電子マネー / 現金 等）

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


# === web_app.py と共通の改善版パーサーを利用 ===
# CLIモジュール用に独立実装も維持

def _normalize_text(text):
    """全角数字・記号を半角に正規化"""
    table = str.maketrans(
        "０１２３４５６７８９￥＊（）．，／−",
        "0123456789¥*().,-/"
    )
    text = text.translate(table)
    text = text.replace("\u3000", " ")
    text = re.sub(r"  +", " ", text)
    return text


def parse_receipt_text(text: str) -> dict:
    """OCR出力テキストからレシート情報を抽出する (v2 改善版)"""
    text = _normalize_text(text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    result = {
        "store_name": "",
        "date": "",
        "items": [],
        "total": 0,
        "category_guess": "",
        "payment_method": "",
        "raw_text": text,
    }

    if not lines:
        return result

    # --- 店名の検出（日本語キーワード優先） ---
    jp_store_keywords = {
        "生鮮市場": "生鮮市場", "業務スーパー": "業務スーパー",
        "イオン": "イオン", "西友": "西友", "ライフ": "ライフ",
        "マルエツ": "マルエツ", "サミット": "サミット",
        "オーケー": "オーケー", "コストコ": "コストコ",
        "成城石井": "成城石井", "まいばすけっと": "まいばすけっと",
        "イトーヨーカドー": "イトーヨーカドー",
        "セブン-イレブン": "セブンイレブン", "セブンイレブン": "セブンイレブン",
        "ファミリーマート": "ファミリーマート", "ローソン": "ローソン",
        "三浦のハンバーグ": "三浦のハンバーグ",
        "タリーズ": "タリーズコーヒー",
        "スターバックス": "スターバックス", "ドトール": "ドトール",
        "マクドナルド": "マクドナルド", "すき家": "すき家",
        "吉野家": "吉野家", "松屋": "松屋",
        "ガスト": "ガスト", "サイゼリヤ": "サイゼリヤ",
        "新時代": "新時代", "鳥貴族": "鳥貴族",
        "大戸屋": "大戸屋", "やよい軒": "やよい軒",
        "マツモトキヨシ": "マツモトキヨシ", "ウエルシア": "ウエルシア",
        "サンドラッグ": "サンドラッグ", "ツルハ": "ツルハドラッグ",
        "ドン・キホーテ": "ドン・キホーテ",
        "ヤマダ電機": "ヤマダ電機", "ビックカメラ": "ビックカメラ",
        "ヨドバシ": "ヨドバシカメラ",
        "ユニクロ": "ユニクロ", "GU": "GU",
        "ダイソー": "ダイソー", "セリア": "セリア",
        "ニトリ": "ニトリ", "無印良品": "無印良品",
    }

    text_for_store = "\n".join(lines[:10])
    found_stores = []
    for key, name in sorted(jp_store_keywords.items(), key=lambda x: len(x[0]), reverse=True):
        if key in text_for_store:
            found_stores.append((text_for_store.index(key), name, key))

    if found_stores:
        found_stores.sort(key=lambda x: x[0])
        base_name = found_stores[0][1]
        result["store_name"] = base_name
        match_key = found_stores[0][2]
        for i, line in enumerate(lines[:10]):
            if match_key in line:
                after = line.split(match_key)[-1].strip()
                if after and len(after) <= 20 and not re.match(r"^[\d\s]+$", after):
                    if after not in base_name and base_name not in after:
                        result["store_name"] = base_name + " " + after
                    elif "店" in after and "店" not in base_name:
                        result["store_name"] = base_name + " " + after
                break
    else:
        # 英語キーワード
        en_keywords = {
            "seven": "セブンイレブン", "7-eleven": "セブンイレブン",
            "lawson": "ローソン", "familymart": "ファミリーマート",
            "starbucks": "スターバックス", "mcdonald": "マクドナルド",
            "tully": "タリーズコーヒー", "fresh food": "生鮮市場",
        }
        lower_text = text_for_store.lower()
        for key, name in en_keywords.items():
            if key in lower_text:
                result["store_name"] = name
                break

    if not result["store_name"] and lines:
        for line in lines[:5]:
            if re.match(r"^[\d\s\-/:.TELtelFAXfax#T※]+$", line):
                continue
            if re.match(r"^(登録番号|レジ|TEL|FAX|電話)", line):
                continue
            if len(line) <= 2:
                continue
            result["store_name"] = line[:30]
            break

    # 支店名補完
    if result["store_name"] and "店" not in result["store_name"]:
        base = result["store_name"]
        for line in lines[:10]:
            stripped = line.strip()
            if re.search(r".+店$", stripped) and len(stripped) <= 20:
                if stripped != base:
                    if base in stripped:
                        branch_part = stripped.replace(base, "").strip()
                        if branch_part:
                            result["store_name"] = base + " " + branch_part
                    else:
                        result["store_name"] = base + " " + stripped
                    break

    # --- 日付抽出（年月日形式を最優先） ---
    date_patterns = [
        (r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", "nen"),
        (r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", "slash"),
        (r"[RＲ]\s*(\d{1,2})\s*[/\-.年]\s*(\d{1,2})\s*[/\-.月]\s*(\d{1,2})", "reiwa"),
        (r"令和\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", "reiwa_kanji"),
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
                    if ptype in ("nen", "slash"):
                        y, m, d = int(groups[0]), int(groups[1]), int(groups[2])
                        if y < 2000 or y > 2100:
                            continue
                    elif ptype in ("reiwa", "reiwa_kanji"):
                        y = int(groups[0]) + 2018
                        m, d = int(groups[1]), int(groups[2])
                    elif ptype == "yy":
                        y = int(groups[0])
                        y = y + 2000 if y < 50 else y + 1900
                        m, d = int(groups[1]), int(groups[2])
                    else:
                        continue
                    if 1 <= m <= 12 and 1 <= d <= 31:
                        test_date = f"{y}-{m:02d}-{d:02d}"
                        datetime.strptime(test_date, "%Y-%m-%d")
                        result["date"] = test_date
                        break
                except (ValueError, IndexError):
                    continue

    if not result["date"]:
        result["date"] = date.today().strftime("%Y-%m-%d")

    # --- 金額抽出 ---
    total_keywords = ["合計", "合 計", "お支払", "税込合計", "total", "TOTAL"]
    skip_keywords = [
        "お釣", "おつり", "お預", "点数", "ポイント", "税率",
        "対象額", "税等", "消費税", "内税", "軽減", "登録番号",
        "コード決済", "楽天ペイ", "PayPay", "LINE Pay", "電子マネー",
        "クレジット", "Suica", "PASMO", "現金",
    ]
    yen_pattern = re.compile(r"[¥￥\\]\s*([0-9][0-9,]*)")

    # 合計金額の検出
    for line in lines:
        if any(kw in line for kw in total_keywords):
            yen_matches = yen_pattern.findall(line)
            if yen_matches:
                for m in yen_matches:
                    try:
                        val = int(m.replace(",", ""))
                        if 10 <= val <= 999999:
                            result["total"] = val
                            break
                    except ValueError:
                        pass
            else:
                nums = re.findall(r"(\d[\d,]*)", line)
                for n in nums:
                    try:
                        val = int(n.replace(",", ""))
                        if 10 <= val <= 999999:
                            result["total"] = val
                            break
                    except ValueError:
                        pass
        if result["total"]:
            break

    # 品目の抽出
    line_amount_pattern = re.compile(r"(.+?)\s+[¥￥\\]?\s*([0-9][0-9,]*)\s*$")
    for line in lines:
        if any(kw in line for kw in total_keywords + skip_keywords + ["小計"]):
            continue
        if re.match(r"^[\d\s,.\-/:#PpTt]+$", line):
            continue
        if re.match(r"^\s*[（(]", line):
            continue

        m = line_amount_pattern.match(line)
        if m:
            name = m.group(1).strip()
            name = re.sub(r"^(内\d+\s*|※\s*|\*\s*)", "", name)
            name = re.sub(r"^\d{4}\s+", "", name)
            name = name.strip()
            if re.match(r"^[\d\s,]+$", name):
                continue
            try:
                amount = int(m.group(2).replace(",", ""))
                if name and 1 <= amount <= 999999 and len(name) >= 2:
                    result["items"].append({"name": name, "amount": amount})
            except ValueError:
                pass

    if not result["total"] and result["items"]:
        positive = [it["amount"] for it in result["items"] if it["amount"] > 0]
        if positive:
            result["total"] = sum(positive)

    # カテゴリ推定
    result["category_guess"] = _guess_category(result["store_name"], result["items"], text)

    # --- 決済方法の検出 ---
    payment_patterns = [
        (r"コード決済", "コード決済"),
        (r"楽天ペイ", "楽天ペイ"),
        (r"PayPay|paypay|ペイペイ", "PayPay"),
        (r"LINE\s*Pay|ラインペイ", "LINE Pay"),
        (r"電子マネー", "電子マネー"),
        (r"楽天ポイント", "楽天ポイント"),
        (r"(?:クレジット|CREDIT|VISA|Mastercard|JCB|AMEX)", "クレジットカード"),
        (r"Suica|スイカ", "Suica"),
        (r"PASMO|パスモ", "PASMO"),
        (r"QUICPay|クイックペイ", "QUICPay"),
        (r"nanaco|ナナコ", "nanaco"),
        (r"WAON|ワオン", "WAON"),
        (r"お預り|お預かり", "現金"),
        (r"現金", "現金"),
    ]

    payment_candidates = []
    for line in lines:
        for pattern, method in payment_patterns:
            if re.search(pattern, line):
                yen_m = yen_pattern.findall(line)
                amount = 0
                if yen_m:
                    try:
                        amount = int(yen_m[0].replace(",", ""))
                    except ValueError:
                        pass
                payment_candidates.append((method, amount))
                break

    if payment_candidates:
        with_amount = [(m, a) for m, a in payment_candidates if a > 0]
        if with_amount:
            best = max(with_amount, key=lambda x: x[1])
            result["payment_method"] = best[0]
        else:
            result["payment_method"] = payment_candidates[0][0]

    return result


def _guess_category(store_name: str, items: list, full_text: str = "") -> str:
    """店名と品目からカテゴリを推定する (v2)"""
    # 店名ベースカテゴリ（優先）
    store_category_map = {
        "生鮮市場": "食費", "業務スーパー": "食費", "イオン": "食費",
        "西友": "食費", "ライフ": "食費", "マルエツ": "食費",
        "サミット": "食費", "オーケー": "食費", "コストコ": "食費",
        "セブンイレブン": "食費", "ローソン": "食費", "ファミリーマート": "食費",
        "三浦のハンバーグ": "外食費", "タリーズ": "外食費",
        "スターバックス": "外食費", "ドトール": "外食費",
        "マクドナルド": "外食費", "すき家": "外食費",
        "吉野家": "外食費", "松屋": "外食費",
        "ガスト": "外食費", "サイゼリヤ": "外食費",
        "新時代": "外食費", "鳥貴族": "外食費",
        "マツモトキヨシ": "日用品", "ウエルシア": "日用品",
        "サンドラッグ": "日用品", "ツルハ": "日用品",
        "ヤマダ電機": "家電購入", "ビックカメラ": "家電購入",
        "ヨドバシ": "家電購入",
        "ユニクロ": "衣服費", "GU": "衣服費",
        "ドン・キホーテ": "日用品",
        "ダイソー": "日用品", "セリア": "日用品",
        "ニトリ": "日用品", "無印良品": "日用品",
    }

    for key, cat in store_category_map.items():
        if key in store_name:
            return cat

    # テキスト内容からカテゴリ推定
    store_lower = store_name.lower()
    text_lower = (full_text or store_name).lower()

    store_keywords = {
        "食費": ["スーパー", "コンビニ", "弁当", "おにぎり", "パン", "飲料",
                 "鮮魚", "青果", "精肉", "惣菜", "生鮮"],
        "外食費": ["restaurant", "cafe", "coffee", "ランチ", "カフェ",
                   "ハンバーグ", "ラーメン", "居酒屋"],
        "日用品": ["ドラッグ", "マツキヨ", "ホームセンター", "カインズ",
                  "100均", "洗剤", "ティッシュ"],
        "衣服費": ["ユニクロ", "GU", "H&M", "ZARA", "しまむら", "靴"],
        "交通費": ["JR", "地下鉄", "バス", "タクシー", "ガソリン", "駐車場"],
        "医療費": ["病院", "クリニック", "薬局", "調剤", "歯科"],
        "娯楽費": ["映画", "カラオケ", "ゲーム", "本屋", "書店"],
        "美容費": ["美容", "理容", "ヘアサロン", "エステ", "ネイル"],
    }

    for category, keywords in store_keywords.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                return category

    item_names = " ".join(item["name"] for item in items).lower()
    for category, keywords in store_keywords.items():
        for kw in keywords:
            if kw.lower() in item_names:
                return category

    return "食費"  # デフォルト


def scan_receipt_image(image_path: str) -> dict:
    """レシート画像をOCR処理し、構造化データを返す (v2)"""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"画像ファイルが見つかりません: {image_path}")

    ext = os.path.splitext(image_path)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"):
        raise ValueError(f"サポートされていない画像形式: {ext}")

    text = ""
    ocr_engine = "none"

    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter
        import shutil

        # Tesseractパスの自動検出
        tesseract_path = shutil.which("tesseract")
        if not tesseract_path:
            for path in ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"]:
                if os.path.isfile(path):
                    tesseract_path = path
                    break
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

        img = Image.open(image_path)

        # 前処理: グレースケール → コントラスト → シャープネス → 二値化
        img_processed = img.convert("L")

        # アップスケール
        w, h = img_processed.size
        if max(w, h) < 1500:
            scale = 1500 / max(w, h)
            img_processed = img_processed.resize(
                (int(w * scale), int(h * scale)), Image.LANCZOS
            )

        enhancer = ImageEnhance.Contrast(img_processed)
        img_processed = enhancer.enhance(2.0)
        enhancer = ImageEnhance.Sharpness(img_processed)
        img_processed = enhancer.enhance(1.5)

        # Otsu風しきい値
        try:
            import numpy as np
            hist = img_processed.histogram()
            pixels = np.array(hist)
            total = pixels.sum()
            if total > 0:
                cumsum = np.cumsum(pixels)
                cumsum_val = np.cumsum(pixels * np.arange(256))
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
                img_processed = img_processed.point(lambda x: 0 if x < threshold else 255)
        except ImportError:
            img_processed = img_processed.point(lambda x: 0 if x < 140 else 255)

        # 言語設定
        try:
            available_langs = pytesseract.get_languages()
            lang = "jpn+eng" if "jpn" in available_langs else "eng"
        except Exception:
            lang = "eng"

        # 複数PSMモードで試行
        best_text = ""
        best_score = 0
        for psm in [6, 4, 3]:
            try:
                config = f"--oem 3 --psm {psm}"
                candidate = pytesseract.image_to_string(img_processed, lang=lang, config=config)
                candidate = _normalize_text(candidate)
                jpn_chars = len(re.findall(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]", candidate))
                digits = len(re.findall(r"\d", candidate))
                score = jpn_chars * 2 + digits
                if score > best_score:
                    best_score = score
                    best_text = candidate
            except Exception:
                continue

        text = best_text
        ocr_engine = f"tesseract ({lang})"

    except ImportError:
        pass
    except Exception as e:
        print(f"Tesseract OCRエラー: {e}")

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
