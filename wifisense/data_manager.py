"""
WiFiSense-CLI Data Manager

Handles data persistence, session management, CSV export, and
historical data querying for WiFi scan and analysis data. Uses JSON
format for storage with optional CSV export.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .utils import (
    log_debug,
    log_error,
    log_info,
    log_warning,
    safe_int,
    timestamp,
)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """Represents a monitoring session.

    Attributes:
        id: Unique session identifier.
        name: Human-readable session name.
        start_time: Session start timestamp.
        end_time: Session end timestamp (empty if active).
        interface: WiFi interface used.
        platform: Operating system.
        scan_count: Number of scans performed.
        ap_count: Number of unique APs seen.
        status: Session status ('active', 'stopped', 'completed').
        data_file: Path to the session data file.
    """

    id: str = ""
    name: str = ""
    start_time: str = ""
    end_time: str = ""
    interface: str = ""
    platform: str = ""
    scan_count: int = 0
    ap_count: int = 0
    status: str = "active"
    data_file: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "interface": self.interface,
            "platform": self.platform,
            "scan_count": self.scan_count,
            "ap_count": self.ap_count,
            "status": self.status,
            "data_file": self.data_file,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Session:
        """Create a Session from a dictionary."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            start_time=data.get("start_time", ""),
            end_time=data.get("end_time", ""),
            interface=data.get("interface", ""),
            platform=data.get("platform", ""),
            scan_count=safe_int(data.get("scan_count", 0)),
            ap_count=safe_int(data.get("ap_count", 0)),
            status=data.get("status", "active"),
            data_file=data.get("data_file", ""),
        )

    @property
    def duration_seconds(self) -> float:
        """Calculate session duration in seconds."""
        if not self.start_time:
            return 0.0
        start = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
        if self.end_time:
            end = datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))
        else:
            end = datetime.now(timezone.utc)
        return (end - start).total_seconds()

    @property
    def is_active(self) -> bool:
        """Check if the session is still active."""
        return self.status == "active"


# ---------------------------------------------------------------------------
# Data Manager
# ---------------------------------------------------------------------------

class DataManager:
    """Manages WiFi scan data persistence and session management.

    Handles storing scan results, analysis results, and event records
    in JSON format. Supports session-based monitoring with start/stop/
    resume capabilities. Provides CSV export and historical data queries.

    Attributes:
        storage_dir: Directory for data storage.
        session_file: Path to the session index file.
        max_sessions: Maximum number of sessions to retain.
        retention_days: Days to keep session data.
    """

    def __init__(
        self,
        storage_dir: str = "data",
        session_file: str = "session.json",
        max_sessions: int = 100,
        retention_days: int = 30,
    ) -> None:
        """Initialize the data manager.

        Args:
            storage_dir: Directory for storing data files.
            session_file: Name of the session index file.
            max_sessions: Maximum sessions to keep.
            retention_days: Data retention period in days.
        """
        self.storage_dir = storage_dir
        self.session_file = session_file
        self.max_sessions = max_sessions
        self.retention_days = retention_days

        # Ensure storage directory exists
        os.makedirs(self.storage_dir, exist_ok=True)

        # Session index
        self._sessions: Dict[str, Session] = {}
        self._active_session: Optional[Session] = None

        # Load existing session index
        self._load_session_index()

    def _session_index_path(self) -> str:
        """Get the full path to the session index file."""
        return os.path.join(self.storage_dir, self.session_file)

    def _session_data_path(self, session_id: str) -> str:
        """Get the data file path for a session.

        Args:
            session_id: The session identifier.

        Returns:
            Full path to the session data file.
        """
        return os.path.join(self.storage_dir, f"session_{session_id}.json")

    def _load_session_index(self) -> None:
        """Load the session index from disk."""
        path = self._session_index_path()
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions_data = data.get("sessions", {})
                for sid, sdata in sessions_data.items():
                    self._sessions[sid] = Session.from_dict(sdata)
                log_debug(f"Loaded {len(self._sessions)} sessions from index")
            except (json.JSONDecodeError, IOError) as e:
                log_warning(f"Failed to load session index: {e}")

    def _save_session_index(self) -> None:
        """Save the session index to disk."""
        path = self._session_index_path()
        try:
            data = {
                "sessions": {
                    sid: s.to_dict() for sid, s in self._sessions.items()
                }
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            log_error(f"Failed to save session index: {e}")

    # ------------------------------------------------------------------
    # Session Management
    # ------------------------------------------------------------------

    def start_session(
        self,
        name: str = "",
        interface: str = "",
        platform: str = "",
    ) -> Session:
        """Start a new monitoring session.

        Args:
            name: Session name. Auto-generated if empty.
            interface: WiFi interface being used.
            platform: Operating system.

        Returns:
            The newly created Session object.
        """
        # Stop any active session
        if self._active_session and self._active_session.is_active:
            self.stop_session()

        # Generate session ID and name
        now = datetime.now()
        session_id = now.strftime("%Y%m%d_%H%M%S")
        if not name:
            name = f"Session {now.strftime('%Y-%m-%d %H:%M')}"

        session = Session(
            id=session_id,
            name=name,
            start_time=timestamp(),
            interface=interface,
            platform=platform,
            status="active",
            data_file=self._session_data_path(session_id),
        )

        self._sessions[session_id] = session
        self._active_session = session

        # Enforce max sessions limit
        self._enforce_session_limit()

        self._save_session_index()
        log_info(f"Started session: {session.name} (ID: {session_id})")
        return session

    def stop_session(self) -> Optional[Session]:
        """Stop the currently active session.

        Returns:
            The stopped Session, or None if no active session.
        """
        if not self._active_session or not self._active_session.is_active:
            return None

        self._active_session.end_time = timestamp()
        self._active_session.status = "completed"
        self._save_session_index()

        session = self._active_session
        log_info(f"Stopped session: {session.name} (scans: {session.scan_count})")
        self._active_session = None
        return session

    def resume_session(self, session_id: str) -> Optional[Session]:
        """Resume a previously stopped session.

        Args:
            session_id: The session to resume.

        Returns:
            The resumed Session, or None if not found.
        """
        if session_id not in self._sessions:
            log_warning(f"Session not found: {session_id}")
            return None

        # Stop any active session first
        if self._active_session and self._active_session.is_active:
            self.stop_session()

        session = self._sessions[session_id]
        session.status = "active"
        session.end_time = ""
        self._active_session = session
        self._save_session_index()

        log_info(f"Resumed session: {session.name}")
        return session

    def get_active_session(self) -> Optional[Session]:
        """Get the currently active session.

        Returns:
            The active Session, or None.
        """
        return self._active_session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID.

        Args:
            session_id: The session identifier.

        Returns:
            The Session object, or None if not found.
        """
        return self._sessions.get(session_id)

    def list_sessions(self) -> List[Session]:
        """List all sessions.

        Returns:
            List of all Session objects.
        """
        return sorted(
            self._sessions.values(),
            key=lambda s: s.start_time,
            reverse=True,
        )

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its data file.

        Args:
            session_id: The session to delete.

        Returns:
            True if the session was found and deleted.
        """
        if session_id not in self._sessions:
            return False

        session = self._sessions.pop(session_id)

        # Delete data file
        if session.data_file and os.path.isfile(session.data_file):
            try:
                os.remove(session.data_file)
            except OSError:
                pass

        if self._active_session and self._active_session.id == session_id:
            self._active_session = None

        self._save_session_index()
        log_debug(f"Deleted session: {session_id}")
        return True

    def _enforce_session_limit(self) -> None:
        """Remove oldest sessions when exceeding max_sessions."""
        while len(self._sessions) > self.max_sessions:
            oldest = min(
                self._sessions.values(),
                key=lambda s: s.start_time,
            )
            self.delete_session(oldest.id)

    # ------------------------------------------------------------------
    # Data Recording
    # ------------------------------------------------------------------

    def record_scan(self, scan_data: Dict[str, Any]) -> None:
        """Record a scan result to the active session.

        Args:
            scan_data: Scan result dictionary (from ScanResult.to_dict()).
        """
        if not self._active_session or not self._active_session.is_active:
            return

        session = self._active_session
        session.scan_count += 1

        # Track unique APs
        aps = scan_data.get("aps", [])
        seen_bssids = set()
        if os.path.isfile(session.data_file):
            try:
                with open(session.data_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                for record in existing.get("scans", []):
                    for ap in record.get("aps", []):
                        seen_bssids.add(ap.get("bssid", ""))
            except (json.JSONDecodeError, IOError):
                pass

        for ap in aps:
            seen_bssids.add(ap.get("bssid", ""))
        session.ap_count = len(seen_bssids)

        # Append scan to data file
        self._append_to_data_file(session.data_file, "scans", scan_data)

    def record_analysis(self, analysis_data: Dict[str, Any]) -> None:
        """Record an analysis result to the active session.

        Args:
            analysis_data: Analysis result dictionary.
        """
        if not self._active_session or not self._active_session.is_active:
            return

        self._append_to_data_file(
            self._active_session.data_file, "analysis", analysis_data
        )

    def record_event(self, event_data: Dict[str, Any]) -> None:
        """Record an event to the active session.

        Args:
            event_data: Event record dictionary.
        """
        if not self._active_session or not self._active_session.is_active:
            return

        self._append_to_data_file(
            self._active_session.data_file, "events", event_data
        )

    def _append_to_data_file(
        self, file_path: str, category: str, data: Dict[str, Any]
    ) -> None:
        """Append a data record to a session data file.

        Args:
            file_path: Path to the data file.
            category: Category key ('scans', 'analysis', 'events').
            data: The data record to append.
        """
        # Load existing data or create new structure
        existing: Dict[str, Any] = {}
        if os.path.isfile(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing = {}

        if category not in existing:
            existing[category] = []
        existing[category].append(data)

        # Save
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
        except IOError as e:
            log_error(f"Failed to write data file: {e}")

    # ------------------------------------------------------------------
    # Data Query
    # ------------------------------------------------------------------

    def get_session_data(
        self, session_id: str
    ) -> Optional[Dict[str, Any]]:
        """Load all data for a session.

        Args:
            session_id: The session identifier.

        Returns:
            Dictionary with 'scans', 'analysis', 'events' lists,
            or None if session not found.
        """
        session = self._sessions.get(session_id)
        if not session:
            return None

        data_file = session.data_file
        if not os.path.isfile(data_file):
            return {"scans": [], "analysis": [], "events": []}

        try:
            with open(data_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log_error(f"Failed to load session data: {e}")
            return None

    def get_scan_history(
        self, session_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get scan history for a session.

        Args:
            session_id: Session identifier.
            limit: Maximum number of scans to return.

        Returns:
            List of scan data dictionaries.
        """
        data = self.get_session_data(session_id)
        if not data:
            return []
        scans = data.get("scans", [])
        return scans[-limit:]

    def get_analysis_history(
        self, session_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get analysis history for a session.

        Args:
            session_id: Session identifier.
            limit: Maximum number of results to return.

        Returns:
            List of analysis data dictionaries.
        """
        data = self.get_session_data(session_id)
        if not data:
            return []
        analysis = data.get("analysis", [])
        return analysis[-limit:]

    def get_event_history(
        self, session_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get event history for a session.

        Args:
            session_id: Session identifier.
            limit: Maximum number of events to return.

        Returns:
            List of event data dictionaries.
        """
        data = self.get_session_data(session_id)
        if not data:
            return []
        events = data.get("events", [])
        return events[-limit:]

    def query_rssi_history(
        self,
        session_id: str,
        bssid: str = "",
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Query RSSI history for a specific BSSID across all scans.

        Args:
            session_id: Session identifier.
            bssid: BSSID to filter by (empty for all).
            limit: Maximum number of entries.

        Returns:
            List of dictionaries with 'timestamp', 'bssid', 'ssid', 'rssi'.
        """
        scans = self.get_scan_history(session_id, limit=limit * 10)
        entries: List[Dict[str, Any]] = []

        for scan in scans:
            ts = scan.get("timestamp", "")
            for ap in scan.get("aps", []):
                if bssid and ap.get("bssid", "") != bssid:
                    continue
                entries.append({
                    "timestamp": ts,
                    "bssid": ap.get("bssid", ""),
                    "ssid": ap.get("ssid", ""),
                    "rssi": ap.get("rssi", 0),
                    "quality": ap.get("quality", 0),
                    "channel": ap.get("channel", 0),
                })
                if len(entries) >= limit:
                    return entries

        return entries

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_session_statistics(self, session_id: str) -> Dict[str, Any]:
        """Compute aggregate statistics for a session.

        Args:
            session_id: Session identifier.

        Returns:
            Dictionary with session statistics.
        """
        session = self._sessions.get(session_id)
        if not session:
            return {}

        data = self.get_session_data(session_id)
        if not data:
            return session.to_dict()

        scans = data.get("scans", [])
        events = data.get("events", [])

        # Collect all RSSI values per BSSID
        rssi_by_bssid: Dict[str, List[float]] = {}
        for scan in scans:
            for ap in scan.get("aps", []):
                bssid = ap.get("bssid", "")
                rssi = ap.get("rssi", 0)
                if bssid:
                    if bssid not in rssi_by_bssid:
                        rssi_by_bssid[bssid] = []
                    rssi_by_bssid[bssid].append(rssi)

        # Compute per-AP stats
        ap_stats: List[Dict[str, Any]] = []
        for bssid, rssi_list in sorted(rssi_by_bssid.items()):
            if not rssi_list:
                continue
            ap_stats.append({
                "bssid": bssid,
                "count": len(rssi_list),
                "mean": sum(rssi_list) / len(rssi_list),
                "min": min(rssi_list),
                "max": max(rssi_list),
                "range": max(rssi_list) - min(rssi_list),
            })

        return {
            **session.to_dict(),
            "total_events": len(events),
            "unique_aps": len(rssi_by_bssid),
            "ap_statistics": ap_stats,
        }

    # ------------------------------------------------------------------
    # CSV Export
    # ------------------------------------------------------------------

    def export_csv(
        self,
        session_id: str,
        output_path: str,
        data_type: str = "scans",
    ) -> bool:
        """Export session data to CSV format.

        Args:
            session_id: Session identifier.
            output_path: Output CSV file path.
            data_type: Type of data to export ('scans', 'analysis', 'events').

        Returns:
            True if export succeeded.
        """
        data = self.get_session_data(session_id)
        if not data:
            log_error(f"No data found for session: {session_id}")
            return False

        records = data.get(data_type, [])
        if not records:
            log_warning(f"No {data_type} records to export")
            return False

        try:
            os.makedirs(
                os.path.dirname(output_path) if os.path.dirname(output_path) else ".",
                exist_ok=True,
            )

            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)

                if data_type == "scans":
                    self._write_scans_csv(writer, records)
                elif data_type == "analysis":
                    self._write_analysis_csv(writer, records)
                elif data_type == "events":
                    self._write_events_csv(writer, records)
                else:
                    log_error(f"Unknown data type: {data_type}")
                    return False

            log_info(f"Exported {len(records)} {data_type} to {output_path}")
            return True

        except IOError as e:
            log_error(f"CSV export failed: {e}")
            return False

    def _write_scans_csv(
        self, writer: csv.writer, records: List[Dict[str, Any]]
    ) -> None:
        """Write scan records to CSV.

        Args:
            writer: CSV writer.
            records: List of scan record dictionaries.
        """
        # Header
        writer.writerow([
            "timestamp", "bssid", "ssid", "rssi", "noise", "quality",
            "channel", "frequency", "security", "mode", "band",
        ])
        # Data rows
        for scan in records:
            ts = scan.get("timestamp", "")
            for ap in scan.get("aps", []):
                writer.writerow([
                    ts,
                    ap.get("bssid", ""),
                    ap.get("ssid", ""),
                    ap.get("rssi", ""),
                    ap.get("noise", ""),
                    ap.get("quality", ""),
                    ap.get("channel", ""),
                    ap.get("frequency", ""),
                    ap.get("security", ""),
                    ap.get("mode", ""),
                    ap.get("band", ""),
                ])

    def _write_analysis_csv(
        self, writer: csv.writer, records: List[Dict[str, Any]]
    ) -> None:
        """Write analysis records to CSV.

        Args:
            writer: CSV writer.
            records: List of analysis record dictionaries.
        """
        # Flatten analysis results
        writer.writerow([
            "timestamp", "bssid", "ssid", "current_rssi", "filtered_rssi",
            "rssi_change", "moving_average", "ewma", "z_score",
            "is_anomaly", "trend_direction", "trend_slope",
            "event_class",
        ])
        for record in records:
            # Handle list of results
            results = record if isinstance(record, list) else [record]
            for r in results:
                if isinstance(r, dict):
                    writer.writerow([
                        r.get("timestamp", ""),
                        r.get("bssid", ""),
                        r.get("ssid", ""),
                        r.get("current_rssi", ""),
                        r.get("filtered_rssi", ""),
                        r.get("rssi_change", ""),
                        r.get("moving_average", ""),
                        r.get("ewma", ""),
                        r.get("z_score", ""),
                        r.get("is_anomaly", ""),
                        r.get("trend_direction", ""),
                        r.get("trend_slope", ""),
                        r.get("event_class", ""),
                    ])

    def _write_events_csv(
        self, writer: csv.writer, records: List[Dict[str, Any]]
    ) -> None:
        """Write event records to CSV.

        Args:
            writer: CSV writer.
            records: List of event record dictionaries.
        """
        writer.writerow([
            "timestamp", "rule_name", "success",
            "actions_executed",
        ])
        for event in records:
            writer.writerow([
                event.get("timestamp", ""),
                event.get("rule_name", ""),
                event.get("success", ""),
                ", ".join(event.get("actions_executed", [])),
            ])

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_old_sessions(self) -> int:
        """Remove sessions older than the retention period.

        Returns:
            Number of sessions removed.
        """
        removed = 0
        cutoff = datetime.now(timezone.utc).timestamp() - (
            self.retention_days * 86400
        )

        for session_id, session in list(self._sessions.items()):
            if session.status == "active":
                continue
            if session.end_time:
                try:
                    end = datetime.fromisoformat(
                        session.end_time.replace("Z", "+00:00")
                    )
                    if end.timestamp() < cutoff:
                        self.delete_session(session_id)
                        removed += 1
                except (ValueError, OSError):
                    pass

        if removed > 0:
            log_info(f"Cleaned up {removed} old sessions")

        return removed

    def get_storage_size(self) -> Dict[str, int]:
        """Get storage usage statistics.

        Returns:
            Dictionary with 'total_bytes', 'file_count', 'session_count'.
        """
        total_bytes = 0
        file_count = 0

        if os.path.isdir(self.storage_dir):
            for entry in os.scandir(self.storage_dir):
                if entry.is_file():
                    total_bytes += entry.stat().st_size
                    file_count += 1

        return {
            "total_bytes": total_bytes,
            "file_count": file_count,
            "session_count": len(self._sessions),
        }

    def __repr__(self) -> str:
        return (
            f"DataManager(sessions={len(self._sessions)}, "
            f"active={self._active_session is not None}, "
            f"storage={self.storage_dir!r})"
        )
