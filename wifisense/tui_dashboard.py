"""
WiFiSense-CLI TUI Dashboard

Terminal User Interface dashboard built with the standard library curses
module. Provides real-time signal strength visualization, AP status panels,
event log scrolling, and environment fingerprint comparison. Supports
keyboard shortcuts for view switching and navigation.

Note: curses is available on Unix-like systems (Linux, macOS). On Windows,
this module provides a fallback to basic terminal output.
"""

from __future__ import annotations

import math
import os
import platform
import sys
import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

from .utils import (
    ANSI,
    rssi_bar,
    rssi_color,
    rssi_to_quality,
    rssi_to_level,
    safe_float,
    safe_int,
)


# ---------------------------------------------------------------------------
# Platform Check for Curses
# ---------------------------------------------------------------------------

def _curses_available() -> bool:
    """Check if the curses module is available."""
    if platform.system() == "Windows":
        return False
    try:
        import curses  # noqa: F401
        return True
    except ImportError:
        return False


_CURSES_AVAILABLE = _curses_available()


# ---------------------------------------------------------------------------
# ASCII Art Helpers (used in both curses and fallback modes)
# ---------------------------------------------------------------------------

def ascii_signal_chart(
    values: List[float],
    width: int = 60,
    height: int = 10,
    min_val: float = -100.0,
    max_val: float = -30.0,
) -> List[str]:
    """Generate an ASCII art signal strength chart.

    Args:
        values: List of RSSI values to plot.
        width: Width of the chart in characters.
        height: Height of the chart in rows.
        min_val: Minimum value for the Y axis.
        max_val: Maximum value for the Y axis.

    Returns:
        List of strings, each representing a row of the chart.
    """
    if not values:
        return [" " * width for _ in range(height)]

    # Normalize values to [0, height-1]
    range_val = max_val - min_val
    if range_val == 0:
        range_val = 1

    # Create a 2D grid
    grid = [[" " for _ in range(width)] for _ in range(height)]

    # Plot each value
    for i, val in enumerate(values):
        if i >= width:
            break
        normalized = (val - min_val) / range_val
        normalized = max(0.0, min(1.0, normalized))
        y = height - 1 - int(normalized * (height - 1))
        y = max(0, min(height - 1, y))
        grid[y][i] = "\u2588"  # Full block

    # Draw axis labels
    rows: List[str] = []
    for row_idx, row in enumerate(grid):
        y_val = max_val - (row_idx / (height - 1)) * range_val if height > 1 else max_val
        label = f"{y_val:>5.0f}"
        line = label + " |" + "".join(row)
        rows.append(line)

    return rows


def ascii_mini_chart(
    values: List[float],
    width: int = 20,
    height: int = 5,
) -> str:
    """Generate a compact single-string mini chart.

    Args:
        values: List of RSSI values.
        width: Chart width.
        height: Chart height.

    Returns:
        Multi-line string chart.
    """
    rows = ascii_signal_chart(values, width, height)
    return "\n".join(rows)


def format_ap_row(
    ssid: str,
    bssid: str,
    rssi: float,
    channel: int = 0,
    quality: float = 0.0,
    max_ssid: int = 20,
    max_bar: int = 15,
) -> str:
    """Format a single AP row for display.

    Args:
        ssid: Network name.
        bssid: MAC address.
        rssi: Signal strength.
        channel: WiFi channel.
        quality: Signal quality percentage.
        max_ssid: Maximum SSID display width.
        max_bar: Maximum bar width.

    Returns:
        Formatted string.
    """
    ssid_display = ssid[:max_ssid].ljust(max_ssid)
    bar = rssi_bar(rssi, max_bar)
    level = rssi_to_level(rssi)
    ch = f"{channel:>3}" if channel else "  -"
    return f" {ssid_display} {bssid:>17} {bar} {rssi:>5.0f} {ch} {level:>9}"


# ---------------------------------------------------------------------------
# Fallback Dashboard (non-curses)
# ---------------------------------------------------------------------------

class FallbackDashboard:
    """Simple terminal dashboard for systems without curses support.

    Uses ANSI escape codes and standard output to display a
    continuously updating dashboard view.
    """

    def __init__(
        self,
        refresh_rate: float = 0.5,
        history_length: int = 60,
    ) -> None:
        """Initialize the fallback dashboard.

        Args:
            refresh_rate: Refresh interval in seconds.
            history_length: Number of historical readings to display.
        """
        self.refresh_rate = refresh_rate
        self.history_length = history_length
        self._running = False
        self._current_view = 0
        self._view_names = ["Signal", "APs", "Events", "Fingerprint"]

        # Data storage
        self._rssi_history: Dict[str, Deque[float]] = {}
        self._ap_list: List[Dict[str, Any]] = []
        self._event_log: Deque[str] = deque(maxlen=50)
        self._status_text = "Ready"
        self._scan_count = 0
        self._session_start = datetime.now()

    def update_data(
        self,
        scan_result: Any = None,
        analysis_results: Optional[List[Any]] = None,
        events: Optional[List[Any]] = None,
    ) -> None:
        """Update dashboard data from scan and analysis results.

        Args:
            scan_result: ScanResult object or dict.
            analysis_results: List of AnalysisResult objects or dicts.
            events: List of triggered events.
        """
        self._scan_count += 1

        if scan_result:
            if hasattr(scan_result, "to_dict"):
                data = scan_result.to_dict()
            elif isinstance(scan_result, dict):
                data = scan_result
            else:
                data = {}

            self._ap_list = data.get("aps", [])
            for ap in self._ap_list:
                bssid = ap.get("bssid", "")
                rssi = safe_float(ap.get("rssi", 0))
                if bssid:
                    if bssid not in self._rssi_history:
                        self._rssi_history[bssid] = deque(
                            maxlen=self.history_length
                        )
                    self._rssi_history[bssid].append(rssi)

        if events:
            for event in events:
                if hasattr(event, "to_dict"):
                    edata = event.to_dict()
                elif isinstance(event, dict):
                    edata = event
                else:
                    continue
                rule_name = edata.get("rule_name", "unknown")
                ts = edata.get("timestamp", "")[:19]
                self._event_log.append(f"[{ts}] {rule_name}")

    def render(self) -> str:
        """Render the current dashboard view as a string.

        Returns:
            Multi-line string representation of the dashboard.
        """
        lines: List[str] = []
        w = 80  # Assume 80 columns

        # Header
        elapsed = (datetime.now() - self._session_start).total_seconds()
        lines.append(ANSI.BOLD + "=" * w + ANSI.RESET)
        title = "WiFiSense-CLI Dashboard"
        view_name = self._view_names[self._current_view]
        header = (
            f"  {title}  |  "
            f"Scans: {self._scan_count}  |  "
            f"APs: {len(self._ap_list)}  |  "
            f"Elapsed: {elapsed:.0f}s  |  "
            f"View: {view_name}  "
            f"[1-4:Switch  Q:Quit]"
        )
        lines.append(ANSI.BOLD + header + ANSI.RESET)
        lines.append(ANSI.BOLD + "=" * w + ANSI.RESET)

        if self._current_view == 0:
            lines.extend(self._render_signal_view())
        elif self._current_view == 1:
            lines.extend(self._render_ap_view())
        elif self._current_view == 2:
            lines.extend(self._render_event_view())
        elif self._current_view == 3:
            lines.extend(self._render_fingerprint_view())

        return "\n".join(lines)

    def _render_signal_view(self) -> List[str]:
        """Render the signal strength chart view."""
        lines: List[str] = []
        lines.append("")
        lines.append(ANSI.BOLD + "  Signal Strength History" + ANSI.RESET)
        lines.append("")

        if not self._rssi_history:
            lines.append("  No data yet. Waiting for scans...")
            return lines

        # Show chart for the first (strongest) AP
        for bssid, history in list(self._rssi_history.items())[:3]:
            values = list(history)
            ssid = "?"
            for ap in self._ap_list:
                if ap.get("bssid") == bssid:
                    ssid = ap.get("ssid", "?")[:20]
                    break

            lines.append(
                f"  {ANSI.CYAN}{ssid}{ANSI.RESET} ({bssid})"
            )
            chart = ascii_signal_chart(values, width=65, height=6)
            for row in chart:
                lines.append(f"  {row}")
            lines.append("")

        return lines

    def _render_ap_view(self) -> List[str]:
        """Render the AP list view."""
        lines: List[str] = []
        lines.append("")
        lines.append(ANSI.BOLD + "  Access Points" + ANSI.RESET)
        lines.append("")

        if not self._ap_list:
            lines.append("  No APs detected.")
            return lines

        # Sort by RSSI
        sorted_aps = sorted(
            self._ap_list, key=lambda a: safe_float(a.get("rssi", 0)), reverse=True
        )

        # Header
        hdr = (
            f"  {'SSID':<20} {'BSSID':>17} "
            f"{'Signal':<16} {'RSSI':>5} {'Ch':>4} {'Level':>9}"
        )
        lines.append(ANSI.BOLD + hdr + ANSI.RESET)
        lines.append("  " + "-" * 76)

        for ap in sorted_aps:
            line = format_ap_row(
                ssid=ap.get("ssid", ""),
                bssid=ap.get("bssid", ""),
                rssi=safe_float(ap.get("rssi", 0)),
                channel=safe_int(ap.get("channel", 0)),
                quality=safe_float(ap.get("quality", 0)),
            )
            lines.append(line)

        return lines

    def _render_event_view(self) -> List[str]:
        """Render the event log view."""
        lines: List[str] = []
        lines.append("")
        lines.append(ANSI.BOLD + "  Event Log" + ANSI.RESET)
        lines.append("")

        if not self._event_log:
            lines.append("  No events recorded.")
            return lines

        for entry in self._event_log:
            lines.append(f"  {entry}")

        return lines

    def _render_fingerprint_view(self) -> List[str]:
        """Render the fingerprint comparison view."""
        lines: List[str] = []
        lines.append("")
        lines.append(ANSI.BOLD + "  Environment Fingerprint" + ANSI.RESET)
        lines.append("")

        if not self._rssi_history:
            lines.append("  No data yet.")
            return lines

        lines.append("  Current RSSI Vector:")
        lines.append("  " + "-" * 50)

        for bssid, history in self._rssi_history.items():
            ssid = "?"
            for ap in self._ap_list:
                if ap.get("bssid") == bssid:
                    ssid = ap.get("ssid", "?")[:20]
                    break
            rssi = history[-1] if history else 0
            lines.append(
                f"  {ssid:<20} {bssid:>17}  RSSI: {rssi:>5.0f} dBm"
            )

        return lines

    def start(self) -> None:
        """Start the fallback dashboard (non-interactive)."""
        self._running = True
        log_info("Fallback dashboard started (no curses support)")

    def stop(self) -> None:
        """Stop the dashboard."""
        self._running = False

    def handle_key(self, key: str) -> None:
        """Handle a keyboard input.

        Args:
            key: The key character pressed.
        """
        if key == "1":
            self._current_view = 0
        elif key == "2":
            self._current_view = 1
        elif key == "3":
            self._current_view = 2
        elif key == "4":
            self._current_view = 3
        elif key.lower() == "q":
            self._running = False


# ---------------------------------------------------------------------------
# Curses Dashboard (Unix-like systems)
# ---------------------------------------------------------------------------

if _CURSES_AVAILABLE:
    import curses
    import curses.ascii

    class CursesDashboard:
        """Full-featured TUI dashboard using the curses library.

        Provides real-time signal visualization, AP listing, event log,
        and fingerprint comparison panels. Supports keyboard navigation.

        Attributes:
            refresh_rate: Screen refresh interval in seconds.
            history_length: Number of historical readings to retain.
        """

        # Color pair indices
        COLOR_HEADER = 1
        COLOR_GOOD = 2
        COLOR_WARN = 3
        COLOR_BAD = 4
        COLOR_HIGHLIGHT = 5
        COLOR_DIM = 6
        COLOR_EVENT = 7

        def __init__(
            self,
            refresh_rate: float = 0.5,
            history_length: int = 60,
        ) -> None:
            """Initialize the curses dashboard.

            Args:
                refresh_rate: Refresh interval in seconds.
                history_length: Number of historical readings.
            """
            self.refresh_rate = refresh_rate
            self.history_length = history_length
            self._running = False
            self._current_view = 0
            self._view_names = ["Signal", "AP List", "Events", "Fingerprint"]

            # Data storage
            self._rssi_history: Dict[str, Deque[float]] = {}
            self._ap_list: List[Dict[str, Any]] = []
            self._event_log: Deque[str] = deque(maxlen=100)
            self._status_text = "Ready"
            self._scan_count = 0
            self._session_start = datetime.now()
            self._scroll_offset = 0

            # Curses state
            self._stdscr: Any = None

        def _init_colors(self) -> None:
            """Initialize curses color pairs."""
            if not curses.has_colors():
                return
            curses.start_color()
            curses.use_default_colors()

            curses.init_pair(
                self.COLOR_HEADER, curses.COLOR_CYAN, curses.COLOR_BLACK
            )
            curses.init_pair(
                self.COLOR_GOOD, curses.COLOR_GREEN, curses.COLOR_BLACK
            )
            curses.init_pair(
                self.COLOR_WARN, curses.COLOR_YELLOW, curses.COLOR_BLACK
            )
            curses.init_pair(
                self.COLOR_BAD, curses.COLOR_RED, curses.COLOR_BLACK
            )
            curses.init_pair(
                self.COLOR_HIGHLIGHT, curses.COLOR_WHITE, curses.COLOR_BLUE
            )
            curses.init_pair(
                self.COLOR_DIM, curses.COLOR_GRAY, curses.COLOR_BLACK
            )
            curses.init_pair(
                self.COLOR_EVENT, curses.COLOR_MAGENTA, curses.COLOR_BLACK
            )

        def _rssi_color_pair(self, rssi: float) -> int:
            """Get the curses color pair for an RSSI value.

            Args:
                rssi: RSSI value in dBm.

            Returns:
                Curses color pair index.
            """
            if rssi >= -50:
                return self.COLOR_GOOD
            elif rssi >= -65:
                return self.COLOR_WARN
            else:
                return self.COLOR_BAD

        def update_data(
            self,
            scan_result: Any = None,
            analysis_results: Optional[List[Any]] = None,
            events: Optional[List[Any]] = None,
        ) -> None:
            """Update dashboard data from scan and analysis results.

            Args:
                scan_result: ScanResult object or dict.
                analysis_results: List of AnalysisResult objects or dicts.
                events: List of triggered events.
            """
            self._scan_count += 1

            if scan_result:
                if hasattr(scan_result, "to_dict"):
                    data = scan_result.to_dict()
                elif isinstance(scan_result, dict):
                    data = scan_result
                else:
                    data = {}

                self._ap_list = data.get("aps", [])
                for ap in self._ap_list:
                    bssid = ap.get("bssid", "")
                    rssi = safe_float(ap.get("rssi", 0))
                    if bssid:
                        if bssid not in self._rssi_history:
                            self._rssi_history[bssid] = deque(
                                maxlen=self.history_length
                            )
                        self._rssi_history[bssid].append(rssi)

            if events:
                for event in events:
                    if hasattr(event, "to_dict"):
                        edata = event.to_dict()
                    elif isinstance(event, dict):
                        edata = event
                    else:
                        continue
                    rule_name = edata.get("rule_name", "unknown")
                    ts = edata.get("timestamp", "")[:19]
                    self._event_log.append(f"[{ts}] {rule_name}")

        def _draw_header(self) -> None:
            """Draw the dashboard header bar."""
            if not self._stdscr:
                return
            h, w = self._stdscr.getmaxyx()
            elapsed = (datetime.now() - self._session_start).total_seconds()

            try:
                self._stdscr.attron(curses.color_pair(self.COLOR_HEADER))
                self._stdscr.attron(curses.A_BOLD)
                title = (
                    f" WiFiSense-CLI Dashboard "
                    f"| Scans: {self._scan_count} "
                    f"| APs: {len(self._ap_list)} "
                    f"| {elapsed:.0f}s "
                    f"| View: {self._view_names[self._current_view]} "
                    f"[1-4] [Q]uit "
                )
                title = title.ljust(w)
                self._stdscr.addstr(0, 0, title[:w])
                self._stdscr.attroff(curses.A_BOLD)
                self._stdscr.attroff(curses.color_pair(self.COLOR_HEADER))
            except curses.error:
                pass

        def _draw_signal_view(self) -> None:
            """Draw the signal strength chart view."""
            if not self._stdscr:
                return
            h, w = self._stdscr.getmaxyx()

            try:
                self._stdscr.addstr(2, 2, "Signal Strength History", curses.A_BOLD)
            except curses.error:
                pass

            if not self._rssi_history:
                try:
                    self._stdscr.addstr(4, 2, "No data yet. Waiting for scans...")
                except curses.error:
                    pass
                return

            y_offset = 4
            chart_height = min(8, (h - y_offset - 4) // max(len(self._rssi_history), 1))
            chart_height = max(3, chart_height)
            chart_width = min(w - 12, 65)

            for idx, (bssid, history) in enumerate(
                list(self._rssi_history.items())[:3]
            ):
                if y_offset + chart_height + 2 >= h:
                    break

                values = list(history)
                ssid = "?"
                for ap in self._ap_list:
                    if ap.get("bssid") == bssid:
                        ssid = ap.get("ssid", "?")[:20]
                        break

                try:
                    self._stdscr.addstr(
                        y_offset, 2, f"{ssid} ({bssid})",
                        curses.color_pair(self.COLOR_HEADER),
                    )
                except curses.error:
                    pass

                chart_rows = ascii_signal_chart(
                    values, width=chart_width, height=chart_height
                )
                for row_idx, row in enumerate(chart_rows):
                    if y_offset + 1 + row_idx >= h:
                        break
                    try:
                        self._stdscr.addstr(
                            y_offset + 1 + row_idx, 2, row[:w - 4]
                        )
                    except curses.error:
                        pass

                y_offset += chart_height + 3

        def _draw_ap_view(self) -> None:
            """Draw the AP list view."""
            if not self._stdscr:
                return
            h, w = self._stdscr.getmaxyx()

            try:
                self._stdscr.addstr(2, 2, "Access Points", curses.A_BOLD)
            except curses.error:
                pass

            if not self._ap_list:
                try:
                    self._stdscr.addstr(4, 2, "No APs detected.")
                except curses.error:
                    pass
                return

            sorted_aps = sorted(
                self._ap_list,
                key=lambda a: safe_float(a.get("rssi", 0)),
                reverse=True,
            )

            # Header
            try:
                hdr = f"  {'SSID':<20} {'BSSID':>17} {'RSSI':>6} {'Ch':>4} {'Quality':>8}"
                self._stdscr.addstr(4, 2, hdr, curses.A_BOLD)
                self._stdscr.addstr(5, 2, "-" * min(w - 4, 60))
            except curses.error:
                pass

            y = 6
            for i, ap in enumerate(sorted_aps):
                if y >= h - 2:
                    break
                ssid = ap.get("ssid", "")[:20]
                bssid = ap.get("bssid", "")
                rssi = safe_float(ap.get("rssi", 0))
                channel = safe_int(ap.get("channel", 0))
                quality = rssi_to_quality(rssi)

                color = self._rssi_color_pair(rssi)
                line = f"  {ssid:<20} {bssid:>17} {rssi:>5.0f} {channel:>4} {quality:>7.1f}%"

                try:
                    self._stdscr.addstr(y, 2, line, curses.color_pair(color))
                except curses.error:
                    pass
                y += 1

        def _draw_event_view(self) -> None:
            """Draw the event log view."""
            if not self._stdscr:
                return
            h, w = self._stdscr.getmaxyx()

            try:
                self._stdscr.addstr(2, 2, "Event Log", curses.A_BOLD)
            except curses.error:
                pass

            if not self._event_log:
                try:
                    self._stdscr.addstr(4, 2, "No events recorded.")
                except curses.error:
                    pass
                return

            y = 4
            events_list = list(self._event_log)
            start = max(0, len(events_list) - (h - y - 2))

            for entry in events_list[start:]:
                if y >= h - 2:
                    break
                try:
                    self._stdscr.addstr(
                        y, 2, entry[:w - 4],
                        curses.color_pair(self.COLOR_EVENT),
                    )
                except curses.error:
                    pass
                y += 1

        def _draw_fingerprint_view(self) -> None:
            """Draw the fingerprint comparison view."""
            if not self._stdscr:
                return
            h, w = self._stdscr.getmaxyx()

            try:
                self._stdscr.addstr(2, 2, "Environment Fingerprint", curses.A_BOLD)
            except curses.error:
                pass

            if not self._rssi_history:
                try:
                    self._stdscr.addstr(4, 2, "No data yet.")
                except curses.error:
                    pass
                return

            try:
                self._stdscr.addstr(4, 2, "Current RSSI Vector:")
                self._stdscr.addstr(5, 2, "-" * min(w - 4, 50))
            except curses.error:
                pass

            y = 6
            for bssid, history in self._rssi_history.items():
                if y >= h - 2:
                    break
                ssid = "?"
                for ap in self._ap_list:
                    if ap.get("bssid") == bssid:
                        ssid = ap.get("ssid", "?")[:20]
                        break
                rssi = history[-1] if history else 0
                line = f"  {ssid:<20} {bssid:>17}  RSSI: {rssi:>5.0f} dBm"

                color = self._rssi_color_pair(rssi)
                try:
                    self._stdscr.addstr(y, 2, line, curses.color_pair(color))
                except curses.error:
                    pass
                y += 1

        def _draw_status_bar(self) -> None:
            """Draw the bottom status bar."""
            if not self._stdscr:
                return
            h, w = self._stdscr.getmaxyx()
            try:
                status = self._status_text.ljust(w - 1)
                self._stdscr.addstr(
                    h - 1, 0, status,
                    curses.color_pair(self.COLOR_DIM),
                )
            except curses.error:
                pass

        def _draw(self) -> None:
            """Redraw the entire dashboard."""
            if not self._stdscr:
                return
            self._stdscr.clear()
            self._draw_header()

            if self._current_view == 0:
                self._draw_signal_view()
            elif self._current_view == 1:
                self._draw_ap_view()
            elif self._current_view == 2:
                self._draw_event_view()
            elif self._current_view == 3:
                self._draw_fingerprint_view()

            self._draw_status_bar()
            self._stdscr.refresh()

        def start(self) -> None:
            """Start the curses dashboard main loop."""
            self._running = True

            def _wrapper(stdscr: Any) -> None:
                """Curses wrapper function."""
                self._stdscr = stdscr
                stdscr.nodelay(True)
                stdscr.timeout(int(self.refresh_rate * 1000))
                self._init_colors()

                while self._running:
                    self._draw()

                    # Handle input
                    try:
                        key = stdscr.getch()
                        if key == ord("1"):
                            self._current_view = 0
                        elif key == ord("2"):
                            self._current_view = 1
                        elif key == ord("3"):
                            self._current_view = 2
                        elif key == ord("4"):
                            self._current_view = 3
                        elif key in (ord("q"), ord("Q"), 27):  # Q or ESC
                            self._running = False
                    except curses.error:
                        pass

            try:
                curses.wrapper(_wrapper)
            except Exception as e:
                print(f"Dashboard error: {e}", file=sys.stderr)

        def stop(self) -> None:
            """Stop the dashboard."""
            self._running = False

        def handle_key(self, key: str) -> None:
            """Handle a keyboard input (for external control).

            Args:
                key: The key character pressed.
            """
            if key == "1":
                self._current_view = 0
            elif key == "2":
                self._current_view = 1
            elif key == "3":
                self._current_view = 2
            elif key == "4":
                self._current_view = 3
            elif key.lower() == "q":
                self._running = False


# ---------------------------------------------------------------------------
# Dashboard Factory
# ---------------------------------------------------------------------------

def create_dashboard(
    refresh_rate: float = 0.5,
    history_length: int = 60,
) -> Any:
    """Create the appropriate dashboard for the current platform.

    Returns a CursesDashboard on Unix-like systems with curses support,
    or a FallbackDashboard on Windows or systems without curses.

    Args:
        refresh_rate: Refresh interval in seconds.
        history_length: Number of historical readings.

    Returns:
        Either a CursesDashboard or FallbackDashboard instance.
    """
    if _CURSES_AVAILABLE:
        return CursesDashboard(
            refresh_rate=refresh_rate,
            history_length=history_length,
        )
    else:
        return FallbackDashboard(
            refresh_rate=refresh_rate,
            history_length=history_length,
        )
