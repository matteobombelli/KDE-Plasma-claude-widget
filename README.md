# Claude Usage Widget for KDE Plasma 6

A taskbar widget that shows your Claude Code 5-hour (blue) and weekly (orange) usage limits.

## Requirements

- KDE Plasma 6
- Python 3
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI installed and authenticated (`claude auth login`)

## Install

```bash
git clone https://github.com/matteobombelli/KDE-Plasma-claude-widget.git
cd KDE-Plasma-claude-widget
chmod +x install.sh
./install.sh
```

Then right-click your panel → **Add Widgets** → search **"Claude Usage"** → drag to panel.

If it doesn't appear, restart Plasma: `plasmashell --replace &`

## Usage

- **Panel**: Shows `XX% [icon] XX%` — blue = 5-hour limit, orange = weekly limit
- **Hover**: Tooltip with exact percentages and reset times
- **Click**: Opens dropdown with progress bars, reset countdowns, and controls
- **Refresh slider**: Adjust polling interval from 1–60 minutes (default 10)
- **Login/Logout**: Managed through the dropdown

## How it works

The widget periodically runs a Python script that makes a minimal API call (1-token Haiku request) using your Claude Code OAuth credentials. Rate limit utilization comes back in response headers (`anthropic-ratelimit-unified-5h-utilization` / `7d-utilization`). Results are cached in `~/.cache/claude-usage/usage.json`.

Percentages may differ from the web UI by up to 1% due to API rounding.

## Uninstall

```bash
rm -rf ~/.local/share/plasma/plasmoids/com.github.claude-usage
rm ~/.local/bin/claude-usage-fetch
rm -rf ~/.cache/claude-usage
```
