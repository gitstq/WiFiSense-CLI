"""
WiFiSense-CLI Package Entry Point

Allows running the package as a module: python -m wifisense
"""

from .cli import main
import sys


def run() -> None:
    """Entry point for python -m wifisense."""
    sys.exit(main())


if __name__ == "__main__":
    run()
