# WiFiSense-CLI

Lightweight Terminal WiFi Signal Intelligence & IoT Event Engine.

A zero-dependency, cross-platform Python CLI tool for WiFi signal monitoring,
analysis, and event-driven automation.

## Features

- **WiFi Signal Scanning** - Cross-platform RSSI collection (Linux/macOS/Windows)
- **Signal Analysis** - Moving average, EWMA, Z-Score/IQR anomaly detection, trend analysis
- **Event Engine** - Rule-based triggers with shell, webhook, ntfy.sh, and log actions
- **TUI Dashboard** - Real-time terminal UI with curses (fallback for Windows)
- **Data Management** - JSON persistence, CSV export, session management
- **Zero Dependencies** - Uses only Python standard library

## Installation

```bash
pip install -e .
```

Or run directly:
```bash
python -m wifisense --help
```

## Usage

```bash
# Single scan
python -m wifisense scan

# Continuous monitoring with recording
python -m wifisense monitor -d

# Analyze recorded session
python -m wifisense analyze --latest --stats

# Manage event rules
python -m wifisense events list
python -m wifisense events add -f rules.json

# View configuration
python -m wifisense config show

# Launch TUI dashboard
python -m wifisense dashboard
```

## Requirements

- Python >= 3.8
- No external dependencies

## License

MIT
