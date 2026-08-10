#!/usr/bin/env bash
# SeedVR2 Video Restoration Toolbox - Setup (Linux/macOS)
# Equivalent of install.bat for Unix-like systems

set -e

echo "============================================"
echo "  SeedVR2 Video Restoration Toolbox - Setup"
echo "============================================"
echo ""

# Detect script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ============================================================
# 1. Detect Python interpreter (prefer system Python 3.12+)
# ============================================================
PYTHON_CMD=""

# 1a. Check for python3.12 explicitly
if command -v python3.12 &>/dev/null; then
    PYTHON_CMD="python3.12"
    echo "[OK] Found Python 3.12: $(which python3.12)"
elif command -v python3 &>/dev/null; then
    # Check if python3 is 3.12+
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
# 2. No suitable Python found
# ============================================================
if [ -z "$PYTHON_CMD" ]; then
    echo "[ERROR] Python 3.12+ not found!"
    echo ""
    echo "============================================"
    echo "  Please install Python 3.12+:"
    echo "============================================"
    echo ""
    echo "  Ubuntu/Debian:"
    echo "    sudo apt-get update"
    echo "    sudo apt-get install -y python3.12 python3.12-venv python3-pip"
    echo ""
    echo "  macOS (Homebrew):"
    echo "    brew install python@3.12"
    echo ""
    echo "  CentOS/RHEL/Fedora:"
    echo "    sudo dnf install -y python3.12 python3.12-pip"
    echo ""
    echo "  Or download from: https://www.python.org/downloads/"
    echo ""
    echo "============================================"
    exit 1
fi

echo "Using Python: $PYTHON_CMD"
$PYTHON_CMD --version
echo ""

# ============================================================
# 3. Check NVIDIA GPU
# ============================================================
echo "[Check] NVIDIA GPU..."
if command -v nvidia-smi &>/dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    echo "[OK] NVIDIA GPU detected: $GPU_NAME"
else
    echo "[!] nvidia-smi not found. NVIDIA GPU and driver are REQUIRED."
    echo "    SeedVR2 does not support CPU-only inference."
    echo ""
fi
echo ""

# ============================================================
# 4. Install PyTorch with CUDA support
# ============================================================
echo "[Install] Installing PyTorch with CUDA support..."
echo "          If download is too slow, install manually from:"
echo "          https://pytorch.org/get-started/locally/"
echo ""

# Detect CUDA version from nvidia-smi
CUDA_VERSION=""
if command -v nvidia-smi &>/dev/null; then
    CUDA_VERSION=$(nvidia-smi | grep "CUDA Version" | awk '{print $9}' 2>/dev/null || echo "")
fi

# Install PyTorch (default to cu121 for broad compatibility)
$PYTHON_CMD -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 --timeout 1200 --retries 10 || {
    echo "[WARN] PyTorch CUDA install failed, trying default index..."
    $PYTHON_CMD -m pip install torch torchvision torchaudio --timeout 1200 --retries 10
}

# ============================================================
# 5. Install other dependencies
# ============================================================
echo ""
echo "[Install] Installing Python dependencies..."
$PYTHON_CMD -m pip install -r requirements.txt --timeout 300 --retries 3 || {
    echo "[WARN] Some dependencies failed to install"
}

echo ""
echo "============================================"
echo "  Installation complete!"
echo "  Run ./start.sh to launch the application"
echo "============================================"
