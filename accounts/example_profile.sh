#!/bin/bash
# =============================================================================
# Template script for launching a browser profile on Linux
# =============================================================================
# Copy this file and configure it for each profile:
#   cp example_profile.sh MyProfile.sh
#   nano MyProfile.sh
#
# Each .sh file in the accounts/ folder is the Linux equivalent of a .lnk
# shortcut on Windows. It will be launched automatically during rain collection.
# =============================================================================

# === SETTINGS (customize for your profile) ===
PROFILE_NAME="ExampleProfile"
PROFILE_DIR="$HOME/.config/chromium-profiles/$PROFILE_NAME"
# Browser binary — set to your ungoogled-chromium path:
CHROME_BIN="/usr/bin/chromium"
# Alternatives:
#   /usr/bin/ungoogled-chromium
#   /usr/bin/chromium-browser
#   /usr/bin/google-chrome-stable
#   /snap/bin/chromium

export DISPLAY="${DISPLAY:-:0}"

exec "$CHROME_BIN" \
    --user-data-dir="$PROFILE_DIR" \
    --profile-directory="$PROFILE_NAME" \
    --disable-dev-shm-usage \
    --disable-gpu \
    --window-size=1920,1080 \
    --window-position=0,0 \
    "https://bandit.camp/" &
