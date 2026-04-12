#!/bin/bash
# =============================================================================
# RainCollector — Linux startup script (аналог start.bat)
# =============================================================================
# Для работы требуется X11 с HDMI-заглушкой или Xvfb
# Убедитесь что xdotool установлен: sudo apt install xdotool
# =============================================================================

set -e

cd "$(dirname "$0")"

# X11 display (для HDMI-заглушки)
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

# Активация виртуального окружения
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "🚀 Запуск RainCollector..."
echo "   DISPLAY=$DISPLAY"
echo "   Python: $(python3 --version)"

python3 main.py

echo ""
echo "Нажмите Enter для выхода..."
read
