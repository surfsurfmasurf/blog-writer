#!/usr/bin/env bash
set -euo pipefail

echo "========================================"
echo " Blog Engine Setup (Linux / macOS)"
echo "========================================"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# ─── conda 환경 생성 ─────────────────────────────────
if command -v conda &>/dev/null; then
    echo "[INFO] conda detected"
    if conda env list | grep -q "blog-writer"; then
        echo "[INFO] Updating existing conda env: blog-writer"
        conda env update -f environment.yml --prune
    else
        echo "[INFO] Creating conda env: blog-writer"
        conda env create -f environment.yml
    fi
    echo "[OK] conda env ready. Activate with: conda activate blog-writer"
else
    echo "[WARN] conda not found. Falling back to venv + pip"
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    echo "[OK] venv ready. Activate with: source venv/bin/activate"
fi

# ─── .env 파일 생성 ──────────────────────────────────
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[OK] .env created. Fill in your API keys: $PROJECT_DIR/.env"
else
    echo "[INFO] .env already exists"
fi

# ─── data 디렉토리 생성 ──────────────────────────────
DIRS=(
    data/topics
    data/collected
    data/discarded
    data/pending_review
    data/published
    data/analytics
    data/images
    data/drafts
    data/failed_outputs
    logs
)
for d in "${DIRS[@]}"; do
    mkdir -p "$d"
done
echo "[OK] data directories created"

# ─── cron 등록 (선택) ────────────────────────────────
echo ""
read -rp "cron에 매일 09:00 자동 실행을 등록할까요? (y/N): " REGISTER_CRON
if [[ "$REGISTER_CRON" =~ ^[Yy]$ ]]; then
    CONDA_PATH="$(which conda 2>/dev/null || true)"
    if [ -n "$CONDA_PATH" ]; then
        CONDA_BASE="$(conda info --base)"
        CRON_CMD="0 9 * * * source ${CONDA_BASE}/etc/profile.d/conda.sh && conda activate blog-writer && cd ${PROJECT_DIR} && python run.py >> ${PROJECT_DIR}/logs/cron.log 2>&1"
    else
        CRON_CMD="0 9 * * * cd ${PROJECT_DIR} && ${PROJECT_DIR}/venv/bin/python run.py >> ${PROJECT_DIR}/logs/cron.log 2>&1"
    fi

    # 기존 cron에 중복 등록 방지
    (crontab -l 2>/dev/null | grep -v "blog-writer.*run.py"; echo "$CRON_CMD") | crontab -
    echo "[OK] cron registered: daily 09:00"
    echo "     확인: crontab -l"
else
    echo "[INFO] cron registration skipped"
fi

echo ""
echo "========================================"
echo " Setup Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Edit .env and fill in API keys (GEMINI_API_KEY 필수)"
echo "  2. python scripts/get_token.py  (Google OAuth token)"
echo "  3. Test run:"
echo "     conda activate blog-writer"
echo "     python run.py --dry-run"
echo ""
