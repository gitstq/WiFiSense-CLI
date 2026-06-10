"""
WiFiSense-CLI WiFi Signal Scanner

Cross-platform WiFi signal strength collector. Supports Linux (nl80211 /
mac80211 via /proc/net/wireless and iw), macOS (CoreWLAN via
system_profiler and airport), and Windows (WLAN API via netsh).

Provides both single-shot scanning and continuous monitoring modes,
with support for multiple access points simultaneously.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from .utils import (
    get_platform,
    get_default_interface,
    is_linux,
    is_macos,
    is_windows,
    log_debug,
    log_error,
    log_info,
    log_warning,
    rssi_to_quality,
    run_command,
    safe_float,
    safe_int,
    timestamp,
)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class APInfo:
    """Represents a single access point observation.

    Attributes:
        ssid: Network name (may be empty for hidden networks).
        bssid: MAC address of the access point.
        rssi: Signal strength in dBm (negative value).
        noise: Noise level in dBm (negative value, may be 0 if unknown).
        quality: Signal quality percentage (0-100).
        channel: WiFi channel number (0 if unknown).
        frequency: Frequency in MHz (0 if unknown).
        security: Security protocol (e.g., 'WPA2', 'OPEN').
        mode: AP mode (e.g., 'Infrastructure', 'Master').
        interface: Network interface used for scanning.
        timestamp: ISO 8601 timestamp of the observation.
        band: Frequency band ('2.4GHz', '5GHz', or 'Unknown').
    """

    ssid: str = ""
    bssid: str = ""
    rssi: float = 0.0
    noise: float = 0.0
    quality: float = 0.0
    channel: int = 0
    frequency: int = 0
    security: str = ""
    mode: str = ""
    interface: str = ""
    timestamp: str = ""
    band: str = ""

    def __post_init__(self) -> None:
        """Set defaults for computed fields after initialization."""
        if not self.timestamp:
            self.timestamp = timestamp()
        if self.rssi != 0.0 and self.quality == 0.0:
            self.quality = rssi_to_quality(self.rssi)
        if self.frequency and not self.band:
            self.band = self._infer_band()

    def _infer_band(self) -> str:
        """Infer frequency band from channel or frequency."""
        if self.frequency >= 2400 and self.frequency <= 2500:
            return "2.4GHz"
        elif self.frequency >= 5000 and self.frequency <= 6000:
            return "5GHz"
        elif self.channel > 0:
            if 1 <= self.channel <= 14:
                return "2.4GHz"
            elif 36 <= self.channel <= 165:
                return "5GHz"
        return "Unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for serialization."""
        return {
            "ssid": self.ssid,
            "bssid": self.bssid,
            "rssi": self.rssi,
            "noise": self.noise,
            "quality": self.quality,
            "channel": self.channel,
            "frequency": self.frequency,
            "security": self.security,
            "mode": self.mode,
            "interface": self.interface,
            "timestamp": self.timestamp,
            "band": self.band,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> APInfo:
        """Create an APInfo instance from a dictionary."""
        return cls(
            ssid=data.get("ssid", ""),
            bssid=data.get("bssid", ""),
            rssi=safe_float(data.get("rssi", 0.0)),
            noise=safe_float(data.get("noise", 0.0)),
            quality=safe_float(data.get("quality", 0.0)),
            channel=safe_int(data.get("channel", 0)),
            frequency=safe_int(data.get("frequency", 0)),
            security=data.get("security", ""),
            mode=data.get("mode", ""),
            interface=data.get("interface", ""),
            timestamp=data.get("timestamp", ""),
            band=data.get("band", ""),
        )


@dataclass
class ScanResult:
    """Result of a single WiFi scan operation.

    Attributes:
        aps: List of detected access points.
        interface: Network interface used for the scan.
        timestamp: ISO 8601 timestamp of the scan.
        scan_duration: Time taken for the scan in seconds.
        platform: Operating system platform.
        success: Whether the scan completed successfully.
        error: Error message if the scan failed.
    """

    aps: List[APInfo] = field(default_factory=list)
    interface: str = ""
    timestamp: str = ""
    scan_duration: float = 0.0
    platform: str = ""
    success: bool = True
    error: str = ""

    def __post_init__(self) -> None:
        """Set defaults for computed fields."""
        if not self.timestamp:
            self.timestamp = timestamp()
        if not self.platform:
            self.platform = get_platform()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for serialization."""
        return {
            "aps": [ap.to_dict() for ap in self.aps],
            "interface": self.interface,
            "timestamp": self.timestamp,
            "scan_duration": self.scan_duration,
            "platform": self.platform,
            "success": self.success,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Scanner Callback Type
# ---------------------------------------------------------------------------

ScanCallback = Callable[[ScanResult], None]


# ---------------------------------------------------------------------------
# WiFi Scanner
# ---------------------------------------------------------------------------

class WiFiScanner:
    """Cross-platform WiFi signal strength scanner.

    Provides methods for single-shot scanning and continuous monitoring
    of WiFi access points. Automatically detects the platform and uses
    the appropriate scanning method.

    Attributes:
        interface: Network interface name for scanning.
        poll_interval: Seconds between scans in monitor mode.
        scan_timeout: Maximum time for a single scan in seconds.
        max_retries: Number of retries on scan failure.
        retry_delay: Delay between retries in seconds.
        include_hidden: Whether to include hidden SSIDs in results.
    """

    def __init__(
        self,
        interface: str = "auto",
        poll_interval: float = 1.0,
        scan_timeout: float = 10.0,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        include_hidden: bool = False,
    ) -> None:
        """Initialize the WiFi scanner.

        Args:
            interface: Network interface name. 'auto' to auto-detect.
            poll_interval: Seconds between scans in monitor mode.
            scan_timeout: Maximum time for a single scan.
            max_retries: Number of retries on scan failure.
            retry_delay: Delay between retries in seconds.
            include_hidden: Whether to include hidden SSIDs.
        """
        self.interface = interface if interface != "auto" else get_default_interface()
        self.poll_interval = poll_interval
        self.scan_timeout = scan_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.include_hidden = include_hidden
        self._monitoring = False
        self._callbacks: List[ScanCallback] = []

    def scan(self) -> ScanResult:
        """Perform a single WiFi scan.

        Automatically selects the appropriate platform-specific
        scanning method and handles retries on failure.

        Returns:
            A ScanResult containing detected access points.
        """
        start_time = time.monotonic()
        last_error = ""

        for attempt in range(self.max_retries):
            try:
                plat = get_platform()
                if plat == "linux":
                    result = self._scan_linux()
                elif plat == "darwin":
                    result = self._scan_macos()
                elif plat == "windows":
                    result = self._scan_windows()
                else:
                    result = ScanResult(
                        interface=self.interface,
                        success=False,
                        error=f"Unsupported platform: {plat}",
                    )

                result.scan_duration = time.monotonic() - start_time
                result.interface = self.interface

                if result.success:
                    # Filter hidden SSIDs if not requested
                    if not self.include_hidden:
                        result.aps = [
                            ap for ap in result.aps if ap.ssid
                        ]
                    log_debug(
                        f"Scan completed: {len(result.aps)} APs found "
                        f"in {result.scan_duration:.2f}s"
                    )
                    return result

                last_error = result.error

            except Exception as e:
                last_error = str(e)
                log_warning(f"Scan attempt {attempt + 1} failed: {e}")

            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)

        return ScanResult(
            interface=self.interface,
            success=False,
            error=f"All {self.max_retries} scan attempts failed. Last error: {last_error}",
            scan_duration=time.monotonic() - start_time,
        )

    # ------------------------------------------------------------------
    # Linux Scanning
    # ------------------------------------------------------------------

    def _scan_linux(self) -> ScanResult:
        """Scan for WiFi access points on Linux.

        Tries multiple methods:
        1. 'iw dev <iface> scan' - Most comprehensive, requires root.
        2. '/proc/net/wireless' - Fast, no root needed, but limited.
        3. 'iwlist <iface> scanning' - Legacy fallback.

        Returns:
            ScanResult with detected APs.
        """
        # Method 1: iw dev scan (best method)
        result = self._scan_linux_iw()
        if result.success and result.aps:
            return result

        # Method 2: /proc/net/wireless (connected AP only)
        result = self._scan_linux_proc()
        if result.success and result.aps:
            return result

        # Method 3: iwlist (legacy)
        result = self._scan_linux_iwlist()
        if result.success and result.aps:
            return result

        return ScanResult(
            interface=self.interface,
            success=False,
            error="All Linux scan methods failed",
        )

    def _scan_linux_iw(self) -> ScanResult:
        """Scan using 'iw dev <iface> scan' command.

        Returns:
            ScanResult with detected APs, or a failed result.
        """
        code, stdout, stderr = run_command(
            ["iw", "dev", self.interface, "scan"],
            timeout=self.scan_timeout,
        )
        if code != 0:
            log_debug(f"iw scan failed (code {code}): {stderr.strip()}")
            return ScanResult(
                interface=self.interface,
                success=False,
                error=f"iw scan failed: {stderr.strip()}",
            )

        aps = self._parse_iw_output(stdout)
        return ScanResult(interface=self.interface, aps=aps)

    def _parse_iw_output(self, output: str) -> List[APInfo]:
        """Parse output from 'iw dev <iface> scan'.

        Args:
            output: Raw output from the iw command.

        Returns:
            List of APInfo objects.
        """
        aps: List[APInfo] = []

        # Split into BSS sections
        bss_sections = re.split(r"(?m)^(BSS ", output)

        for section in bss_sections[1:]:  # Skip text before first BSS
            ap = APInfo(interface=self.interface)

            # BSSID
            bss_match = re.match(r"BSS ([0-9a-fA-F:]+)", section)
            if bss_match:
                ap.bssid = bss_match.group(1).upper()

            # SSID
            ssid_match = re.search(r"SSID: (.+)", section)
            if ssid_match:
                ap.ssid = ssid_match.group(1).strip()

            # Signal strength (RSSI)
            signal_match = re.search(r"signal:\s*(-?\d+(?:\.\d+)?)\s*dBm", section)
            if signal_match:
                ap.rssi = float(signal_match.group(1))

            # Channel
            channel_match = re.search(r"channel:\s*(\d+)", section)
            if channel_match:
                ap.channel = int(channel_match.group(1))

            # Frequency
            freq_match = re.search(r"freq:\s*(\d+)", section)
            if freq_match:
                ap.frequency = int(freq_match.group(1))

            # Security
            if "WPA2" in section:
                ap.security = "WPA2"
            elif "WPA" in section:
                ap.security = "WPA"
            elif "WEP" in section:
                ap.security = "WEP"
            else:
                ap.security = "OPEN"

            # Noise level (not always available in iw output)
            noise_match = re.search(r"noise:\s*(-?\d+(?:\.\d+)?)\s*dBm", section)
            if noise_match:
                ap.noise = float(noise_match.group(1))

            aps.append(ap)

        return aps

    def _scan_linux_proc(self) -> ScanResult:
        """Scan using /proc/net/wireless (connected AP only).

        Returns:
            ScanResult with the currently connected AP, or a failed result.
        """
        try:
            with open("/proc/net/wireless", "r") as f:
                content = f.read()
        except (OSError, IOError) as e:
            return ScanResult(
                interface=self.interface,
                success=False,
                error=f"Cannot read /proc/net/wireless: {e}",
            )

        aps = self._parse_proc_wireless(content)
        if aps:
            return ScanResult(interface=self.interface, aps=aps)

        return ScanResult(
            interface=self.interface,
            success=False,
            error="No data in /proc/net/wireless",
        )

    def _parse_proc_wireless(self, content: str) -> List[APInfo]:
        """Parse /proc/net/wireless output.

        Format:
            Inter-| sta-|   Quality   | ...
            face | tus |   link level | noise  | ...
            wlan0: 0000  70.  -62.  -256.  0

        Args:
            content: Raw file content.

        Returns:
            List of APInfo objects (typically one for connected AP).
        """
        aps: List[APInfo] = []
        for line in content.strip().split("\n")[2:]:  # Skip header lines
            line = line.strip()
            if not line or ":" not in line:
                continue

            # Parse interface name and status
            iface_match = re.match(r"(\w+):\s+(\d+)\s+(\S+)\s+(-?\d+)\.\s+(-?\d+)\.\s+(-?\d+)", line)
            if not iface_match:
                continue

            iface_name = iface_match.group(1)
            status = int(iface_match.group(2))
            link_quality = safe_float(iface_match.group(3))
            signal_level = safe_float(iface_match.group(4))
            noise_level = safe_float(iface_match.group(5))

            if iface_name != self.interface:
                continue

            ap = APInfo(
                ssid="(connected)",
                bssid="",
                rssi=signal_level,
                noise=noise_level,
                quality=link_quality,
                interface=self.interface,
                mode="Managed",
            )
            aps.append(ap)

        return aps

    def _scan_linux_iwlist(self) -> ScanResult:
        """Scan using 'iwlist <iface> scanning' (legacy method).

        Returns:
            ScanResult with detected APs.
        """
        code, stdout, stderr = run_command(
            ["iwlist", self.interface, "scanning"],
            timeout=self.scan_timeout,
        )
        if code != 0:
            return ScanResult(
                interface=self.interface,
                success=False,
                error=f"iwlist scan failed: {stderr.strip()}",
            )

        aps = self._parse_iwlist_output(stdout)
        return ScanResult(interface=self.interface, aps=aps)

    def _parse_iwlist_output(self, output: str) -> List[APInfo]:
        """Parse output from 'iwlist <iface> scanning'.

        Args:
            output: Raw output from the iwlist command.

        Returns:
            List of APInfo objects.
        """
        aps: List[APInfo] = []
        # Split into cell sections
        cell_sections = re.split(r"(?m)^\s*(Cell \d+)", output)

        for i in range(1, len(cell_sections), 2):
            header = cell_sections[i]
            body = cell_sections[i + 1] if i + 1 < len(cell_sections) else ""

            ap = APInfo(interface=self.interface)

            # Address
            addr_match = re.search(r"Address:\s*([0-9a-fA-F:]+)", body)
            if addr_match:
                ap.bssid = addr_match.group(1).upper()

            # ESSID (SSID)
            essid_match = re.search(r'ESSID:"([^"]*)"', body)
            if essid_match:
                ap.ssid = essid_match.group(1)

            # Signal level
            signal_match = re.search(
                r"Signal level[=:]\s*(-?\d+)\s*dBm", body
            )
            if signal_match:
                ap.rssi = float(signal_match.group(1))

            # Noise level
            noise_match = re.search(
                r"Noise level[=:]\s*(-?\d+)\s*dBm", body
            )
            if noise_match:
                ap.noise = float(noise_match.group(1))

            # Channel
            channel_match = re.search(r"Channel[=:]\s*(\d+)", body)
            if channel_match:
                ap.channel = int(channel_match.group(1))

            # Frequency
            freq_match = re.search(r"Frequency[=:]\s*([\d.]+)\s*GHz", body)
            if freq_match:
                ap.frequency = int(float(freq_match.group(1)) * 1000)

            # Security
            if "WPA2" in body:
                ap.security = "WPA2"
            elif "WPA" in body:
                ap.security = "WPA"
            elif "WEP" in body:
                ap.security = "WEP"
            else:
                ap.security = "OPEN"

            # Mode
            mode_match = re.search(r"Mode[=:]\s*(\w+)", body)
            if mode_match:
                ap.mode = mode_match.group(1)

            aps.append(ap)

        return aps

    # ------------------------------------------------------------------
    # macOS Scanning
    # ------------------------------------------------------------------

    def _scan_macos(self) -> ScanResult:
        """Scan for WiFi access points on macOS.

        Tries multiple methods:
        1. 'airport -s' - Fast and detailed.
        2. system_profiler SPNetworkDataType - Slow but reliable.

        Returns:
            ScanResult with detected APs.
        """
        # Method 1: airport command
        result = self._scan_macos_airport()
        if result.success and result.aps:
            return result

        # Method 2: system_profiler
        result = self._scan_macos_system_profiler()
        if result.success and result.aps:
            return result

        return ScanResult(
            interface=self.interface,
            success=False,
            error="All macOS scan methods failed",
        )

    def _scan_macos_airport(self) -> ScanResult:
        """Scan using the macOS airport utility.

        Returns:
            ScanResult with detected APs.
        """
        airport_path = (
            "/System/Library/PrivateFrameworks/Apple80211.framework"
            "/Versions/Current/Resources/airport"
        )
        code, stdout, stderr = run_command(
            [airport_path, "-s"],
            timeout=self.scan_timeout,
        )
        if code != 0:
            return ScanResult(
                interface=self.interface,
                success=False,
                error=f"airport scan failed: {stderr.strip()}",
            )

        aps = self._parse_airport_output(stdout)
        return ScanResult(interface=self.interface, aps=aps)

    def _parse_airport_output(self, output: str) -> List[APInfo]:
        """Parse output from the airport command.

        Format:
                            SSID BSSID             RSSI信道  CCB  安全
            MyNetwork        aa:bb:cc:dd:ee:ff -62  6       WPA2(PSK)

        Args:
            output: Raw output from the airport command.

        Returns:
            List of APInfo objects.
        """
        aps: List[APInfo] = []
        lines = output.strip().split("\n")
        if len(lines) < 2:
            return aps

        # Skip header line
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue

            ap = APInfo(interface=self.interface)

            # SSID is everything before the BSSID (MAC address)
            bssid_idx = -1
            for idx, part in enumerate(parts):
                if re.match(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$", part):
                    bssid_idx = idx
                    break

            if bssid_idx > 0:
                ap.ssid = " ".join(parts[:bssid_idx])
                ap.bssid = parts[bssid_idx].upper()
                remaining = parts[bssid_idx + 1:]
            else:
                continue

            if len(remaining) >= 1:
                ap.rssi = safe_float(remaining[0])
            if len(remaining) >= 2:
                ap.channel = safe_int(remaining[1])

            # Security
            security_parts = " ".join(remaining[3:]) if len(remaining) > 3 else ""
            if "WPA3" in security_parts:
                ap.security = "WPA3"
            elif "WPA2" in security_parts:
                ap.security = "WPA2"
            elif "WPA" in security_parts:
                ap.security = "WPA"
            elif "WEP" in security_parts:
                ap.security = "WEP"
            else:
                ap.security = "OPEN"

            aps.append(ap)

        return aps

    def _scan_macos_system_profiler(self) -> ScanResult:
        """Scan using system_profiler SPNetworkDataType.

        Returns:
            ScanResult with detected APs.
        """
        code, stdout, stderr = run_command(
            ["system_profiler", "SPNetworkDataType"],
            timeout=self.scan_timeout * 2,  # This command is slow
        )
        if code != 0:
            return ScanResult(
                interface=self.interface,
                success=False,
                error=f"system_profiler failed: {stderr.strip()}",
            )

        aps = self._parse_system_profiler_output(stdout)
        return ScanResult(interface=self.interface, aps=aps)

    def _parse_system_profiler_output(self, output: str) -> List[APInfo]:
        """Parse system_profiler SPNetworkDataType output for WiFi info.

        Args:
            output: Raw output from system_profiler.

        Returns:
            List of APInfo objects.
        """
        aps: List[APInfo] = []

        # Find the WiFi section
        wifi_section = ""
        in_wifi = False
        for line in output.split("\n"):
            if "Wi-Fi" in line or "AirPort" in line:
                in_wifi = True
            if in_wifi:
                wifi_section += line + "\n"
            if in_wifi and line.strip() == "" and len(wifi_section) > 100:
                break

        if not wifi_section:
            return aps

        # Parse currently connected network
        ap = APInfo(interface=self.interface)

        ssid_match = re.search(r"Current Network[^\n]*:\s*(.+)", wifi_section)
        if ssid_match:
            ap.ssid = ssid_match.group(1).strip()

        bssid_match = re.search(r"BSSID[^\n]*:\s*([0-9a-fA-F:]+)", wifi_section)
        if bssid_match:
            ap.bssid = bssid_match.group(1).upper()

        signal_match = re.search(
            r"Signal Strength[^\n]*:\s*(-?\d+)", wifi_section
        )
        if signal_match:
            ap.rssi = float(signal_match.group(1))

        noise_match = re.search(r"Noise[^\n]*:\s*(-?\d+)", wifi_section)
        if noise_match:
            ap.noise = float(noise_match.group(1))

        channel_match = re.search(r"Channel[^\n]*:\s*(\d+)", wifi_section)
        if channel_match:
            ap.channel = int(channel_match.group(1))

        if ap.ssid or ap.bssid:
            aps.append(ap)

        return aps

    # ------------------------------------------------------------------
    # Windows Scanning
    # ------------------------------------------------------------------

    def _scan_windows(self) -> ScanResult:
        """Scan for WiFi access points on Windows.

        Uses 'netsh wlan show networks mode=bssid' for all visible
        networks, and 'netsh wlan show interfaces' for the currently
        connected interface details.

        Returns:
            ScanResult with detected APs.
        """
        result = self._scan_windows_netsh()
        if result.success and result.aps:
            return result

        return ScanResult(
            interface=self.interface,
            success=False,
            error="Windows netsh scan failed",
        )

    def _scan_windows_netsh(self) -> ScanResult:
        """Scan using 'netsh wlan show networks mode=bssid'.

        Returns:
            ScanResult with detected APs.
        """
        code, stdout, stderr = run_command(
            ["netsh", "wlan", "show", "networks", "mode=bssid"],
            timeout=self.scan_timeout,
            shell=True,
        )
        if code != 0:
            return ScanResult(
                interface=self.interface,
                success=False,
                error=f"netsh failed: {stderr.strip()}",
            )

        aps = self._parse_netsh_output(stdout)
        return ScanResult(interface=self.interface, aps=aps)

    def _parse_netsh_output(self, output: str) -> List[APInfo]:
        """Parse netsh wlan show networks output.

        Format:
            SSID 1 : MyNetwork
                Network type             : Infrastructure
                Authentication           : WPA2-Personal
                BSSID                   : aa:bb:cc:dd:ee:ff
                Signal                  : 82%
                Radio type              : 802.11n
                Channel                 : 6

        Args:
            output: Raw output from netsh.

        Returns:
            List of APInfo objects.
        """
        aps: List[APInfo] = []

        # Split into network blocks by SSID headers
        ssid_blocks = re.split(r"(?m)^(SSID \d+)\s*:", output)

        for i in range(1, len(ssid_blocks), 2):
            ssid_header = ssid_blocks[i]
            block = ssid_blocks[i + 1] if i + 1 < len(ssid_blocks) else ""

            # Get SSID name from the next line after the header
            ssid_name_match = re.match(
                r"\s*(.+?)(?:\s*$)", block.split("\n")[0] if block.split("\n") else ""
            )
            ssid_name = ""
            if ssid_name_match:
                ssid_name = ssid_name_match.group(1).strip()

            # Parse BSSIDs within this network block
            bssid_sections = re.split(r"(?m)^\s*BSSID\s+(\d+)\s*:", block)

            for j in range(1, len(bssid_sections), 2):
                bssid_block = bssid_sections[j + 1] if j + 1 < len(bssid_sections) else ""

                ap = APInfo(interface=self.interface)
                ap.ssid = ssid_name

                # BSSID
                bssid_match = re.search(r"BSSID\s*:\s*([0-9a-fA-F:-]+)", bssid_block)
                if bssid_match:
                    ap.bssid = bssid_match.group(1).replace("-", ":").upper()

                # Signal (percentage)
                signal_match = re.search(r"Signal\s*:\s*(\d+)%", bssid_block)
                if signal_match:
                    pct = int(signal_match.group(1))
                    ap.quality = float(pct)
                    # Convert percentage to approximate dBm
                    ap.rssi = -(100 - pct)

                # Channel
                channel_match = re.search(r"Channel\s*:\s*(\d+)", bssid_block)
                if channel_match:
                    ap.channel = int(channel_match.group(1))

                # Radio type / frequency
                radio_match = re.search(r"Radio type\s*:\s*(.+)", bssid_block)
                if radio_match:
                    radio = radio_match.group(1).strip()
                    if "5" in radio:
                        ap.band = "5GHz"
                        ap.frequency = 5000
                    elif "2.4" in radio or "802.11b" in radio or "802.11g" in radio or "802.11n" in radio:
                        ap.band = "2.4GHz"
                        ap.frequency = 2412

                # Authentication / Security
                auth_match = re.search(
                    r"Authentication\s*:\s*(.+)", bssid_block
                )
                if auth_match:
                    ap.security = auth_match.group(1).strip()

                # Network type / Mode
                type_match = re.search(r"Network type\s*:\s*(.+)", bssid_block)
                if type_match:
                    ap.mode = type_match.group(1).strip()

                aps.append(ap)

        return aps

    # ------------------------------------------------------------------
    # Continuous Monitoring
    # ------------------------------------------------------------------

    def start_monitoring(
        self,
        callback: Optional[ScanCallback] = None,
    ) -> None:
        """Start continuous monitoring mode.

        Blocks the calling thread and repeatedly performs WiFi scans,
        invoking the callback with each scan result.

        Args:
            callback: Function to call with each ScanResult.
                     If None, prints results to stdout.
        """
        self._monitoring = True
        log_info(
            f"Starting WiFi monitoring on {self.interface} "
            f"(interval: {self.poll_interval}s)"
        )

        try:
            while self._monitoring:
                result = self.scan()
                if callback:
                    callback(result)
                else:
                    self._default_callback(result)
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            log_info("Monitoring stopped by user")
        finally:
            self._monitoring = False

    def stop_monitoring(self) -> None:
        """Stop the continuous monitoring loop."""
        self._monitoring = False

    def add_callback(self, callback: ScanCallback) -> None:
        """Register a callback for monitoring events.

        Args:
            callback: Function to call with each ScanResult.
        """
        self._callbacks.append(callback)

    def remove_callback(self, callback: ScanCallback) -> None:
        """Unregister a monitoring callback.

        Args:
            callback: The callback function to remove.
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _default_callback(self, result: ScanResult) -> None:
        """Default callback that prints scan results to stdout.

        Args:
            result: The scan result to display.
        """
        if not result.success:
            log_error(f"Scan failed: {result.error}")
            return

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'=' * 60}")
        print(f"  WiFi Scan - {ts} | {len(result.aps)} APs detected")
        print(f"{'=' * 60}")

        for ap in sorted(result.aps, key=lambda x: x.rssi, reverse=True):
            ssid_display = ap.ssid if ap.ssid else "(hidden)"
            print(
                f"  {ssid_display:<25} {ap.bssid:>17} "
                f"RSSI: {ap.rssi:>6.0f} dBm  "
                f"Ch: {ap.channel:>3}  "
                f"Q: {ap.quality:>5.1f}%"
            )

        print(f"{'=' * 60}")

    # ------------------------------------------------------------------
    # Utility Methods
    # ------------------------------------------------------------------

    def get_interfaces(self) -> List[str]:
        """List available wireless network interfaces.

        Returns:
            List of wireless interface names.
        """
        plat = get_platform()
        if plat == "linux":
            return self._get_linux_interfaces()
        elif plat == "darwin":
            return ["en0", "en1"]
        elif plat == "windows":
            return ["Wi-Fi"]
        return []

    def _get_linux_interfaces(self) -> List[str]:
        """Get wireless interfaces on Linux from /proc/net/wireless.

        Returns:
            List of wireless interface names.
        """
        interfaces: List[str] = []
        try:
            with open("/proc/net/wireless", "r") as f:
                for line in f:
                    line = line.strip()
                    if ":" in line and not line.startswith("Inter"):
                        iface = line.split(":")[0].strip()
                        if iface:
                            interfaces.append(iface)
        except (OSError, IOError):
            pass

        # Also check /sys/class/net for wireless devices
        if not interfaces:
            try:
                net_dir = "/sys/class/net"
                if os.path.isdir(net_dir):
                    for entry in os.listdir(net_dir):
                        wireless_dir = os.path.join(
                            net_dir, entry, "wireless"
                        )
                        if os.path.exists(wireless_dir):
                            interfaces.append(entry)
            except OSError:
                pass

        return interfaces

    def __repr__(self) -> str:
        return (
            f"WiFiScanner(interface={self.interface!r}, "
            f"poll_interval={self.poll_interval}s)"
        )
