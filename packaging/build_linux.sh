#!/bin/sh
# Build ModBridge on Linux into a single binary via PyInstaller.
# Usage:
#   sh packaging/build_linux.sh            # build only -> dist/ModBridge
#   sh packaging/build_linux.sh --install  # build + install into ~/.local
#
# System dependencies (Debian/Ubuntu), required BEFORE building/running PySide6:
#   sudo apt install python3-venv libgl1 libegl1 libfontconfig1 \
#     libxkbcommon-x11-0 libdbus-1-3 libxcb-cursor0
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found. Install it first (e.g. sudo apt install python3 python3-venv)." >&2
    exit 1
fi

VENV_DIR="$ROOT_DIR/.venv-build"
if [ ! -x "$VENV_DIR/bin/python" ]; then
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r requirements.txt pyinstaller

"$VENV_DIR/bin/python" -m PyInstaller --noconfirm --clean --onefile \
    --name ModBridge \
    --add-data "modrinth_app/locales:modrinth_app/locales" \
    --add-data "assets:assets" \
    main.py

echo "Done: $ROOT_DIR/dist/ModBridge"

if [ "${1:-}" = "--install" ]; then
    BIN_DIR="$HOME/.local/bin"
    APP_DIR="$HOME/.local/share/applications"
    ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
    mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR"
    cp -f "$ROOT_DIR/dist/ModBridge" "$BIN_DIR/ModBridge"
    chmod +x "$BIN_DIR/ModBridge"
    cp -f "$ROOT_DIR/assets/icon.png" "$ICON_DIR/ModBridge.png"
    _exec_escaped="$(printf '%s' "$BIN_DIR/ModBridge" | sed 's/[&|\]/\\&/g')"
    sed "s|@EXEC@|$_exec_escaped|" "$ROOT_DIR/packaging/ModBridge.desktop" \
        > "$APP_DIR/ModBridge.desktop"
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
    echo "Installed: $BIN_DIR/ModBridge (+ menu shortcut)"
fi
