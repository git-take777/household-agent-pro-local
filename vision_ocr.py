"""
家計Pro - Google Cloud Vision OCR モジュール
月1,000枚まで無料の TEXT_DETECTION を使用
使用量トラッキング + 警告システム付き

セットアップ:
  1. Google Cloud Console で Vision API を有効化
  2. サービスアカウントキー (JSON) を credentials/ に配置
  3. pip3 install google-cloud-vision

使用量管理:
  - data/vision_usage.json に月間使用量を記録
  - 無料枠 (1,000回/月) の80%到達で警告
  - 上限到達時は Tesseract にフォールバック
"""
import os
import io
import json
import re
from datetime import datetime, date
from pathlib import Path

# --- 設定 ---
MONTHLY_FREE_LIMIT = 1000       # Google Vision API 無料枠
WARNING_THRESHOLD = 0.80        # 80% で警告開始
HARD_LIMIT_ENABLED = True       # True = 無料枠超過時にブロック
CREDENTIALS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
USAGE_FILE = os.path.join(DATA_DIR, "vision_usage.json")

# --- 使用量トラッキング ---

def _load_usage():
    """月間使用量を読み込む"""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"month": "", "count": 0, "history": []}


def _save_usage(usage):
    """月間使用量を保存"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(usage, f, ensure_ascii=False, indent=2)


def get_usage_status():
    """
    現在の使用量ステータスを取得
    Returns:
        dict: {
            "month": "2026-02",
            "count": 42,
            "limit": 1000,
            "remaining": 958,
            "percentage": 4.2,
            "warning": False,
            "blocked": False,
            "message": "今月の使用量: 42/1,000 (残り958回)"
        }
    """
    usage = _load_usage()
    current_month = date.today().strftime("%Y-%m")

    # 月が変わったらリセット
    if usage.get("month") != current_month:
        if usage.get("month") and usage.get("count", 0) > 0:
            # 先月の記録を履歴に保存
            usage.setdefault("history", []).append({
                "month": usage["month"],
                "count": usage["count"],
            })
            # 履歴は直近12ヶ月分のみ保持
            usage["history"] = usage["history"][-12:]
        usage["month"] = current_month
        usage["count"] = 0
        _save_usage(usage)

    count = usage.get("count", 0)
    remaining = max(0, MONTHLY_FREE_LIMIT - count)
    percentage = (count / MONTHLY_FREE_LIMIT) * 100
    is_warning = percentage >= (WARNING_THRESHOLD * 100)
    is_blocked = HARD_LIMIT_ENABLED and count >= MONTHLY_FREE_LIMIT

    if is_blocked:
        msg = f"⛔ 今月の無料枠 ({MONTHLY_FREE_LIMIT}回) を使い切りました。Tesseract で代替します。"
    elif is_warning:
        msg = f"⚠️ 今月の使用量: {count}/{MONTHLY_FREE_LIMIT} (残り{remaining}回) - まもなく無料枠に到達します"
    else:
        msg = f"今月の使用量: {count}/{MONTHLY_FREE_LIMIT:,} (残り{remaining}回)"

    return {
        "month": current_month,
        "count": count,
        "limit": MONTHLY_FREE_LIMIT,
        "remaining": remaining,
        "percentage": round(percentage, 1),
        "warning": is_warning,
        "blocked": is_blocked,
        "message": msg,
    }


def _increment_usage():
    """使用量を1増やす"""
    usage = _load_usage()
    current_month = date.today().strftime("%Y-%m")
    if usage.get("month") != current_month:
        usage["month"] = current_month
        usage["count"] = 0
    usage["count"] = usage.get("count", 0) + 1
    _save_usage(usage)
    return usage["count"]


# --- Google Cloud Vision API ---

def _get_vision_client():
    """Vision API クライアントを取得"""
    try:
        from google.cloud import vision
    except ImportError:
        raise ImportError(
            "google-cloud-vision がインストールされていません。\n"
            "  pip3 install google-cloud-vision"
        )

    # サービスアカウントキーの検索
    key_path = None
    if os.path.isdir(CREDENTIALS_DIR):
        for f in os.listdir(CREDENTIALS_DIR):
            if f.endswith(".json") and "service_account" in f.lower():
                key_path = os.path.join(CREDENTIALS_DIR, f)
                break
        # service_account が名前に含まれなくてもJSONキーを探す
        if not key_path:
            for f in os.listdir(CREDENTIALS_DIR):
                if f.endswith(".json"):
                    fpath = os.path.join(CREDENTIALS_DIR, f)
                    try:
                        with open(fpath) as jf:
                            data = json.load(jf)
                            if "type" in data and data["type"] == "service_account":
                                key_path = fpath
                                break
                    except (json.JSONDecodeError, IOError):
                        continue

    if key_path:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path
        client = vision.ImageAnnotatorClient()
    else:
        # 環境変数 GOOGLE_APPLICATION_CREDENTIALS が既に設定されている場合
        if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
            client = vision.ImageAnnotatorClient()
        else:
            raise FileNotFoundError(
                "サービスアカウントキーが見つかりません。\n"
                "credentials/ フォルダに service_account.json を配置してください。\n"
                "または GOOGLE_APPLICATION_CREDENTIALS 環境変数を設定してください。"
            )

    return client


def vision_ocr_image(image_bytes):
    """
    Google Cloud Vision API で画像からテキストを抽出
    Args:
        image_bytes: 画像のバイナリデータ
    Returns:
        dict: {
            "text": "抽出されたテキスト全文",
            "blocks": [{"text": "...", "confidence": 0.98, "bounds": [...]}],
            "success": True/False,
            "error": "",
            "usage": {...}  # 使用量情報
        }
    """
    from google.cloud import vision

    # 使用量チェック
    status = get_usage_status()
    if status["blocked"]:
        return {
            "text": "",
            "blocks": [],
            "success": False,
            "error": status["message"],
            "usage": status,
            "fallback_to_tesseract": True,
        }

    try:
        client = _get_vision_client()

        image = vision.Image(content=image_bytes)

        # TEXT_DETECTION (Document OCR よりレシート向き)
        response = client.text_detection(
            image=image,
            image_context=vision.ImageContext(
                language_hints=["ja", "en"]
            ),
        )

        # 使用量カウント
        current_count = _increment_usage()
        status = get_usage_status()

        if response.error.message:
            return {
                "text": "",
                "blocks": [],
                "success": False,
                "error": f"Vision API エラー: {response.error.message}",
                "usage": status,
                "fallback_to_tesseract": True,
            }

        # テキスト抽出
        texts = response.text_annotations
        full_text = texts[0].description if texts else ""

        # ブロック情報（位置・信頼度付き）
        blocks = []
        for annotation in texts[1:]:  # 最初は全文なのでスキップ
            bounds = annotation.bounding_poly.vertices
            blocks.append({
                "text": annotation.description,
                "bounds": [(v.x, v.y) for v in bounds],
            })

        return {
            "text": full_text,
            "blocks": blocks,
            "success": True,
            "error": "",
            "usage": status,
            "fallback_to_tesseract": False,
        }

    except ImportError as e:
        return {
            "text": "",
            "blocks": [],
            "success": False,
            "error": str(e),
            "usage": get_usage_status(),
            "fallback_to_tesseract": True,
        }
    except FileNotFoundError as e:
        return {
            "text": "",
            "blocks": [],
            "success": False,
            "error": str(e),
            "usage": get_usage_status(),
            "fallback_to_tesseract": True,
        }
    except Exception as e:
        return {
            "text": "",
            "blocks": [],
            "success": False,
            "error": f"Vision API 通信エラー: {e}",
            "usage": get_usage_status(),
            "fallback_to_tesseract": True,
        }


def vision_ocr_file(filepath):
    """
    画像ファイルパスから Vision OCR を実行
    """
    with open(filepath, "rb") as f:
        image_bytes = f.read()
    return vision_ocr_image(image_bytes)


# --- Vision API 有効化チェック ---

def check_vision_api():
    """
    Vision API が利用可能かチェック（実際にAPIを叩いて確認）
    Returns:
        dict: {"available": True/False, "error": "", "credentials_found": True/False}
    """
    result = {
        "available": False,
        "error": "",
        "credentials_found": False,
        "package_installed": False,
    }

    # パッケージチェック
    try:
        from google.cloud import vision
        result["package_installed"] = True
    except ImportError:
        result["error"] = "google-cloud-vision がインストールされていません。\n  pip3 install google-cloud-vision"
        return result

    # 認証情報チェック
    try:
        client = _get_vision_client()
        result["credentials_found"] = True
    except FileNotFoundError as e:
        result["error"] = str(e)
        return result

    # 実際の API 接続テスト（初回のみ、結果をキャッシュ）
    cache_file = os.path.join(DATA_DIR, "vision_api_check.json")
    os.makedirs(DATA_DIR, exist_ok=True)

    # キャッシュが1時間以内なら再利用
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache = json.load(f)
            cache_time = datetime.fromisoformat(cache.get("checked_at", "2000-01-01"))
            if (datetime.now() - cache_time).total_seconds() < 3600:
                result["available"] = cache.get("available", False)
                if not result["available"]:
                    result["error"] = cache.get("error", "Vision API が利用できません")
                return result
        except (json.JSONDecodeError, IOError, ValueError):
            pass

    # APIテスト実行
    try:
        from PIL import Image as PILImage
        test_img = PILImage.new("RGB", (10, 10), "white")
        buf = io.BytesIO()
        test_img.save(buf, format="PNG")
        test_bytes = buf.getvalue()

        image = vision.Image(content=test_bytes)
        response = client.text_detection(image=image)

        if response.error.message:
            err_msg = response.error.message
            if "PERMISSION_DENIED" in err_msg or "has not been used" in err_msg or "denied" in err_msg.lower():
                sa_info = _read_service_account_project()
                pid = sa_info["project_id"] if sa_info else ""
                result["error"] = (
                    f"Vision API が有効化されていません。\n"
                    f"プロジェクト: {pid}\n"
                    f"→ https://console.cloud.google.com/apis/library/vision.googleapis.com?project={pid}"
                )
            else:
                result["error"] = f"Vision API エラー: {err_msg}"
        else:
            result["available"] = True

    except Exception as e:
        err_str = str(e)
        if "403" in err_str or "PERMISSION_DENIED" in err_str or "has not been used" in err_str:
            sa_info = _read_service_account_project()
            pid = sa_info["project_id"] if sa_info else ""
            result["error"] = (
                f"Vision API が有効化されていません。\n"
                f"プロジェクト: {pid}\n"
                f"→ https://console.cloud.google.com/apis/library/vision.googleapis.com?project={pid}"
            )
        else:
            result["error"] = f"Vision API 接続エラー: {e}"

    # キャッシュ保存
    try:
        with open(cache_file, "w") as f:
            json.dump({
                "available": result["available"],
                "error": result.get("error", ""),
                "checked_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False)
    except IOError:
        pass

    return result


def _read_service_account_project():
    """サービスアカウントキーからプロジェクトIDを読み取る"""
    if os.path.isdir(CREDENTIALS_DIR):
        for f in os.listdir(CREDENTIALS_DIR):
            if f.endswith(".json"):
                fpath = os.path.join(CREDENTIALS_DIR, f)
                try:
                    with open(fpath) as jf:
                        data = json.load(jf)
                        if data.get("type") == "service_account":
                            return {
                                "project_id": data.get("project_id", ""),
                                "client_email": data.get("client_email", ""),
                                "file": f,
                            }
                except (json.JSONDecodeError, IOError):
                    continue
    return None


def _print_api_troubleshoot(err_str, sa_info):
    """APIエラーの原因を分析してガイドを表示"""
    err_lower = err_str.lower()
    pid = sa_info["project_id"] if sa_info else ""

    # --- ① 請求先アカウント (Billing) 未設定 ---
    if "billing" in err_lower or "billing is not enabled" in err_lower or "BILLING_DISABLED" in err_str:
        print("  🔍 原因: 請求先アカウント（Billing）が未設定です")
        print()
        print("  💡 Vision API は無料枠 (月1,000回) がありますが、")
        print("     Google Cloud の仕様上、請求先アカウントの設定が必須です。")
        print("     ※ 無料枠内なら請求は発生しません。")
        print()
        print(f"  → 請求先アカウントを設定してください:")
        print(f"    https://console.cloud.google.com/billing/linkedaccount?project={pid}")
        return

    # --- ② Vision API 未有効化 or 権限不足 ---
    if ("403" in err_str or "PERMISSION_DENIED" in err_str
            or "has not been used" in err_str or "denied" in err_lower
            or "permission" in err_lower):
        print("  🔍 考えられる原因:")
        print()
        print("  [原因1] 請求先アカウント（Billing）が未設定")
        print("     Vision API は有効化しても、請求先アカウントがないと動きません。")
        print("     無料枠内 (月1,000回) なら料金は発生しません。")
        if pid:
            print(f"     → https://console.cloud.google.com/billing/linkedaccount?project={pid}")
        print()
        print("  [原因2] Vision API が未有効化（別プロジェクトで有効化した）")
        if pid:
            print(f"     サービスアカウントのプロジェクト: {pid}")
            print(f"     → https://console.cloud.google.com/apis/library/vision.googleapis.com?project={pid}")
        print()
        print("  [原因3] 有効化したばかりで反映待ち（2〜5分かかることがあります）")
        print("     → 数分待ってもう一度実行してみてください")
        print()
        print("  [原因4] サービスアカウントの権限不足")
        print("     → IAMで「編集者」ロールが付与されているか確認:")
        if pid:
            print(f"       https://console.cloud.google.com/iam-admin/iam?project={pid}")
        return

    # --- ③ ネットワーク/その他 ---
    if "Could not automatically determine credentials" in err_str:
        print("  🔍 原因: 認証情報が正しく読み込めていません")
        print("     → credentials/ フォルダのサービスアカウントキーを確認してください")
    else:
        print("  🔍 ネットワーク接続を確認してください")
        if pid:
            print(f"     プロジェクト: {pid}")


# === セットアップスクリプト ===
if __name__ == "__main__":
    print("=" * 50)
    print("  Google Cloud Vision OCR セットアップ")
    print("=" * 50)

    # 1. パッケージチェック
    print("\n[1] パッケージチェック...")
    try:
        from google.cloud import vision
        print("  ✅ google-cloud-vision インストール済み")
    except ImportError:
        print("  ❌ google-cloud-vision が見つかりません")
        print("  → pip3 install google-cloud-vision を実行してください")
        exit(1)

    # 2. 認証情報チェック
    print("\n[2] 認証情報チェック...")
    sa_info = _read_service_account_project()
    try:
        client = _get_vision_client()
        print("  ✅ サービスアカウントキー検出")
        if sa_info:
            print(f"     ファイル: credentials/{sa_info['file']}")
            print(f"     プロジェクトID: {sa_info['project_id']}")
            print(f"     サービスアカウント: {sa_info['client_email']}")
    except FileNotFoundError as e:
        print(f"  ❌ {e}")
        exit(1)

    # 3. API 接続テスト
    print("\n[3] Vision API 接続テスト...")
    try:
        # 小さなテスト画像を送信
        from PIL import Image
        import io as _io

        # 10x10 白画像でテスト
        test_img = Image.new("RGB", (10, 10), "white")
        buf = _io.BytesIO()
        test_img.save(buf, format="PNG")
        test_bytes = buf.getvalue()

        image = vision.Image(content=test_bytes)
        response = client.text_detection(image=image)

        if response.error.message:
            err_msg = response.error.message
            print(f"  ❌ API レスポンスエラー:")
            print(f"     {err_msg}")
            _print_api_troubleshoot(err_msg, sa_info)
            exit(1)
        else:
            print("  ✅ Vision API 正常動作")
    except Exception as e:
        err_str = str(e)
        print(f"  ❌ 接続エラー:")
        # 改行して全文表示（見やすく）
        for line in err_str.split(". "):
            print(f"     {line.strip()}")
        print()
        _print_api_troubleshoot(err_str, sa_info)
        exit(1)

    # 4. 使用量表示
    print("\n[4] 使用量ステータス...")
    status = get_usage_status()
    print(f"  {status['message']}")

    print("\n" + "=" * 50)
    print("  ✅ セットアップ完了！Vision OCR が利用可能です")
    print("=" * 50)
