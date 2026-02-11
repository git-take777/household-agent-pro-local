#!/bin/zsh
# ============================================================
#  家計Pro - Web サーバー起動スクリプト
# ============================================================
#
#  使い方:
#    cd /Users/take/App/WebApp/claude_code/HouseholdFinanceProAgent
#    chmod +x start_server.sh
#    ./start_server.sh
#
# ============================================================

echo "============================================"
echo "  家計Pro - Web サーバー起動"
echo "============================================"
echo ""

# --- 現在のディレクトリに移動 ---
cd "$(dirname "$0")"

# --- Python確認 ---
if ! command -v python3 &> /dev/null; then
    echo "エラー: python3 がインストールされていません。"
    echo "  brew install python3"
    exit 1
fi

# --- pip パッケージ確認 & インストール ---
echo "[1/3] 依存パッケージを確認中..."
python3 -c "import flask" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "  Flask がありません。インストールします..."
    pip3 install -r requirements.txt
    echo ""
fi

# --- Tesseract 確認 ---
echo "[2/3] Tesseract OCR を確認中..."
if command -v tesseract &> /dev/null; then
    echo "  Tesseract: $(tesseract --version 2>&1 | head -1)"
    # 日本語データがあるかチェック
    if tesseract --list-langs 2>&1 | grep -q "jpn"; then
        echo "  日本語OCR: 利用可能"
    else
        echo "  日本語OCR: 未インストール"
        echo "  (インストール推奨: brew install tesseract-lang)"
        echo "  ※英語OCRのみでも動作します"
    fi
else
    echo "  Tesseract がありません。レシートOCR機能を使う場合:"
    echo "    brew install tesseract"
    echo "    brew install tesseract-lang  (日本語対応)"
    echo "  ※OCR以外の機能は問題なく使えます"
fi

# --- サーバー起動 ---
echo ""
echo "[3/3] サーバーを起動します..."
echo ""
echo "============================================"
echo "  http://localhost:8080 をブラウザで開いてください"
echo "  停止: Ctrl+C"
echo "============================================"
echo ""

python3 web_app.py
