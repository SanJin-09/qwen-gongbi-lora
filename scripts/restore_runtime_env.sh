#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/featurize/work/qwen-gongbi-lora"
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/configs/seed_api.env"

cd "$PROJECT_DIR"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "[setup] creating venv: $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "[setup] installing/updating required packages"
python3 -m pip install -U pip
python3 -m pip install -r requirements.txt
python3 -m pip install "volcengine-python-sdk[ark]" "httpx[socks]" pillow requests

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[error] missing $ENV_FILE"
  echo "create it first, with:"
  echo 'export ARK_API_KEY="your_real_key"'
  echo 'export ARK_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"'
  echo 'export DOUBAO_IMAGE_MODEL="doubao-seedream-5-0-260128"'
  exit 1
fi

source "$ENV_FILE"

echo "[verify] runtime"
python3 - <<'PY'
import os
import importlib.util

checks = {
    "ARK_API_KEY": "SET" if os.environ.get("ARK_API_KEY") else "MISSING",
    "ARK_BASE_URL": os.environ.get("ARK_BASE_URL", "MISSING"),
    "DOUBAO_IMAGE_MODEL": os.environ.get("DOUBAO_IMAGE_MODEL", "MISSING"),
    "volcenginesdkarkruntime": "OK" if importlib.util.find_spec("volcenginesdkarkruntime") else "MISSING",
    "httpx": "OK" if importlib.util.find_spec("httpx") else "MISSING",
    "socksio": "OK" if importlib.util.find_spec("socksio") else "MISSING",
    "PIL": "OK" if importlib.util.find_spec("PIL") else "MISSING",
    "requests": "OK" if importlib.util.find_spec("requests") else "MISSING",
}

for key, value in checks.items():
    print(f"{key}: {value}")

failed = [
    key for key, value in checks.items()
    if value in {"MISSING", ""}
]

if failed:
    raise SystemExit(f"runtime check failed: {failed}")
PY

echo "[ok] runtime environment is ready"
echo
echo "Run this in your current shell to keep the environment active:"
echo "source $VENV_DIR/bin/activate && source $ENV_FILE"
