"""
WiFiSense-CLI Command Line Interface

Provides the main CLI entry point with subcommand architecture:
scan, monitor, analyze, events, config, dashboard. Uses argparse
for command parsing with colored output and table formatting.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config_manager import ConfigManager, create_default_config
from .data_manager import DataManager
from .event_engine import EventEngine
from .signal_analyzer import SignalAnalyzer
from .tui_dashboard import create_dashboard, FallbackDashboard
from .wifi_scanner import WiFiScanner
from .utils import (
    ANSI,
    colorize,
    format_table,
    get_platform,
    log_error,
    log_info,
    log_warning,
    rssi_bar,
    rssi_color,
    rssi_to_level,
    rssi_to_quality,
    safe_float,
    safe_int,
    style,
    timestamp,
)


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

VERSION = "0.1.0"
BANNER = f"""
{ANSI.CYAN}{ANSI.BOLD}WiFiSense-CLI{ANSI.RESET} {ANSI.DIM}v{VERSION}{ANSI.RESET}
{ANSI.DIM}Lightweight Terminal WiFi Signal Intelligence & IoT Event Engine{ANSI.RESET}
"""


# ---------------------------------------------------------------------------
# CLI Application
# ---------------------------------------------------------------------------

class WiFiSenseCLI:
    """Main CLI application class.

    Parses commands, initializes components, and routes execution
    to the appropriate handler.

    Attributes:
        config: Configuration manager instance.
        args: Parsed command-line arguments.
    """

    def __init__(self) -> None:
        """Initialize the CLI application."""
        self.config = ConfigManager()
        self.args: Optional[argparse.Namespace] = None

    def run(self, argv: Optional[List[str]] = None) -> int:
        """Run the CLI application.

        Args:
            argv: Command-line arguments. If None, uses sys.argv[1:].

        Returns:
            Exit code (0 for success, non-zero for errors).
        """
        parser = self._build_parser()
        self.args = parser.parse_args(argv)

        # Handle --version
        if self.args.version:
            print(f"WiFiSense-CLI v{VERSION}")
            return 0

        # Handle --config-dir
        if hasattr(self.args, "config_dir") and self.args.config_dir:
            self.config = ConfigManager(config_dir=self.args.config_dir)

        # Route to subcommand handler
        if not hasattr(self.args, "command") or not self.args.command:
            parser.print_help()
            return 0

        handler_map = {
            "scan": self._cmd_scan,
            "monitor": self._cmd_monitor,
            "analyze": self._cmd_analyze,
            "events": self._cmd_events,
            "config": self._cmd_config,
            "dashboard": self._cmd_dashboard,
        }

        handler = handler_map.get(self.args.command)
        if handler:
            try:
                return handler()
            except KeyboardInterrupt:
                print("\nInterrupted.")
                return 130
            except Exception as e:
                log_error(f"Error: {e}")
                return 1
        else:
            parser.print_help()
            return 1

    def _build_parser(self) -> argparse.ArgumentParser:
        """Build the argument parser with all subcommands.

        Returns:
            Configured ArgumentParser instance.
        """
        parser = argparse.ArgumentParser(
            prog="wifisense",
            description="WiFiSense-CLI - Lightweight Terminal WiFi Signal Intelligence & IoT Event Engine",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  wifisense scan                    Single scan, list all visible APs
  wifisense scan -i wlan0           Scan on specific interface
  wifisense monitor                 Start continuous monitoring
  wifisense monitor -d              Monitor with data recording
  wifisense analyze -s session_id   Analyze a recorded session
  wifisense events list             List all event rules
  wifisense events add -f rules.json Add rules from file
  wifisense config show             Show current configuration
  wifisense config set scanner.poll_interval 2.0
  wifisense dashboard               Launch TUI dashboard
""",
        )

        # Global options
        parser.add_argument(
            "--version", "-V",
            action="store_true",
            help="Show version and exit",
        )
        parser.add_argument(
            "--config-dir", "-C",
            type=str, default=None,
            help="Configuration directory path",
        )
        parser.add_argument(
            "--no-color",
            action="store_true",
            help="Disable colored output",
        )

        # Subcommands
        subparsers = parser.add_subparsers(
            dest="command",
            title="Commands",
            metavar="COMMAND",
        )

        # --- scan ---
        scan_parser = subparsers.add_parser(
            "scan",
            help="Perform a single WiFi scan",
            description="Scan for visible WiFi access points and display their signal information.",
        )
        scan_parser.add_argument(
            "-i", "--interface",
            type=str, default=None,
            help="WiFi interface to use (default: auto-detect)",
        )
        scan_parser.add_argument(
            "-j", "--json",
            action="store_true",
            help="Output in JSON format",
        )
        scan_parser.add_argument(
            "-a", "--all",
            action="store_true",
            help="Show all details including hidden SSIDs",
        )
        scan_parser.add_argument(
            "-s", "--sort",
            type=str, choices=["rssi", "ssid", "channel", "quality"],
            default="rssi",
            help="Sort APs by field (default: rssi)",
        )

        # --- monitor ---
        monitor_parser = subparsers.add_parser(
            "monitor",
            help="Start continuous WiFi monitoring",
            description="Continuously monitor WiFi signals and optionally record data.",
        )
        monitor_parser.add_argument(
            "-i", "--interface",
            type=str, default=None,
            help="WiFi interface to use",
        )
        monitor_parser.add_argument(
            "-p", "--poll-interval",
            type=float, default=None,
            help="Scan interval in seconds (default: from config)",
        )
        monitor_parser.add_argument(
            "-d", "--record",
            action="store_true",
            help="Record scan data to session",
        )
        monitor_parser.add_argument(
            "-n", "--session-name",
            type=str, default="",
            help="Name for the recording session",
        )
        monitor_parser.add_argument(
            "-e", "--events",
            action="store_true",
            help="Enable event engine during monitoring",
        )
        monitor_parser.add_argument(
            "--no-analysis",
            action="store_true",
            help="Disable signal analysis",
        )

        # --- analyze ---
        analyze_parser = subparsers.add_parser(
            "analyze",
            help="Analyze recorded WiFi data",
            description="Analyze historical scan data from a recorded session.",
        )
        analyze_parser.add_argument(
            "-s", "--session",
            type=str, default=None,
            help="Session ID to analyze",
        )
        analyze_parser.add_argument(
            "-l", "--latest",
            action="store_true",
            help="Analyze the latest session",
        )
        analyze_parser.add_argument(
            "--stats",
            action="store_true",
            help="Show statistics summary",
        )
        analyze_parser.add_argument(
            "--export",
            type=str, default=None,
            help="Export data to CSV file",
        )
        analyze_parser.add_argument(
            "--data-type",
            type=str, choices=["scans", "analysis", "events"],
            default="scans",
            help="Type of data to export",
        )

        # --- events ---
        events_parser = subparsers.add_parser(
            "events",
            help="Manage event rules",
            description="List, add, remove, or test event rules.",
        )
        events_sub = events_parser.add_subparsers(
            dest="events_command",
            title="Event subcommands",
            metavar="SUBCOMMAND",
        )

        # events list
        events_list = events_sub.add_parser("list", help="List all event rules")
        events_list.add_argument(
            "-j", "--json",
            action="store_true",
            help="Output in JSON format",
        )

        # events add
        events_add = events_sub.add_parser("add", help="Add event rules from file")
        events_add.add_argument(
            "-f", "--file",
            type=str, required=True,
            help="JSON rules file to load",
        )

        # events remove
        events_remove = events_sub.add_parser("remove", help="Remove an event rule")
        events_remove.add_argument(
            "-n", "--name",
            type=str, required=True,
            help="Name of the rule to remove",
        )

        # events enable/disable
        events_enable = events_sub.add_parser("enable", help="Enable an event rule")
        events_enable.add_argument("-n", "--name", type=str, required=True)

        events_disable = events_sub.add_parser("disable", help="Disable an event rule")
        events_disable.add_argument("-n", "--name", type=str, required=True)

        # events test
        events_test = events_sub.add_parser("test", help="Test rules with current scan data")

        # events log
        events_log = events_sub.add_parser("log", help="Show event trigger log")
        events_log.add_argument(
            "-l", "--limit",
            type=int, default=20,
            help="Number of entries to show",
        )

        # events save
        events_save = events_sub.add_parser("save", help="Save current rules to file")
        events_save.add_argument(
            "-f", "--file",
            type=str, default=None,
            help="Output file path",
        )

        # --- config ---
        config_parser = subparsers.add_parser(
            "config",
            help="Manage configuration",
            description="View and modify WiFiSense configuration.",
        )
        config_sub = config_parser.add_subparsers(
            dest="config_command",
            title="Config subcommands",
            metavar="SUBCOMMAND",
        )

        # config show
        config_show = config_sub.add_parser("show", help="Show current configuration")
        config_show.add_argument(
            "-s", "--section",
            type=str, default=None,
            help="Show a specific section",
        )
        config_show.add_argument(
            "-j", "--json",
            action="store_true",
            help="Output in JSON format",
        )

        # config set
        config_set = config_sub.add_parser("set", help="Set a configuration value")
        config_set.add_argument(
            "key",
            type=str,
            help="Configuration key (e.g., scanner.poll_interval)",
        )
        config_set.add_argument(
            "value",
            type=str,
            help="Configuration value",
        )

        # config reset
        config_reset = config_sub.add_parser("reset", help="Reset configuration to defaults")
        config_reset.add_argument(
            "--confirm",
            action="store_true",
            help="Skip confirmation prompt",
        )

        # config validate
        config_validate = config_sub.add_parser("validate", help="Validate configuration")

        # config init
        config_init = config_sub.add_parser("init", help="Create default config file")
        config_init.add_argument(
            "-p", "--path",
            type=str, default=None,
            help="Path for the new config file",
        )

        # --- dashboard ---
        dashboard_parser = subparsers.add_parser(
            "dashboard",
            help="Launch TUI dashboard",
            description="Launch the interactive terminal UI dashboard for real-time monitoring.",
        )
        dashboard_parser.add_argument(
            "-i", "--interface",
            type=str, default=None,
            help="WiFi interface to use",
        )
        dashboard_parser.add_argument(
            "-r", "--refresh",
            type=float, default=None,
            help="Refresh rate in seconds",
        )

        return parser

    # ------------------------------------------------------------------
    # Command: scan
    # ------------------------------------------------------------------

    def _cmd_scan(self) -> int:
        """Execute the scan command.

        Returns:
            Exit code.
        """
        interface = self.args.interface or self.config.get("scanner.interface", "auto")
        scanner = WiFiScanner(
            interface=interface,
            scan_timeout=self.config.get("scanner.scan_timeout", 10.0),
            max_retries=self.config.get("scanner.max_retries", 3),
            include_hidden=self.args.all,
        )

        result = scanner.scan()

        if not result.success:
            log_error(f"Scan failed: {result.error}")
            return 1

        if self.args.json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0

        # Display results
        print(BANNER)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"  {colorize('Scan Results', ANSI.BOLD)}  "
            f"{style(ts, ANSI.DIM)}  "
            f"Interface: {style(result.interface, ANSI.CYAN)}  "
            f"Platform: {get_platform()}"
        )
        print(f"  {len(result.aps)} APs detected in {result.scan_duration:.2f}s")
        print()

        # Sort APs
        sort_key = self.args.sort
        if sort_key == "rssi":
            result.aps.sort(key=lambda a: a.rssi, reverse=True)
        elif sort_key == "ssid":
            result.aps.sort(key=lambda a: a.ssid.lower())
        elif sort_key == "channel":
            result.aps.sort(key=lambda a: a.channel)
        elif sort_key == "quality":
            result.aps.sort(key=lambda a: a.quality, reverse=True)

        # Build table
        headers = ["SSID", "BSSID", "RSSI", "Quality", "Ch", "Band", "Security"]
        rows: List[List[Any]] = []
        for ap in result.aps:
            ssid = ap.ssid if ap.ssid else colorize("(hidden)", ANSI.DIM)
            rows.append([
                ssid,
                ap.bssid,
                f"{ap.rssi:.0f} dBm",
                f"{ap.quality:.0f}%",
                ap.channel if ap.channel else "-",
                ap.band,
                ap.security if ap.security else "-",
            ])

        table = format_table(headers, rows)
        print(table)
        return 0

    # ------------------------------------------------------------------
    # Command: monitor
    # ------------------------------------------------------------------

    def _cmd_monitor(self) -> int:
        """Execute the monitor command.

        Returns:
            Exit code.
        """
        interface = self.args.interface or self.config.get("scanner.interface", "auto")
        poll_interval = self.args.poll_interval or self.config.get("scanner.poll_interval", 1.0)

        scanner = WiFiScanner(
            interface=interface,
            poll_interval=poll_interval,
            scan_timeout=self.config.get("scanner.scan_timeout", 10.0),
            max_retries=self.config.get("scanner.max_retries", 3),
        )

        analyzer = SignalAnalyzer(
            ma_window=self.config.get("analyzer.moving_average_window", 5),
            ewma_alpha=self.config.get("analyzer.ewma_alpha", 0.3),
            z_score_threshold=self.config.get("analyzer.z_score_threshold", 2.0),
            iqr_factor=self.config.get("analyzer.iqr_factor", 1.5),
            trend_window=self.config.get("analyzer.trend_window", 10),
        )

        event_engine = None
        if self.args.events:
            event_engine = EventEngine(
                rules_file=self.config.get("events.rules_file", "rules.json"),
                max_events_per_minute=self.config.get("events.max_events_per_minute", 10),
            )

        data_manager = None
        session = None
        if self.args.record:
            data_manager = DataManager(
                storage_dir=self.config.get("data.storage_dir", "data"),
            )
            session = data_manager.start_session(
                name=self.args.session_name,
                interface=interface,
                platform=get_platform(),
            )

        print(BANNER)
        print(
            f"  {colorize('Monitoring Mode', ANSI.BOLD)}  "
            f"Interface: {style(interface, ANSI.CYAN)}  "
            f"Interval: {poll_interval}s  "
            f"Recording: {'Yes' if self.args.record else 'No'}  "
            f"Events: {'Yes' if self.args.events else 'No'}"
        )
        print(f"  Press Ctrl+C to stop")
        print()

        scan_count = 0

        def monitor_callback(scan_result: Any) -> None:
            """Callback for each scan result during monitoring."""
            nonlocal scan_count
            scan_count += 1

            if not scan_result.success:
                log_error(f"Scan failed: {scan_result.error}")
                return

            # Record data
            if data_manager and session:
                data_manager.record_scan(scan_result.to_dict())

            # Analyze
            if not self.args.no_analysis:
                analysis_results = analyzer.process_scan(scan_result.to_dict())

                # Record analysis
                if data_manager and session:
                    for ar in analysis_results:
                        data_manager.record_analysis(ar.to_dict())

                # Check events
                if event_engine:
                    events = event_engine.evaluate(analysis_results)
                    if events:
                        for evt in events:
                            if data_manager and session:
                                data_manager.record_event(evt.to_dict())

            # Display summary
            self._print_monitor_summary(scan_result, scan_count)

        try:
            scanner.start_monitoring(callback=monitor_callback)
        except KeyboardInterrupt:
            pass
        finally:
            if data_manager and session:
                data_manager.stop_session()
            print(f"\n  Monitoring stopped. Total scans: {scan_count}")

        return 0

    def _print_monitor_summary(self, scan_result: Any, count: int) -> None:
        """Print a one-line summary for each monitoring cycle.

        Args:
            scan_result: The scan result.
            count: Cumulative scan count.
        """
        ts = datetime.now().strftime("%H:%M:%S")
        ap_count = len(scan_result.aps)

        if scan_result.aps:
            best = max(scan_result.aps, key=lambda a: a.rssi)
            avg_rssi = sum(ap.rssi for ap in scan_result.aps) / ap_count
            line = (
                f"  [{ts}] #{count:>4}  "
                f"APs: {ap_count:>2}  "
                f"Best: {best.ssid[:15]:<15} "
                f"{best.rssi:>5.0f} dBm  "
                f"Avg: {avg_rssi:>5.1f} dBm"
            )
        else:
            line = f"  [{ts}] #{count:>4}  APs: 0  No signals detected"

        print(f"\r{line.ljust(80)}", end="", flush=True)

    # ------------------------------------------------------------------
    # Command: analyze
    # ------------------------------------------------------------------

    def _cmd_analyze(self) -> int:
        """Execute the analyze command.

        Returns:
            Exit code.
        """
        data_manager = DataManager(
            storage_dir=self.config.get("data.storage_dir", "data"),
        )

        # Determine session
        session_id = self.args.session
        if self.args.latest or not session_id:
            sessions = data_manager.list_sessions()
            if not sessions:
                log_error("No sessions found. Run 'wifisense monitor -d' first.")
                return 1
            session_id = sessions[0].id

        session = data_manager.get_session(session_id)
        if not session:
            log_error(f"Session not found: {session_id}")
            return 1

        # Statistics
        if self.args.stats:
            stats = data_manager.get_session_statistics(session_id)
            print(f"\n  {colorize('Session Statistics', ANSI.BOLD)}")
            print(f"  {'=' * 50}")
            print(f"  Name:       {stats.get('name', 'N/A')}")
            print(f"  ID:         {stats.get('id', 'N/A')}")
            print(f"  Start:      {stats.get('start_time', 'N/A')[:19]}")
            print(f"  End:        {stats.get('end_time', 'N/A')[:19] if stats.get('end_time') else 'Active'}")
            print(f"  Scans:      {stats.get('scan_count', 0)}")
            print(f"  Unique APs: {stats.get('unique_aps', 0)}")
            print(f"  Events:     {stats.get('total_events', 0)}")
            print()

            ap_stats = stats.get("ap_statistics", [])
            if ap_stats:
                headers = ["BSSID", "Samples", "Mean RSSI", "Min", "Max", "Range"]
                rows = [
                    [
                        s["bssid"],
                        s["count"],
                        f"{s['mean']:.1f} dBm",
                        f"{s['min']:.0f} dBm",
                        f"{s['max']:.0f} dBm",
                        f"{s['range']:.0f} dBm",
                    ]
                    for s in ap_stats
                ]
                print(format_table(headers, rows))

        # Export
        if self.args.export:
            success = data_manager.export_csv(
                session_id=session_id,
                output_path=self.args.export,
                data_type=self.args.data_type,
            )
            if success:
                log_info(f"Data exported to {self.args.export}")
            else:
                log_error("Export failed")
                return 1

        # Default: show session summary
        if not self.args.stats and not self.args.export:
            stats = data_manager.get_session_statistics(session_id)
            print(f"\n  {colorize('Session Summary', ANSI.BOLD)}")
            print(f"  {'=' * 50}")
            print(f"  Name:       {stats.get('name', 'N/A')}")
            print(f"  ID:         {stats.get('id', 'N/A')}")
            print(f"  Scans:      {stats.get('scan_count', 0)}")
            print(f"  Unique APs: {stats.get('unique_aps', 0)}")
            print(f"  Duration:   {session.duration_seconds:.0f}s")
            print(f"\n  Use --stats for detailed statistics")
            print(f"  Use --export <file> to export data to CSV")

        return 0

    # ------------------------------------------------------------------
    # Command: events
    # ------------------------------------------------------------------

    def _cmd_events(self) -> int:
        """Execute the events command.

        Returns:
            Exit code.
        """
        events_cmd = getattr(self.args, "events_command", None)

        if not events_cmd:
            log_error("Please specify an events subcommand. See 'wifisense events --help'")
            return 1

        engine = EventEngine(
            rules_file=self.config.get("events.rules_file", "rules.json"),
        )

        if events_cmd == "list":
            return self._events_list(engine)
        elif events_cmd == "add":
            return self._events_add(engine)
        elif events_cmd == "remove":
            return self._events_remove(engine)
        elif events_cmd == "enable":
            return self._events_enable(engine)
        elif events_cmd == "disable":
            return self._events_disable(engine)
        elif events_cmd == "test":
            return self._events_test(engine)
        elif events_cmd == "log":
            return self._events_log(engine)
        elif events_cmd == "save":
            return self._events_save(engine)
        else:
            log_error(f"Unknown events subcommand: {events_cmd}")
            return 1

    def _events_list(self, engine: EventEngine) -> int:
        """List all event rules."""
        if self.args.json:
            summary = engine.get_summary()
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return 0

        rules = engine.rules
        if not rules:
            print("  No event rules configured.")
            return 0

        print(f"\n  {colorize('Event Rules', ANSI.BOLD)}")
        print(f"  {'=' * 60}")

        headers = ["Name", "Enabled", "Triggers", "Conditions", "Actions"]
        rows = [
            [
                r.name,
                colorize("Yes", ANSI.GREEN) if r.enabled else colorize("No", ANSI.RED),
                str(r.trigger_count),
                str(len(r.conditions)),
                str(len(r.actions)),
            ]
            for r in rules
        ]
        print(format_table(headers, rows))
        return 0

    def _events_add(self, engine: EventEngine) -> int:
        """Add event rules from a file."""
        if engine.load_rules(self.args.file):
            log_info(f"Rules loaded from {self.args.file}")
            return 0
        return 1

    def _events_remove(self, engine: EventEngine) -> int:
        """Remove an event rule."""
        if engine.remove_rule(self.args.name):
            engine.save_rules()
            log_info(f"Rule '{self.args.name}' removed")
            return 0
        log_error(f"Rule not found: {self.args.name}")
        return 1

    def _events_enable(self, engine: EventEngine) -> int:
        """Enable an event rule."""
        if engine.enable_rule(self.args.name):
            engine.save_rules()
            log_info(f"Rule '{self.args.name}' enabled")
            return 0
        log_error(f"Rule not found: {self.args.name}")
        return 1

    def _events_disable(self, engine: EventEngine) -> int:
        """Disable an event rule."""
        if engine.disable_rule(self.args.name):
            engine.save_rules()
            log_info(f"Rule '{self.args.name}' disabled")
            return 0
        log_error(f"Rule not found: {self.args.name}")
        return 1

    def _events_test(self, engine: EventEngine) -> int:
        """Test rules with a current scan."""
        scanner = WiFiScanner(
            interface=self.config.get("scanner.interface", "auto"),
        )
        result = scanner.scan()
        if not result.success:
            log_error(f"Scan failed: {result.error}")
            return 1

        analyzer = SignalAnalyzer()
        analysis_results = analyzer.process_scan(result.to_dict())
        events = engine.evaluate(analysis_results)

        if events:
            print(f"\n  {colorize(f'{len(events)} Rule(s) Triggered', ANSI.YELLOW)}")
            for evt in events:
                print(f"  - {evt.rule_name}")
        else:
            print("\n  No rules triggered.")

        return 0

    def _events_log(self, engine: EventEngine) -> int:
        """Show event trigger log."""
        events = engine.get_event_log(limit=self.args.limit)
        if not events:
            print("  No events recorded.")
            return 0

        print(f"\n  {colorize('Event Log', ANSI.BOLD)}")
        print(f"  {'=' * 60}")

        headers = ["Timestamp", "Rule", "Success", "Actions"]
        rows = [
            [
                e.timestamp[:19],
                e.rule_name,
                colorize("Yes", ANSI.GREEN) if e.success else colorize("No", ANSI.RED),
                ", ".join(e.actions_executed),
            ]
            for e in events
        ]
        print(format_table(headers, rows))
        return 0

    def _events_save(self, engine: EventEngine) -> int:
        """Save current rules to a file."""
        path = self.args.file or self.config.get("events.rules_file", "rules.json")
        if engine.save_rules(path):
            log_info(f"Rules saved to {path}")
            return 0
        return 1

    # ------------------------------------------------------------------
    # Command: config
    # ------------------------------------------------------------------

    def _cmd_config(self) -> int:
        """Execute the config command.

        Returns:
            Exit code.
        """
        config_cmd = getattr(self.args, "config_command", None)

        if not config_cmd:
            log_error("Please specify a config subcommand. See 'wifisense config --help'")
            return 1

        if config_cmd == "show":
            return self._config_show()
        elif config_cmd == "set":
            return self._config_set()
        elif config_cmd == "reset":
            return self._config_reset()
        elif config_cmd == "validate":
            return self._config_validate()
        elif config_cmd == "init":
            return self._config_init()
        else:
            log_error(f"Unknown config subcommand: {config_cmd}")
            return 1

    def _config_show(self) -> int:
        """Show current configuration."""
        if self.args.json:
            print(json.dumps(self.config.to_dict(), indent=2, ensure_ascii=False))
            return 0

        section = self.args.section
        if section:
            data = self.config.get_section(section)
            if not data:
                log_error(f"Section not found: {section}")
                return 1
            print(f"\n  {colorize(f'Config: {section}', ANSI.BOLD)}")
            print(f"  {'=' * 50}")
            for key, value in sorted(data.items()):
                print(f"  {key:<30} = {value}")
        else:
            config = self.config.to_dict()
            print(f"\n  {colorize('Configuration', ANSI.BOLD)}")
            print(f"  {'=' * 50}")
            for section_name, section_data in sorted(config.items()):
                print(f"\n  {colorize(f'[{section_name}]', ANSI.CYAN)}")
                for key, value in sorted(section_data.items()):
                    print(f"    {key:<28} = {value}")

        return 0

    def _config_set(self) -> int:
        """Set a configuration value."""
        key = self.args.key
        value = self.args.value

        # Try to convert to appropriate type
        try:
            converted_value: Any
            if value.lower() == "true":
                converted_value = True
            elif value.lower() == "false":
                converted_value = False
            elif "." in value:
                converted_value = float(value)
            else:
                try:
                    converted_value = int(value)
                except ValueError:
                    converted_value = value
        except (ValueError, TypeError):
            converted_value = value

        old_value = self.config.get(key)
        self.config.set(key, converted_value)

        # Validate
        errors = self.config.validate()
        if errors:
            self.config.set(key, old_value)
            log_error(f"Invalid value. Validation errors:")
            for err in errors:
                log_error(f"  - {err}")
            return 1

        self.config.save()
        log_info(f"Set {key} = {converted_value} (was: {old_value})")
        return 0

    def _config_reset(self) -> int:
        """Reset configuration to defaults."""
        if not self.args.confirm:
            confirm = input("Reset all configuration to defaults? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0

        self.config.reset()
        self.config.save()
        log_info("Configuration reset to defaults")
        return 0

    def _config_validate(self) -> int:
        """Validate current configuration."""
        errors = self.config.validate()
        if errors:
            print(f"  {colorize('Configuration Errors:', ANSI.RED)}")
            for err in errors:
                print(f"    - {err}")
            return 1
        else:
            print(f"  {colorize('Configuration is valid.', ANSI.GREEN)}")
            return 0

    def _config_init(self) -> int:
        """Create a default configuration file."""
        path = self.args.path or self.config.config_path
        create_default_config(path)
        log_info(f"Default configuration created at {path}")
        return 0

    # ------------------------------------------------------------------
    # Command: dashboard
    # ------------------------------------------------------------------

    def _cmd_dashboard(self) -> int:
        """Execute the dashboard command.

        Returns:
            Exit code.
        """
        interface = self.args.interface or self.config.get("scanner.interface", "auto")
        refresh_rate = self.args.refresh or self.config.get("dashboard.refresh_rate", 0.5)
        history_length = self.config.get("dashboard.history_length", 60)

        scanner = WiFiScanner(
            interface=interface,
            poll_interval=refresh_rate,
            scan_timeout=self.config.get("scanner.scan_timeout", 10.0),
        )

        analyzer = SignalAnalyzer(
            ma_window=self.config.get("analyzer.moving_average_window", 5),
            ewma_alpha=self.config.get("analyzer.ewma_alpha", 0.3),
        )

        event_engine = EventEngine(
            rules_file=self.config.get("events.rules_file", "rules.json"),
        )

        dashboard = create_dashboard(
            refresh_rate=refresh_rate,
            history_length=history_length,
        )

        dashboard.start()

        # Check if it's a curses dashboard
        is_curses = hasattr(dashboard, "_stdscr")

        if is_curses:
            # Curses dashboard runs its own loop
            # We need to feed data to it from a separate thread-like approach
            # Since we can't use threading (keeping it simple), we use
            # a polling approach within the curses loop
            import time as _time

            def _feed_data() -> None:
                """Feed scan data to the dashboard."""
                result = scanner.scan()
                if result.success:
                    dashboard.update_data(scan_result=result)
                    analysis = analyzer.process_scan(result.to_dict())
                    events = event_engine.evaluate(analysis)
                    if events:
                        dashboard.update_data(events=events)

            # Monkey-patch the draw method to include data fetching
            original_draw = dashboard._draw

            def _draw_with_data() -> None:
                _feed_data()
                original_draw()

            dashboard._draw = _draw_with_data

            try:
                dashboard.start()
            except KeyboardInterrupt:
                pass
        else:
            # Fallback dashboard: simple loop
            try:
                while dashboard._running:
                    result = scanner.scan()
                    if result.success:
                        dashboard.update_data(scan_result=result)
                        analysis = analyzer.process_scan(result.to_dict())
                        events = event_engine.evaluate(analysis)
                        if events:
                            dashboard.update_data(events=events)

                    # Clear screen and render
                    print("\033[2J\033[H", end="")
                    print(dashboard.render())
                    _time = __import__("time")
                    _time.sleep(refresh_rate)
            except KeyboardInterrupt:
                pass

        dashboard.stop()
        print("\n  Dashboard closed.")
        return 0


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for the wifisense CLI.

    Args:
        argv: Command-line arguments. If None, uses sys.argv[1:].

    Returns:
        Exit code.
    """
    # Handle --no-color
    if argv and "--no-color" in argv:
        from .utils import enable_color
        enable_color(False)

    app = WiFiSenseCLI()
    return app.run(argv)
