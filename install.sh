#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLASMOID_ID="com.github.claude-usage"
PLASMOID_DIR="$HOME/.local/share/plasma/plasmoids/$PLASMOID_ID"
BIN_DIR="$HOME/.local/bin"

echo "=== Claude Usage Widget Installer ==="

# Install the fetch script
mkdir -p "$BIN_DIR"
cp "$SCRIPT_DIR/scripts/fetch_usage.py" "$BIN_DIR/claude-usage-fetch"
chmod +x "$BIN_DIR/claude-usage-fetch"
echo "Installed fetch script to $BIN_DIR/claude-usage-fetch"

# Copy icon into plasmoid package
mkdir -p "$SCRIPT_DIR/plasmoid/$PLASMOID_ID/contents/images"
cp "$SCRIPT_DIR/images/claude-color.svg" "$SCRIPT_DIR/plasmoid/$PLASMOID_ID/contents/images/"

# Install the plasmoid
[ -d "$PLASMOID_DIR" ] && rm -rf "$PLASMOID_DIR"
mkdir -p "$PLASMOID_DIR"
cp -r "$SCRIPT_DIR/plasmoid/$PLASMOID_ID/"* "$PLASMOID_DIR/"
echo "Installed plasmoid to $PLASMOID_DIR"

echo ""
echo "Done! Right-click your panel -> Add Widgets -> search 'Claude Usage'."
echo "If it doesn't appear, run: plasmashell --replace &"
