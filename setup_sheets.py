#!/usr/bin/env python3
"""
家計Pro - Google スプレッドシート連携 ワンクリックセットアップ
このスクリプトを1回だけ実行すれば、以降は自動で連携されます。
"""
import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_DIR = os.path.join(BASE_DIR, "credentials")
SERVICE_ACCOUNT_FILE = os.path.join(CREDENTIALS_DIR, "service_account.json")

def main():
    print()
    print("=" * 56)
    print("  家計Pro - Google スプレッドシート連携セットアップ")
    print("=" * 56)
    print()

    # ── Step 1: gspread チェック ──
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        print("✅ Step 1/4: gspread インストール済み")
    except ImportError:
        print("❌ Step 1/4: gspread がありません。インストールします...")
        os.system(f"{sys.executable} -m pip install gspread google-auth")
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            print("✅ Step 1/4: gspread インストール完了")
        except ImportError:
            print("❌ インストールに失敗しました。以下を手動で実行してください:")
            print("   pip3 install gspread google-auth")
            return

    # ── Step 2: サービスアカウントキー チェック ──
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print()
        print("❌ Step 2/4: サービスアカウントキーが見つかりません")
        print()
        print("  以下のフォルダにJSONキーを配置してください:")
        print(f"  → {SERVICE_ACCOUNT_FILE}")
        print()
        print("  まだ作成していない場合:")
        print("  1. https://console.cloud.google.com にアクセス")
        print("  2. 「APIとサービス」→「認証情報」→「サービスアカウント」")
        print("  3. JSONキーをダウンロード")
        print(f"  4. credentials/ フォルダに service_account.json として保存")
        return
    else:
        print("✅ Step 2/4: サービスアカウントキー OK")

    # サービスアカウントのメールアドレスを取得
    with open(SERVICE_ACCOUNT_FILE, "r") as f:
        sa_data = json.load(f)
    sa_email = sa_data.get("client_email", "（不明）")

    # ── Step 3: スプレッドシートURL入力 ──
    print()
    print("─" * 56)
    print("  Step 3/4: スプレッドシートの準備")
    print("─" * 56)
    print()
    print("  Google Sheets で空のスプレッドシートを1つ作成し、")
    print("  以下のメールアドレスを「編集者」として共有してください:")
    print()
    print(f"  📧 {sa_email}")
    print()
    print("  ※ これは1回だけの作業です。")
    print("  ※ 共有後、スプレッドシートのURLをコピーしてください。")
    print()

    url = input("  スプレッドシートのURLを貼り付け → ").strip()
    if not url:
        print("  キャンセルしました。")
        return

    # ── Step 4: 接続 & シート構築 ──
    print()
    print("─" * 56)
    print("  Step 4/4: 接続 & シート構築中...")
    print("─" * 56)
    print()

    from google_sheets_sync import setup_with_existing_sheet
    setup_with_existing_sheet(url)

    print()
    print("=" * 56)
    print("  🎉 セットアップ完了！")
    print("=" * 56)
    print()
    print("  以降、Web UIで支出・収入を登録すると")
    print("  自動的にGoogleスプレッドシートにも反映されます。")
    print()
    print("  サーバーを再起動してご利用ください:")
    print("  → python3 web_app.py")
    print()


if __name__ == "__main__":
    main()
