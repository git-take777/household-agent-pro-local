"""
家計Pro - Pay API連携モジュール
担当: バックエンド担当

楽天Pay、PayPay、LINE Payなどの決済サービスから
取引履歴を取得し、自動で家計簿に登録する。

注意:
  - 各決済サービスのAPI利用には事前登録・認証が必要です
  - APIキーは pay_config.json に保存されます
  - 現状、公式APIが制限されているサービスはCSVインポート方式を使用

対応サービス:
  1. 楽天Pay  : 楽天API (要: 楽天デベロッパー登録)
  2. PayPay   : CSV取引履歴インポート (公式APIは法人のみ)
  3. LINE Pay : CSV取引履歴インポート
  4. 汎用CSV  : 任意のCSV形式に対応
"""
import os
import json
import csv
from datetime import datetime, date
from typing import Dict, List, Optional
from config import get_all_expense_categories
from receipt_scanner import _guess_category

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PAY_CONFIG_FILE = os.path.join(CONFIG_DIR, "pay_config.json")


def _load_pay_config() -> dict:
    if os.path.exists(PAY_CONFIG_FILE):
        with open(PAY_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_pay_config(config: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(PAY_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# === CSV インポート（PayPay / LINE Pay / 汎用） ===

def import_paypay_csv(csv_path: str) -> List[dict]:
    """PayPayの取引履歴CSVをインポートする
    PayPayアプリ → マイページ → 取引履歴 → CSVダウンロード
    想定カラム: 日時, 取引種別, 店舗名, 金額, ステータス
    """
    return _import_generic_csv(
        csv_path,
        date_col="日時",
        store_col="店舗名",
        amount_col="金額",
        service_name="PayPay",
        date_format="%Y/%m/%d %H:%M",
    )


def import_linepay_csv(csv_path: str) -> List[dict]:
    """LINE Payの取引履歴CSVをインポートする
    LINE Pay → 設定 → 取引履歴エクスポート
    想定カラム: 取引日時, 取引先, 金額, 取引タイプ
    """
    return _import_generic_csv(
        csv_path,
        date_col="取引日時",
        store_col="取引先",
        amount_col="金額",
        service_name="LINE Pay",
        date_format="%Y-%m-%d %H:%M:%S",
    )


def import_rakuten_csv(csv_path: str) -> List[dict]:
    """楽天Payの利用明細CSVをインポートする
    楽天ペイアプリ → 利用履歴 → CSVエクスポート
    想定カラム: 利用日, 利用先, 利用金額, ポイント利用
    """
    return _import_generic_csv(
        csv_path,
        date_col="利用日",
        store_col="利用先",
        amount_col="利用金額",
        service_name="楽天Pay",
        date_format="%Y/%m/%d",
    )


def import_generic_csv(
    csv_path: str,
    date_col: str,
    store_col: str,
    amount_col: str,
    date_format: str = "%Y/%m/%d",
) -> List[dict]:
    """汎用CSVインポート: カラム名を指定してインポートする"""
    return _import_generic_csv(
        csv_path, date_col, store_col, amount_col,
        service_name="CSV", date_format=date_format,
    )


def _import_generic_csv(
    csv_path: str,
    date_col: str,
    store_col: str,
    amount_col: str,
    service_name: str,
    date_format: str,
) -> List[dict]:
    """CSVファイルを読み込み、取引データのリストを返す"""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSVファイルが見つかりません: {csv_path}")

    transactions = []
    encoding_options = ["utf-8", "shift_jis", "cp932", "euc-jp"]

    for encoding in encoding_options:
        try:
            with open(csv_path, "r", encoding=encoding) as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []

                # カラム名の部分一致検索
                actual_date_col = _find_column(headers, date_col)
                actual_store_col = _find_column(headers, store_col)
                actual_amount_col = _find_column(headers, amount_col)

                if not all([actual_date_col, actual_store_col, actual_amount_col]):
                    missing = []
                    if not actual_date_col:
                        missing.append(f"日付({date_col})")
                    if not actual_store_col:
                        missing.append(f"店舗({store_col})")
                    if not actual_amount_col:
                        missing.append(f"金額({amount_col})")
                    raise ValueError(
                        f"必要なカラムが見つかりません: {', '.join(missing)}\n"
                        f"CSVのカラム: {headers}"
                    )

                for row in reader:
                    try:
                        raw_date = row[actual_date_col].strip()
                        raw_amount = row[actual_amount_col].strip()
                        store_name = row[actual_store_col].strip()

                        # 日付パース
                        try:
                            dt = datetime.strptime(raw_date, date_format)
                        except ValueError:
                            for fmt in ["%Y/%m/%d", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S"]:
                                try:
                                    dt = datetime.strptime(raw_date, fmt)
                                    break
                                except ValueError:
                                    continue
                            else:
                                continue

                        # 金額パース（マイナス記号、カンマ、円記号を除去）
                        amount_str = raw_amount.replace(",", "").replace("¥", "").replace("￥", "").replace("円", "")
                        amount = abs(int(float(amount_str)))

                        if amount <= 0 or amount > 10000000:
                            continue

                        category = _guess_category(store_name, [])

                        transactions.append({
                            "date": dt.strftime("%Y-%m-%d"),
                            "store_name": store_name,
                            "amount": amount,
                            "category_guess": category,
                            "service": service_name,
                            "raw_date": raw_date,
                        })
                    except (ValueError, KeyError):
                        continue

            break  # エンコーディング成功
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"CSVファイルのエンコーディングを認識できません: {csv_path}")

    return transactions


def _find_column(headers: List[str], target: str) -> Optional[str]:
    """カラム名の完全一致→部分一致で検索"""
    for h in headers:
        if h.strip() == target:
            return h
    for h in headers:
        if target in h.strip() or h.strip() in target:
            return h
    return None


def register_transactions(transactions: List[dict], auto_confirm: bool = False) -> List[dict]:
    """取引データを家計簿に一括登録する"""
    from data_manager import add_expense

    registered = []
    for tx in transactions:
        if not auto_confirm:
            print(f"\n{tx['date']} | {tx['store_name']} | {tx['amount']:,}円 | → {tx['category_guess']}")
            confirm = input("  登録しますか？ (y/n/カテゴリ変更→カテゴリ名): ").strip()
            if confirm.lower() == "n":
                continue
            if confirm.lower() != "y" and confirm in get_all_expense_categories():
                tx["category_guess"] = confirm

        try:
            entry = add_expense(
                date_str=tx["date"],
                category=tx["category_guess"],
                amount=tx["amount"],
                memo=f"[{tx.get('service', '')}] {tx['store_name']}",
            )
            registered.append(entry)
        except Exception as e:
            print(f"  登録エラー: {e}")

    return registered


# === 楽天API連携（将来実装用のスケルトン） ===

def setup_rakuten_api(client_id: str, client_secret: str):
    """楽天APIの認証情報を設定する

    楽天デベロッパー登録: https://webservice.rakuten.co.jp/
    必要な権限: 楽天ペイ利用履歴API

    料金: 基本無料（APIコール数制限あり）
      - 無料枠: 1日あたり約1000リクエスト
      - 商用利用: 要問い合わせ
    """
    config = _load_pay_config()
    config["rakuten"] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "setup_date": datetime.now().isoformat(),
    }
    _save_pay_config(config)
    print("楽天API設定を保存しました。")


def fetch_rakuten_transactions(start_date: str = None, end_date: str = None) -> List[dict]:
    """楽天APIから取引履歴を取得する（スケルトン）

    注意: 楽天ペイの個人向けAPIは現状制限されています。
    代替手段:
      1. 楽天ペイアプリからCSVエクスポート → import_rakuten_csv() を使用
      2. 楽天カードの利用明細CSV → import_generic_csv() を使用
    """
    config = _load_pay_config()
    if "rakuten" not in config:
        raise ValueError(
            "楽天APIが設定されていません。\n"
            "  setup_rakuten_api(client_id, client_secret) を実行するか、\n"
            "  CSVインポート: import_rakuten_csv('ファイルパス') を使用してください。"
        )

    print("注意: 楽天ペイの個人向け取引履歴APIは現在制限されています。")
    print("代替手段として以下をお試しください:")
    print("  1. 楽天ペイアプリ → 利用履歴 → CSV出力")
    print("  2. python kakeibo_pro.py import-csv rakuten <CSVファイルパス>")
    return []


# === サービス一覧・ヘルプ ===

PAY_SERVICES = {
    "paypay": {
        "name": "PayPay",
        "import_func": import_paypay_csv,
        "api_available": False,
        "csv_guide": "PayPayアプリ → マイページ → 取引履歴 → CSVダウンロード",
        "cost": "無料（CSV方式）",
    },
    "linepay": {
        "name": "LINE Pay",
        "import_func": import_linepay_csv,
        "api_available": False,
        "csv_guide": "LINE Pay → 設定 → 取引履歴エクスポート",
        "cost": "無料（CSV方式）",
    },
    "rakuten": {
        "name": "楽天Pay",
        "import_func": import_rakuten_csv,
        "api_available": True,
        "csv_guide": "楽天ペイアプリ → 利用履歴 → CSV出力",
        "api_cost": "基本無料（楽天デベロッパー登録が必要、1日1000リクエスト制限）",
        "cost": "無料（CSV方式）/ API: 基本無料",
    },
}


def show_pay_services():
    """対応決済サービスの一覧を表示"""
    print("\n=== 対応決済サービス ===")
    for key, svc in PAY_SERVICES.items():
        api_status = "API対応" if svc["api_available"] else "CSV方式"
        print(f"\n  {svc['name']} ({api_status})")
        print(f"    コスト: {svc['cost']}")
        print(f"    CSV取得方法: {svc['csv_guide']}")
        print(f"    インポート: python kakeibo_pro.py import-csv {key} <CSVファイルパス>")
