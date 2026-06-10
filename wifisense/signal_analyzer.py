"""
WiFiSense-CLI Signal Analysis Engine

Provides signal processing and analysis capabilities including moving
average filtering, exponential weighted moving average (EWMA), anomaly
detection via Z-Score and IQR methods, trend analysis using linear
regression, and environment fingerprinting based on multi-AP RSSI vectors.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

from .utils import (
    compute_statistics,
    cosine_similarity,
    euclidean_distance,
    exponential_moving_average,
    iqr_anomaly,
    iqr_bounds,
    linear_regression_slope,
    log_debug,
    log_info,
    moving_average,
    safe_float,
    timestamp,
    z_score,
    z_score_anomaly,
)


# ---------------------------------------------------------------------------
# Event Classification Enum
# ---------------------------------------------------------------------------

class EventClass(Enum):
    """Classification of detected WiFi environment events."""
    IDLE = "IDLE"
    CHANGED = "CHANGED"
    DEGRADED = "DEGRADED"
    IMPROVED = "IMPROVED"
    ANOMALY = "ANOMALY"


class TrendDirection(Enum):
    """Direction of signal trend."""
    STABLE = "STABLE"
    INCREASING = "INCREASING"
    DECREASING = "DECREASING"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    """Result of signal analysis for a single scan cycle.

    Attributes:
        timestamp: When the analysis was performed.
        bssid: BSSID of the analyzed AP.
        ssid: SSID of the analyzed AP.
        current_rssi: Current raw RSSI value.
        filtered_rssi: RSSI after filtering (moving average or EWMA).
        rssi_change: Change from previous reading.
        rssi_change_rate: Rate of change per second.
        moving_average: Current moving average value.
        ewma: Current EWMA value.
        z_score: Z-score of current reading.
        is_anomaly_zscore: Whether Z-score method detects anomaly.
        is_anomaly_iqr: Whether IQR method detects anomaly.
        is_anomaly: Combined anomaly detection result.
        trend_direction: Current trend direction.
        trend_slope: Linear regression slope value.
        statistics: Computed statistics for the history window.
        event_class: Classified event type.
        fingerprint_distance: Distance from reference fingerprint.
    """

    timestamp: str = ""
    bssid: str = ""
    ssid: str = ""
    current_rssi: float = 0.0
    filtered_rssi: float = 0.0
    rssi_change: float = 0.0
    rssi_change_rate: float = 0.0
    moving_average: float = 0.0
    ewma: float = 0.0
    z_score: float = 0.0
    is_anomaly_zscore: bool = False
    is_anomaly_iqr: bool = False
    is_anomaly: bool = False
    trend_direction: TrendDirection = TrendDirection.STABLE
    trend_slope: float = 0.0
    statistics: Dict[str, float] = field(default_factory=dict)
    event_class: EventClass = EventClass.IDLE
    fingerprint_distance: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp,
            "bssid": self.bssid,
            "ssid": self.ssid,
            "current_rssi": self.current_rssi,
            "filtered_rssi": self.filtered_rssi,
            "rssi_change": self.rssi_change,
            "rssi_change_rate": self.rssi_change_rate,
            "moving_average": self.moving_average,
            "ewma": self.ewma,
            "z_score": self.z_score,
            "is_anomaly_zscore": self.is_anomaly_zscore,
            "is_anomaly_iqr": self.is_anomaly_iqr,
            "is_anomaly": self.is_anomaly,
            "trend_direction": self.trend_direction.value,
            "trend_slope": self.trend_slope,
            "statistics": self.statistics,
            "event_class": self.event_class.value,
            "fingerprint_distance": self.fingerprint_distance,
        }


@dataclass
class EnvironmentFingerprint:
    """Fingerprint of the WiFi environment based on multi-AP RSSI vector.

    Attributes:
        timestamp: When the fingerprint was captured.
        ap_vector: Dictionary mapping BSSID to RSSI value.
        label: Optional label for the fingerprint (e.g., 'home', 'office').
        ap_count: Number of APs in the fingerprint.
    """

    timestamp: str = ""
    ap_vector: Dict[str, float] = field(default_factory=dict)
    label: str = ""
    ap_count: int = 0

    def __post_init__(self) -> None:
        """Compute derived fields after initialization."""
        if not self.timestamp:
            self.timestamp = timestamp()
        self.ap_count = len(self.ap_vector)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp,
            "ap_vector": self.ap_vector,
            "label": self.label,
            "ap_count": self.ap_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EnvironmentFingerprint:
        """Create a fingerprint from a dictionary."""
        return cls(
            timestamp=data.get("timestamp", ""),
            ap_vector=data.get("ap_vector", {}),
            label=data.get("label", ""),
        )

    def distance_to(self, other: EnvironmentFingerprint) -> float:
        """Calculate Euclidean distance to another fingerprint.

        Only considers APs present in both fingerprints.

        Args:
            other: Another fingerprint to compare against.

        Returns:
            Euclidean distance between the two fingerprint vectors.
        """
        common_bssids = set(self.ap_vector.keys()) & set(other.ap_vector.keys())
        if not common_bssids:
            return float("inf")

        v1 = [self.ap_vector[b] for b in sorted(common_bssids)]
        v2 = [other.ap_vector[b] for b in sorted(common_bssids)]
        return euclidean_distance(v1, v2)

    def similarity_to(self, other: EnvironmentFingerprint) -> float:
        """Calculate cosine similarity to another fingerprint.

        Only considers APs present in both fingerprints.

        Args:
            other: Another fingerprint to compare against.

        Returns:
            Cosine similarity between -1 and 1.
        """
        common_bssids = set(self.ap_vector.keys()) & set(other.ap_vector.keys())
        if not common_bssids:
            return 0.0

        v1 = [self.ap_vector[b] for b in sorted(common_bssids)]
        v2 = [other.ap_vector[b] for b in sorted(common_bssids)]
        return cosine_similarity(v1, v2)


# ---------------------------------------------------------------------------
# Per-AP History Tracker
# ---------------------------------------------------------------------------

class APHistory:
    """Maintains a rolling history of RSSI readings for a single AP.

    Attributes:
        bssid: BSSID of the tracked AP.
        ssid: SSID of the tracked AP.
        max_size: Maximum number of readings to keep.
        rssi_history: Deque of RSSI values.
        timestamp_history: Deque of timestamps.
    """

    def __init__(self, bssid: str, ssid: str = "", max_size: int = 100) -> None:
        """Initialize AP history tracker.

        Args:
            bssid: BSSID of the AP.
            ssid: SSID of the AP.
            max_size: Maximum number of historical readings to retain.
        """
        self.bssid = bssid
        self.ssid = ssid
        self.max_size = max_size
        self.rssi_history: Deque[float] = deque(maxlen=max_size)
        self.timestamp_history: Deque[str] = deque(maxlen=max_size)

    def add_reading(self, rssi: float, ts: str = "") -> None:
        """Add a new RSSI reading to the history.

        Args:
            rssi: RSSI value in dBm.
            ts: Timestamp string. If empty, current time is used.
        """
        if not ts:
            ts = timestamp()
        self.rssi_history.append(rssi)
        self.timestamp_history.append(ts)

    @property
    def count(self) -> int:
        """Number of readings in history."""
        return len(self.rssi_history)

    @property
    def last_rssi(self) -> Optional[float]:
        """Most recent RSSI value, or None if empty."""
        return self.rssi_history[-1] if self.rssi_history else None

    @property
    def previous_rssi(self) -> Optional[float]:
        """Second-to-last RSSI value, or None."""
        return self.rssi_history[-2] if len(self.rssi_history) >= 2 else None

    @property
    def rssi_list(self) -> List[float]:
        """RSSI history as a list."""
        return list(self.rssi_history)

    def get_statistics(self) -> Dict[str, float]:
        """Compute statistics over the current history.

        Returns:
            Dictionary with count, mean, median, stdev, min, max, range, q1, q3.
        """
        return compute_statistics(self.rssi_list())

    def clear(self) -> None:
        """Clear all historical data."""
        self.rssi_history.clear()
        self.timestamp_history.clear()


# ---------------------------------------------------------------------------
# Signal Analyzer
# ---------------------------------------------------------------------------

class SignalAnalyzer:
    """Analyzes WiFi signal data to detect environmental changes.

    Maintains per-AP history, applies filtering algorithms, detects
    anomalies, analyzes trends, and generates environment fingerprints.

    Attributes:
        ma_window: Moving average window size.
        ewma_alpha: EWMA smoothing factor.
        z_score_threshold: Threshold for Z-score anomaly detection.
        iqr_factor: IQR multiplier for anomaly bounds.
        trend_window: Window size for trend analysis.
        anomaly_cooldown: Minimum seconds between anomaly alerts.
        fingerprint_min_aps: Minimum APs required for fingerprint.
        max_history: Maximum readings per AP.
    """

    def __init__(
        self,
        ma_window: int = 5,
        ewma_alpha: float = 0.3,
        z_score_threshold: float = 2.0,
        iqr_factor: float = 1.5,
        trend_window: int = 10,
        anomaly_cooldown: float = 5.0,
        fingerprint_min_aps: int = 2,
        max_history: int = 500,
    ) -> None:
        """Initialize the signal analyzer.

        Args:
            ma_window: Window size for simple moving average.
            ewma_alpha: Smoothing factor for EWMA (0.0 to 1.0).
            z_score_threshold: Z-score threshold for anomaly detection.
            iqr_factor: IQR multiplier for anomaly detection.
            trend_window: Number of readings for trend analysis.
            anomaly_cooldown: Cooldown period between anomaly alerts (seconds).
            fingerprint_min_aps: Minimum APs for valid fingerprint.
            max_history: Maximum number of readings stored per AP.
        """
        self.ma_window = ma_window
        self.ewma_alpha = ewma_alpha
        self.z_score_threshold = z_score_threshold
        self.iqr_factor = iqr_factor
        self.trend_window = trend_window
        self.anomaly_cooldown = anomaly_cooldown
        self.fingerprint_min_aps = fingerprint_min_aps
        self.max_history = max_history

        # Per-AP history storage
        self._ap_histories: Dict[str, APHistory] = {}

        # Reference fingerprints
        self._reference_fingerprints: List[EnvironmentFingerprint] = []

        # Anomaly cooldown tracking
        self._last_anomaly_time: Dict[str, float] = {}

        # Analysis results history
        self._results_history: List[AnalysisResult] = []

    def process_scan(self, ap_data: Dict[str, Any]) -> List[AnalysisResult]:
        """Process a new scan result and analyze all detected APs.

        Args:
            ap_data: Dictionary with 'aps' key containing a list of
                     APInfo dictionaries (as returned by ScanResult.to_dict()).

        Returns:
            List of AnalysisResult objects, one per AP.
        """
        aps = ap_data.get("aps", [])
        results: List[AnalysisResult] = []

        for ap_info in aps:
            bssid = ap_info.get("bssid", "")
            ssid = ap_info.get("ssid", "")
            rssi = safe_float(ap_info.get("rssi", 0.0))

            if not bssid:
                continue

            result = self._analyze_ap(bssid, ssid, rssi)
            results.append(result)

        # Store results
        self._results_history.extend(results)
        if len(self._results_history) > self.max_history * 10:
            self._results_history = self._results_history[-self.max_history * 5:]

        return results

    def _analyze_ap(self, bssid: str, ssid: str, rssi: float) -> AnalysisResult:
        """Analyze a single AP reading.

        Args:
            bssid: BSSID of the AP.
            ssid: SSID of the AP.
            rssi: Current RSSI reading.

        Returns:
            AnalysisResult with all computed metrics.
        """
        now = timestamp()

        # Get or create AP history
        if bssid not in self._ap_histories:
            self._ap_histories[bssid] = APHistory(
                bssid=bssid, ssid=ssid, max_size=self.max_history
            )
        history = self._ap_histories[bssid]
        history.ssid = ssid

        # Get previous values
        prev_rssi = history.last_rssi

        # Add new reading
        history.add_reading(rssi, now)

        # Build result
        result = AnalysisResult(
            timestamp=now,
            bssid=bssid,
            ssid=ssid,
            current_rssi=rssi,
        )

        # Compute change
        if prev_rssi is not None:
            result.rssi_change = rssi - prev_rssi

        # Moving average
        rssi_list = history.rssi_list
        if len(rssi_list) >= self.ma_window:
            ma_values = moving_average(rssi_list, self.ma_window)
            result.moving_average = ma_values[-1]
            result.filtered_rssi = result.moving_average
        else:
            result.moving_average = rssi
            result.filtered_rssi = rssi

        # EWMA
        ewma_values = exponential_moving_average(rssi_list, self.ewma_alpha)
        result.ewma = ewma_values[-1]

        # Statistics
        if len(rssi_list) >= 2:
            result.statistics = history.get_statistics()
            mean = result.statistics["mean"]
            std = result.statistics["stdev"]

            # Z-score
            result.z_score = z_score(rssi, mean, std)
            result.is_anomaly_zscore = z_score_anomaly(
                rssi, mean, std, self.z_score_threshold
            )

            # IQR
            result.is_anomaly_iqr = iqr_anomaly(
                rssi, rssi_list, self.iqr_factor
            )

            # Combined anomaly
            result.is_anomaly = (
                result.is_anomaly_zscore or result.is_anomaly_iqr
            )

            # Apply anomaly cooldown
            if result.is_anomaly:
                import time as _time
                last_time = self._last_anomaly_time.get(bssid, 0.0)
                current_time = _time.monotonic()
                if current_time - last_time < self.anomaly_cooldown:
                    result.is_anomaly = False
                else:
                    self._last_anomaly_time[bssid] = current_time

        # Trend analysis
        if len(rssi_list) >= self.trend_window:
            trend_data = rssi_list[-self.trend_window:]
            x_values = list(range(len(trend_data)))
            slope = linear_regression_slope(x_values, trend_data)
            result.trend_slope = slope

            if slope > 0.5:
                result.trend_direction = TrendDirection.INCREASING
            elif slope < -0.5:
                result.trend_direction = TrendDirection.DECREASING
            else:
                result.trend_direction = TrendDirection.STABLE

        # Event classification
        result.event_class = self._classify_event(result)

        # Fingerprint distance
        if self._reference_fingerprints:
            fp = self._generate_fingerprint()
            min_dist = min(
                ref.distance_to(fp) for ref in self._reference_fingerprints
            )
            result.fingerprint_distance = min_dist

        return result

    def _classify_event(self, result: AnalysisResult) -> EventClass:
        """Classify the type of event based on analysis results.

        Args:
            result: The analysis result to classify.

        Returns:
            EventClass enum value.
        """
        # Anomaly takes priority
        if result.is_anomaly:
            return EventClass.ANOMALY

        # Check trend direction
        if result.trend_direction == TrendDirection.DECREASING:
            if abs(result.trend_slope) > 2.0:
                return EventClass.DEGRADED
            return EventClass.CHANGED

        if result.trend_direction == TrendDirection.INCREASING:
            if abs(result.trend_slope) > 2.0:
                return EventClass.IMPROVED
            return EventClass.CHANGED

        # Check for significant change
        if abs(result.rssi_change) > 10:
            if result.rssi_change < 0:
                return EventClass.DEGRADED
            else:
                return EventClass.IMPROVED

        return EventClass.IDLE

    # ------------------------------------------------------------------
    # Fingerprinting
    # ------------------------------------------------------------------

    def _generate_fingerprint(self) -> EnvironmentFingerprint:
        """Generate a current environment fingerprint from all tracked APs.

        Returns:
            EnvironmentFingerprint representing the current state.
        """
        ap_vector: Dict[str, float] = {}
        for bssid, history in self._ap_histories.items():
            if history.last_rssi is not None:
                ap_vector[bssid] = history.last_rssi

        return EnvironmentFingerprint(ap_vector=ap_vector)

    def capture_fingerprint(self, label: str = "") -> EnvironmentFingerprint:
        """Capture and store a reference environment fingerprint.

        Args:
            label: Optional label for the fingerprint.

        Returns:
            The captured fingerprint.
        """
        fp = self._generate_fingerprint()
        fp.label = label
        self._reference_fingerprints.append(fp)
        log_info(
            f"Captured fingerprint '{label}': "
            f"{fp.ap_count} APs"
        )
        return fp

    def compare_fingerprint(self) -> Tuple[float, Optional[EnvironmentFingerprint]]:
        """Compare current environment against reference fingerprints.

        Returns:
            Tuple of (distance, closest_reference_fingerprint).
        """
        if not self._reference_fingerprints:
            return 0.0, None

        current = self._generate_fingerprint()
        best_dist = float("inf")
        best_ref: Optional[EnvironmentFingerprint] = None

        for ref in self._reference_fingerprints:
            dist = ref.distance_to(current)
            if dist < best_dist:
                best_dist = dist
                best_ref = ref

        return best_dist, best_ref

    def get_fingerprints(self) -> List[EnvironmentFingerprint]:
        """Get all stored reference fingerprints.

        Returns:
            List of reference fingerprints.
        """
        return list(self._reference_fingerprints)

    def clear_fingerprints(self) -> None:
        """Remove all stored reference fingerprints."""
        self._reference_fingerprints.clear()

    # ------------------------------------------------------------------
    # History Access
    # ------------------------------------------------------------------

    def get_ap_history(self, bssid: str) -> Optional[APHistory]:
        """Get the history tracker for a specific AP.

        Args:
            bssid: BSSID of the AP.

        Returns:
            APHistory object, or None if not tracked.
        """
        return self._ap_histories.get(bssid)

    def get_all_bssids(self) -> List[str]:
        """Get all tracked BSSIDs.

        Returns:
            List of BSSID strings.
        """
        return list(self._ap_histories.keys())

    def get_analysis_history(self, limit: int = 100) -> List[AnalysisResult]:
        """Get recent analysis results.

        Args:
            limit: Maximum number of results to return.

        Returns:
            List of recent AnalysisResult objects.
        """
        return self._results_history[-limit:]

    def clear_history(self, bssid: Optional[str] = None) -> None:
        """Clear analysis history.

        Args:
            bssid: Specific BSSID to clear, or None to clear all.
        """
        if bssid:
            if bssid in self._ap_histories:
                self._ap_histories[bssid].clear()
                del self._ap_histories[bssid]
        else:
            self._ap_histories.clear()
            self._results_history.clear()
            self._last_anomaly_time.clear()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the current analysis state.

        Returns:
            Dictionary with summary information.
        """
        ap_summaries: List[Dict[str, Any]] = []
        for bssid, history in self._ap_histories.items():
            stats = history.get_statistics()
            ap_summaries.append({
                "bssid": bssid,
                "ssid": history.ssid,
                "current_rssi": history.last_rssi,
                "readings": history.count,
                "mean_rssi": stats.get("mean", 0.0),
                "stdev": stats.get("stdev", 0.0),
                "min_rssi": stats.get("min", 0.0),
                "max_rssi": stats.get("max", 0.0),
            })

        return {
            "tracked_aps": len(self._ap_histories),
            "total_readings": sum(h.count for h in self._ap_histories.values()),
            "reference_fingerprints": len(self._reference_fingerprints),
            "ap_summaries": ap_summaries,
        }

    def __repr__(self) -> str:
        return (
            f"SignalAnalyzer(tracked_aps={len(self._ap_histories)}, "
            f"fingerprints={len(self._reference_fingerprints)})"
        )
