"""
WiFiSense-CLI - Lightweight Terminal WiFi Signal Intelligence & IoT Event Engine

A zero-dependency, cross-platform Python CLI tool for WiFi signal monitoring,
analysis, and event-driven automation.

Usage:
    python -m wifisense scan          Perform a single WiFi scan
    python -m wifisense monitor       Start continuous monitoring
    python -m wifisense analyze       Analyze recorded session data
    python -m wifisense events        Manage event rules
    python -m wifisense config        View/modify configuration
    python -m wifisense dashboard     Launch TUI dashboard
"""

__version__ = "0.1.0"
__author__ = "WiFiSense-CLI Contributors"
__description__ = "Lightweight Terminal WiFi Signal Intelligence & IoT Event Engine"
__license__ = "MIT"

from .cli import main

__all__ = ["main", "__version__"]
