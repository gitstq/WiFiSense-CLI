"""
WiFiSense-CLI Utility Module

Provides common utility functions including ANSI color output,
table formatting, cross-platform helpers, signal quality calculation,
and statistical computation tools.
"""

from __future__ import annotations

import math
import os
import platform
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# ANSI Color Utilities
# ---------------------------------------------------------------------------

class ANSI:
    """ANSI escape code constants for colored terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    BLINK = "\033[5m"
    REVERSE = "\033[7m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright foreground colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Background colors
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"


def supports_color() -> bool:
    """Check if the current terminal supports ANSI color codes."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if sys.platform == "win32":
        # Windows 10+ supports ANSI via VirtualTerminalProcessing
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # Check if stdout is a console
            stdout_handle = kernel32.GetStdHandle(-11)
            if stdout_handle == -1:
                return False
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode))
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            return bool(mode.value & 0x0004)
        except Exception:
            return False
    # On Unix-like systems, check if stdout is a TTY
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


# Global flag to enable/disable colors
_COLOR_ENABLED = supports_color()


def enable_color(enabled: bool = True) -> None:
    """Enable or disable colored output globally."""
    global _COLOR_ENABLED
    _COLOR_ENABLED = enabled


def colorize(text: str, color: str) -> str:
    """Wrap text with an ANSI color code if colors are enabled.

    Args:
        text: The text to colorize.
        color: An ANSI escape code string (e.g. ANSI.RED).

    Returns:
        The colorized text, or the original text if colors are disabled.
    """
    if _COLOR_ENABLED:
        return f"{color}{text}{ANSI.RESET}"
    return text


def style(text: str, *styles: str) -> str:
    """Apply multiple ANSI styles to text.

    Args:
        text: The text to style.
        *styles: ANSI escape code strings to apply.

    Returns:
        The styled text, or the original text if colors are disabled.
    """
    if _COLOR_ENABLED:
        prefix = "".join(styles)
        return f"{prefix}{text}{ANSI.RESET}"
    return text


# Signal strength color helpers
def rssi_color(rssi: float) -> str:
    """Return an ANSI color code based on RSSI signal strength.

    Args:
        rssi: The RSSI value in dBm (typically -30 to -90).

    Returns:
        ANSI color code: GREEN (>= -50), YELLOW (>= -65), RED (< -65).
    """
    if rssi >= -50:
        return ANSI.GREEN
    elif rssi >= -65:
        return ANSI.YELLOW
    else:
        return ANSI.RED


def rssi_bar(rssi: float, width: int = 20) -> str:
    """Generate a visual signal strength bar using Unicode block characters.

    Args:
        rssi: The RSSI value in dBm.
        width: The width of the bar in characters.

    Returns:
        A string representing the signal strength bar.
    """
    # Normalize RSSI from [-100, -30] to [0, 1]
    normalized = max(0.0, min(1.0, (rssi + 100) / 70.0))
    filled = int(normalized * width)
    empty = width - filled
    bar = "\u2588" * filled + "\u2591" * empty
    return colorize(bar, rssi_color(rssi))


def quality_color(quality: float) -> str:
    """Return an ANSI color code based on signal quality percentage.

    Args:
        quality: Signal quality as a percentage (0-100).

    Returns:
        ANSI color code based on quality level.
    """
    if quality >= 80:
        return ANSI.GREEN
    elif quality >= 50:
        return ANSI.YELLOW
    else:
        return ANSI.RED


# ---------------------------------------------------------------------------
# Table Formatting
# ---------------------------------------------------------------------------

def format_table(
    headers: List[str],
    rows: List[List[Any]],
    padding: int = 2,
    max_col_width: Optional[int] = None,
) -> str:
    """Format data as an aligned ASCII table.

    Args:
        headers: Column header strings.
        rows: List of rows, where each row is a list of cell values.
        padding: Horizontal padding inside each cell.
        max_col_width: Maximum width for any column. None means unlimited.

    Returns:
        A formatted multi-line string representing the table.
    """
    if not headers or not rows:
        return ""

    # Convert all cells to strings
    str_rows: List[List[str]] = []
    for row in rows:
        str_row = [str(cell) if cell is not None else "" for cell in row]
        str_rows.append(str_row)

    # Calculate column widths
    num_cols = len(headers)
    col_widths: List[int] = [len(h) for h in headers]
    for row in str_rows:
        for i, cell in enumerate(row):
            if i < num_cols:
                col_widths[i] = max(col_widths[i], len(cell))

    # Apply max column width
    if max_col_width is not None:
        col_widths = [min(w, max_col_width) for w in col_widths]

    # Truncate cells that exceed column width
    for row in str_rows:
        for i in range(min(len(row), num_cols)):
            if len(row[i]) > col_widths[i]:
                row[i] = row[i][: col_widths[i] - 3] + "..."

    # Build separator line
    sep_parts = []
    for w in col_widths:
        sep_parts.append("-" * (w + padding * 2))
    separator = "+" + "+".join(sep_parts) + "+"

    # Build header line
    header_parts = []
    for i, h in enumerate(headers):
        header_parts.append(h.ljust(col_widths[i]))
    header_line = "|" + "|".join(
        f"{' ' * padding}{part}{' ' * padding}" for part in header_parts
    ) + "|"

    # Build data lines
    data_lines: List[str] = []
    for row in str_rows:
        row_parts = []
        for i in range(num_cols):
            cell = row[i] if i < len(row) else ""
            row_parts.append(cell.ljust(col_widths[i]))
        line = "|" + "|".join(
            f"{' ' * padding}{part}{' ' * padding}" for part in row_parts
        ) + "|"
        data_lines.append(line)

    # Combine all parts
    lines = [separator, header_line, separator]
    lines.extend(data_lines)
    lines.append(separator)
    return "\n".join(lines)


def format_key_value(pairs: Dict[str, Any], indent: int = 2) -> str:
    """Format key-value pairs as aligned output.

    Args:
        pairs: Dictionary of key-value pairs.
        indent: Number of spaces for indentation.

    Returns:
        A formatted string with aligned key-value pairs.
    """
    if not pairs:
        return ""
    max_key_len = max(len(str(k)) for k in pairs.keys())
    lines: List[str] = []
    prefix = " " * indent
    for key, value in pairs.items():
        lines.append(f"{prefix}{str(key).ljust(max_key_len)} : {value}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cross-Platform Utilities
# ---------------------------------------------------------------------------

def get_platform() -> str:
    """Return a normalized platform identifier.

    Returns:
        One of 'linux', 'darwin', 'windows'.
    """
    system = platform.system().lower()
    if system == "linux":
        return "linux"
    elif system == "darwin":
        return "darwin"
    elif system == "windows":
        return "windows"
    else:
        return system


def is_linux() -> bool:
    """Check if running on Linux."""
    return get_platform() == "linux"


def is_macos() -> bool:
    """Check if running on macOS."""
    return get_platform() == "darwin"


def is_windows() -> bool:
    """Check if running on Windows."""
    return get_platform() == "windows"


def get_default_interface() -> str:
    """Attempt to determine the default WiFi interface name.

    Returns:
        The interface name string, or 'wlan0' as a default guess.
    """
    plat = get_platform()
    if plat == "linux":
        # Try to read from /proc/net/wireless
        try:
            with open("/proc/net/wireless", "r") as f:
                for line in f:
                    line = line.strip()
                    if ":" in line and not line.startswith("Inter"):
                        iface = line.split(":")[0].strip()
                        if iface:
                            return iface
        except (OSError, IOError):
            pass
        # Try common interface names
        for iface in ["wlan0", "wlp2s0", "wlp3s0", "wlo1"]:
            if os.path.exists(f"/sys/class/net/{iface}"):
                return iface
        return "wlan0"
    elif plat == "darwin":
        return "en0"
    elif plat == "windows":
        return "Wi-Fi"
    return "wlan0"


def run_command(
    cmd: List[str],
    timeout: float = 10.0,
    shell: bool = False,
) -> Tuple[int, str, str]:
    """Run an external command and return exit code, stdout, stderr.

    Args:
        cmd: Command and arguments as a list of strings.
        timeout: Maximum time to wait in seconds.
        shell: Whether to run through the shell.

    Returns:
        A tuple of (exit_code, stdout, stderr).
    """
    import subprocess

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except OSError as e:
        return -1, "", str(e)


def timestamp() -> str:
    """Return the current UTC timestamp in ISO 8601 format.

    Returns:
        ISO 8601 formatted timestamp string.
    """
    return datetime.now(timezone.utc).isoformat()


def timestamp_local() -> str:
    """Return the current local timestamp in ISO 8601 format.

    Returns:
        ISO 8601 formatted local timestamp string.
    """
    return datetime.now().astimezone().isoformat()


# ---------------------------------------------------------------------------
# Signal Quality Calculation
# ---------------------------------------------------------------------------

def rssi_to_quality(rssi: float) -> float:
    """Convert RSSI value to a signal quality percentage.

    Uses a linear mapping from the typical WiFi RSSI range
    [-100, -30] dBm to [0, 100]%.

    Args:
        rssi: RSSI value in dBm.

    Returns:
        Signal quality as a percentage (0-100).
    """
    # Clamp RSSI to [-100, -30]
    clamped = max(-100.0, min(-30.0, rssi))
    # Linear mapping
    quality = ((clamped + 100) / 70.0) * 100.0
    return round(quality, 1)


def rssi_to_dbm_quality(rssi: float) -> int:
    """Convert RSSI to a 0-100 integer quality score (Windows style).

    Args:
        rssi: RSSI value in dBm.

    Returns:
        Integer quality score from 0 to 100.
    """
    return int(rssi_to_quality(rssi))


def rssi_to_level(rssi: float) -> str:
    """Convert RSSI to a human-readable signal level description.

    Args:
        rssi: RSSI value in dBm.

    Returns:
        A string: 'Excellent', 'Good', 'Fair', or 'Weak'.
    """
    if rssi >= -50:
        return "Excellent"
    elif rssi >= -60:
        return "Good"
    elif rssi >= -70:
        return "Fair"
    else:
        return "Weak"


def dbm_to_watts(dbm: float) -> float:
    """Convert dBm to milliwatts.

    Args:
        dbm: Power in dBm.

    Returns:
        Power in milliwatts.
    """
    return 10.0 ** (dbm / 10.0)


def dbm_to_watts_str(dbm: float) -> str:
    """Convert dBm to a human-readable power string.

    Args:
        dbm: Power in dBm.

    Returns:
        Formatted string with appropriate unit (mW or uW).
    """
    mw = dbm_to_watts(dbm)
    if mw >= 1.0:
        return f"{mw:.2f} mW"
    elif mw >= 0.001:
        return f"{mw * 1000:.2f} uW"
    else:
        return f"{mw * 1e6:.2f} nW"


# ---------------------------------------------------------------------------
# Statistical Computation Tools
# ---------------------------------------------------------------------------

def moving_average(data: List[float], window: int) -> List[float]:
    """Compute a simple moving average over a data series.

    Args:
        data: List of numeric values.
        window: Number of samples in the moving window.

    Returns:
        List of averaged values. Length is len(data) - window + 1.
    """
    if not data:
        return []
    if len(data) < window:
        return data[:]
    result: List[float] = []
    for i in range(len(data) - window + 1):
        window_slice = data[i : i + window]
        result.append(sum(window_slice) / window)
    return result


def exponential_moving_average(
    data: List[float], alpha: float = 0.3
) -> List[float]:
    """Compute an exponential weighted moving average (EWMA).

    Args:
        data: List of numeric values.
        alpha: Smoothing factor between 0 and 1. Higher values give
               more weight to recent observations.

    Returns:
        List of EWMA values, same length as input data.
    """
    if not data:
        return []
    result: List[float] = [data[0]]
    for i in range(1, len(data)):
        ema = alpha * data[i] + (1 - alpha) * result[i - 1]
        result.append(ema)
    return result


def z_score(value: float, mean: float, std: float) -> float:
    """Calculate the Z-score of a value given a distribution.

    Args:
        value: The observed value.
        mean: The mean of the distribution.
        std: The standard deviation of the distribution.

    Returns:
        The Z-score.
    """
    if std == 0:
        return 0.0
    return (value - mean) / std


def z_score_anomaly(
    value: float, mean: float, std: float, threshold: float = 2.0
) -> bool:
    """Detect if a value is anomalous using the Z-score method.

    Args:
        value: The observed value.
        mean: The mean of the reference distribution.
        std: The standard deviation of the reference distribution.
        threshold: Z-score threshold for anomaly detection.

    Returns:
        True if the value is considered anomalous.
    """
    if std == 0:
        return False
    return abs(z_score(value, mean, std)) > threshold


def iqr_bounds(data: List[float], factor: float = 1.5) -> Tuple[float, float]:
    """Calculate IQR-based outlier bounds.

    Args:
        data: List of numeric values.
        factor: IQR multiplier for bounds (default 1.5 for mild outliers).

    Returns:
        A tuple of (lower_bound, upper_bound).
    """
    if len(data) < 4:
        return (min(data) if data else 0.0, max(data) if data else 0.0)
    sorted_data = sorted(data)
    n = len(sorted_data)
    q1 = sorted_data[n // 4]
    q3 = sorted_data[3 * n // 4]
    iqr = q3 - q1
    lower = q1 - factor * iqr
    upper = q3 + factor * iqr
    return (lower, upper)


def iqr_anomaly(value: float, data: List[float], factor: float = 1.5) -> bool:
    """Detect if a value is anomalous using the IQR method.

    Args:
        value: The observed value.
        data: Reference data for computing quartiles.
        factor: IQR multiplier for bounds.

    Returns:
        True if the value is considered anomalous.
    """
    if len(data) < 4:
        return False
    lower, upper = iqr_bounds(data, factor)
    return value < lower or value > upper


def linear_regression_slope(x: List[float], y: List[float]) -> float:
    """Calculate the slope of a simple linear regression.

    Args:
        x: Independent variable values (e.g., time indices).
        y: Dependent variable values (e.g., RSSI readings).

    Returns:
        The slope of the best-fit line.
    """
    n = len(x)
    if n < 2 or len(y) < 2 or n != len(y):
        return 0.0
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi ** 2 for xi in x)
    denominator = n * sum_x2 - sum_x ** 2
    if denominator == 0:
        return 0.0
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    return slope


def compute_statistics(data: List[float]) -> Dict[str, float]:
    """Compute basic descriptive statistics for a data series.

    Args:
        data: List of numeric values.

    Returns:
        Dictionary with keys: count, mean, median, stdev, min, max,
        range, q1, q3.
    """
    if not data:
        return {
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "stdev": 0.0,
            "min": 0.0,
            "max": 0.0,
            "range": 0.0,
            "q1": 0.0,
            "q3": 0.0,
        }
    sorted_data = sorted(data)
    n = len(sorted_data)
    return {
        "count": n,
        "mean": statistics.mean(data),
        "median": statistics.median(data),
        "stdev": statistics.stdev(data) if n > 1 else 0.0,
        "min": sorted_data[0],
        "max": sorted_data[-1],
        "range": sorted_data[-1] - sorted_data[0],
        "q1": sorted_data[n // 4],
        "q3": sorted_data[3 * n // 4],
    }


def euclidean_distance(v1: List[float], v2: List[float]) -> float:
    """Calculate the Euclidean distance between two vectors.

    Args:
        v1: First vector.
        v2: Second vector.

    Returns:
        Euclidean distance.
    """
    if len(v1) != len(v2):
        raise ValueError("Vectors must have the same length")
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculate cosine similarity between two vectors.

    Args:
        v1: First vector.
        v2: Second vector.

    Returns:
        Cosine similarity between -1 and 1.
    """
    if len(v1) != len(v2):
        raise ValueError("Vectors must have the same length")
    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a ** 2 for a in v1))
    mag2 = math.sqrt(sum(b ** 2 for b in v2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


# ---------------------------------------------------------------------------
# String / Template Utilities
# ---------------------------------------------------------------------------

def render_template(template: str, context: Dict[str, Any]) -> str:
    """Render a simple template string with {{variable}} placeholders.

    Args:
        template: Template string with {{key}} placeholders.
        context: Dictionary mapping keys to replacement values.

    Returns:
        The rendered string with all placeholders replaced.
    """
    def replacer(match: re.Match) -> str:
        key = match.group(1).strip()
        return str(context.get(key, match.group(0)))

    return re.sub(r"\{\{(\w+)\}\}", replacer, template)


def truncate(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate text to a maximum length, adding a suffix if truncated.

    Args:
        text: The input text.
        max_length: Maximum length of the output.
        suffix: Suffix to append when truncated.

    Returns:
        Truncated text.
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def bytes_to_human(num_bytes: int) -> str:
    """Convert bytes to a human-readable size string.

    Args:
        num_bytes: Number of bytes.

    Returns:
        Human-readable size string (e.g., '1.23 MB').
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to an integer.

    Args:
        value: The value to convert.
        default: Default value if conversion fails.

    Returns:
        Integer value or default.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to a float.

    Args:
        value: The value to convert.
        default: Default value if conversion fails.

    Returns:
        Float value or default.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Logging Helpers
# ---------------------------------------------------------------------------

class LogLevel:
    """Log level constants."""
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4

    _names = {
        0: "DEBUG",
        1: "INFO",
        2: "WARNING",
        3: "ERROR",
        4: "CRITICAL",
    }

    @classmethod
    def name(cls, level: int) -> str:
        """Get the string name for a log level."""
        return cls._names.get(level, "UNKNOWN")

    @classmethod
    def color(cls, level: int) -> str:
        """Get the ANSI color for a log level."""
        colors = {
            0: ANSI.BRIGHT_BLACK,
            1: ANSI.GREEN,
            2: ANSI.YELLOW,
            3: ANSI.RED,
            4: ANSI.BRIGHT_RED,
        }
        return colors.get(level, ANSI.WHITE)


def log_print(
    level: int,
    message: str,
    prefix: str = "WiFiSense",
) -> None:
    """Print a formatted log message to stderr.

    Args:
        level: Log level (use LogLevel constants).
        message: The log message.
        prefix: A prefix string for the log line.
    """
    ts = datetime.now().strftime("%H:%M:%S")
    level_name = LogLevel.name(level)
    level_color = LogLevel.color(level)
    formatted = (
        f"{ANSI.DIM}{ts}{ANSI.RESET} "
        f"[{colorize(level_name, level_color)}] "
        f"{colorize(prefix, ANSI.CYAN)}: "
        f"{message}"
    )
    print(formatted, file=sys.stderr)


def log_debug(message: str, prefix: str = "WiFiSense") -> None:
    """Print a DEBUG level log message."""
    log_print(LogLevel.DEBUG, message, prefix)


def log_info(message: str, prefix: str = "WiFiSense") -> None:
    """Print an INFO level log message."""
    log_print(LogLevel.INFO, message, prefix)


def log_warning(message: str, prefix: str = "WiFiSense") -> None:
    """Print a WARNING level log message."""
    log_print(LogLevel.WARNING, message, prefix)


def log_error(message: str, prefix: str = "WiFiSense") -> None:
    """Print an ERROR level log message."""
    log_print(LogLevel.ERROR, message, prefix)


def log_critical(message: str, prefix: str = "WiFiSense") -> None:
    """Print a CRITICAL level log message."""
    log_print(LogLevel.CRITICAL, message, prefix)
