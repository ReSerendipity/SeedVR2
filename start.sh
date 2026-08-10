#!/usr/bin/env bash
# SeedVR2 Video Restoration Toolbox - Launcher (Linux/macOS)
# Equivalent of start.bat for Unix-like systems

set -e

# Fix OMP duplicate library issue
export KMP_DUPLICATE_LIB_OK=TRUE

echo "============================================"
echo "  SeedVR2 Video Restoration Toolbox"
echo "============================================"
echo ""

# Detect script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ============================================================
# 1. Detect Python interpreter (prefer system Python 3.12+)
# ============================================================
PYTHON_CMD=""

if command -v python3.12 &>/dev/null; then
    PYTHON_CMD="python3.12"
    echo "[OK] Found Python 3.12: $(which python3.12)"
elif command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 12 ]; then
        PYTHON_CMD="python3"
        echo "[OK] Found Python 3: $(which python3) (version $PY_VERSION)"
    fi
elif command -v python &>/dev/null; then
    PY_VERSION=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 12 ]; then
        PYTHON_CMD="python"
        echo "[OK] Found Python: $(which python) (version $PY_VERSION)"
    fi
fi

# ============================================================
# 2. Check for virtual environment
# ============================================================
if [ -z "$PYTHON_CMD" ]; then
    # Check for .venv
    if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
        PYTHON_CMD="$SCRIPT_DIR/.venv/bin/python"
        echo "[OK] Found virtual environment: .venv/bin/python"
    fi
fi

# ============================================================
# 3. No Python found
# ============================================================
if [ -z "$PYTHON_CMD" ]; then
    echo "[ERROR] Python 3.12+ not found!"
    echo ""
    echo "============================================"
    echo "  Options:"
    echo "============================================"
    echo ""
    echo "  Option A - Install system Python:"
    echo "    Ubuntu/Debian: sudo apt-get install -y python3.12 python3.12-venv"
    echo "    macOS: brew install python@3.12"
    echo "    Then run: ./install.sh"
    echo ""
    echo "  Option B - Use virtual environment:"
    echo "    python3.12 -m venv .venv"
    echo "    source .venv/bin/activate"
    echo "    pip install -r requirements.txt"
    echo "    Then re-run: ./start.sh"
    echo ""
    echo "============================================"
    exit 1
fi

echo "Using Python: $PYTHON_CMD"
$PYTHON_CMD --version
echo ""

# ============================================================
# 4. Verify Python works
# ============================================================
if ! $PYTHON_CMD -c "import sys; sys.exit(0)" 2>/dev/null; then
    echo "[ERROR] Python interpreter failed to run"
    exit 1
fi

# ============================================================
# 5. Start application
# ============================================================
echo "[Start] Launching SeedVR2..."
$PYTHON_CMD bin/clean_launch.py

if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] Failed to start. Check logs/app.log"
    exit 1
fi
