#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
REQUIREMENTS_STAMP="$VENV_DIR/.requirements-installed"

cd "$ROOT_DIR"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "[setup] 创建 Python 虚拟环境..."
  python3 -m venv "$VENV_DIR"
fi

# requirements.txt 没变化时跳过安装，加快日常启动。
if [[ ! -f "$REQUIREMENTS_STAMP" || requirements.txt -nt "$REQUIREMENTS_STAMP" ]]; then
  echo "[setup] 安装或更新 Python 依赖..."
  "$VENV_DIR/bin/pip" install -r requirements.txt
  touch "$REQUIREMENTS_STAMP"
fi

if [[ ! -f .env ]]; then
  echo "[setup] 从示例创建 .env，请按需填写数据库和模型配置。"
  cp .env.example .env
fi

# 图片 OCR 依赖系统级 Tesseract；macOS 开发机缺失时自动补齐。
if ! command -v tesseract >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then
  echo "[setup] 安装图片 OCR 引擎 Tesseract..."
  HOMEBREW_NO_AUTO_UPDATE=1 brew install tesseract
fi

# Homebrew 默认只有英文模型，按需下载体积较小的简体中文语言数据。
if command -v tesseract >/dev/null 2>&1 \
  && ! tesseract --list-langs 2>/dev/null | grep -qx "chi_sim" \
  && command -v brew >/dev/null 2>&1; then
  echo "[setup] 安装 Tesseract 简体中文语言数据..."
  TESSDATA_DIR="$(brew --prefix tesseract)/share/tessdata"
  curl -fL --retry 3 \
    -o "$TESSDATA_DIR/chi_sim.traineddata" \
    https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/chi_sim.traineddata
fi

echo "[database] 升级数据库结构..."
"$VENV_DIR/bin/alembic" upgrade head

echo "[server] http://127.0.0.1:8000"
exec "$VENV_DIR/bin/uvicorn" app.main:app --reload --host 127.0.0.1 --port 8000
