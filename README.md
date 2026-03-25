# Claude Usage Widget for KDE Plasma 6

A taskbar widget that shows your Claude Code 5-hour (blue) and weekly (orange) usage limits as percentages.

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

- **Panel**: Shows two percentages — blue = 5-hour limit, orange = weekly limit
- **Hover**: Tooltip with exact percentages and reset times
- **Click**: Opens dropdown with progress bars, reset countdowns, and controls
- **Refresh slider**: Adjust polling interval from 1–60 minutes (default 10)
- **Login/Logout**: Managed through the widget dropdown

## How it works

The widget periodically runs a Python script that makes a minimal API call (1-token Haiku request) using your Claude Code OAuth credentials. Rate limit utilization is returned in response headers (`anthropic-ratelimit-unified-5h-utilization` / `7d-utilization`) and cached in `~/.cache/claude-usage/usage.json`.

When Claude Code is running, the manual refresh button is disabled to avoid interference, but background polling continues at the configured interval.

Percentages may differ from the web UI by up to 1% due to ceiling rounding.

## Initial login

If you log in via the widget's "Login with Claude Code" button, you may need to **run `claude` once in a terminal** afterward to fully initialize the API session before usage data appears. Subsequent refreshes will work automatically without Claude Code open.

## Uninstall

```bash
rm -rf ~/.local/share/plasma/plasmoids/com.github.claude-usage
rm ~/.local/bin/claude-usage-fetch
rm -rf ~/.cache/claude-usage
```
