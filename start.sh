#!/bin/bash
# =============================================================================
# RainCollector — Linux startup script (equivalent of start.bat)
# =============================================================================
# Requires X11 with HDMI dummy plug or Xvfb
# Make sure xdotool is installed: sudo apt install xdotool
# =============================================================================

set -e

cd "$(dirname "$0")"

# X11 display (for HDMI dummy plug)
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "🚀 Starting RainCollector..."
echo "   DISPLAY=$DISPLAY"
echo "   Python: $(python3 --version)"

python3 main.py

echo ""
echo "Press Enter to exit..."
read
