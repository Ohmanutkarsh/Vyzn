#!/usr/bin/env bash
# ==============================================================================
# VYZN Netra - 1-Click Linux Systemd Service Installer for Commodity Mini-PCs
# Deploys VYZN as a systemd service on Ubuntu / Debian x86_64 or ARM SBCs.
# ==============================================================================

set -e

echo "============================================================"
echo "VYZN NETRA - ZERO-HARDWARE LINUX SERVICE INSTALLER"
echo "============================================================"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$(which python3 || echo "")"

if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: python3 not found. Installing python3 and pip..."
    sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv ffmpeg
    PYTHON_BIN="$(which python3)"
fi

echo "[OK] Project Directory: $PROJECT_DIR"
echo "[OK] Python Binary: $PYTHON_BIN"

# Install Python requirements
if [ -f "$PROJECT_DIR/requirements.txt" ]; then
    echo "[*] Installing Python dependencies..."
    $PYTHON_BIN -m pip install --upgrade pip
    $PYTHON_BIN -m pip install -r "$PROJECT_DIR/requirements.txt"
fi

# Create systemd service unit
SERVICE_FILE="/etc/systemd/system/vyzn-edge.service"
echo "[*] Generating systemd unit: $SERVICE_FILE..."

sudo bash -c "cat <<EOF > $SERVICE_FILE
[Unit]
Description=VYZN Netra AI Edge Surveillance Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_BIN $PROJECT_DIR/run_edge.py
Restart=always
RestartSec=5s
Nice=5
LimitNOFILE=65536
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF"

echo "[*] Enabling and starting vyzn-edge.service..."
sudo systemctl daemon-reload
sudo systemctl enable vyzn-edge.service
sudo systemctl restart vyzn-edge.service

echo "============================================================"
echo "[SUCCESS] VYZN Edge Service is now active and enabled on boot!"
echo "Status check: sudo systemctl status vyzn-edge.service"
echo "Logs: journalctl -u vyzn-edge.service -f"
echo "============================================================"
