"""
WiFiSense-CLI Event Rule Engine

Provides a rule-based event triggering system for WiFi signal analysis.
Supports threshold conditions, change rate conditions, AP count conditions,
time window aggregation, and combined logic (AND/OR/NOT). Built-in
actions include shell command execution, log recording, and webhook
notifications (ntfy.sh, shoutrrr-compatible endpoints).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .utils import (
    log_debug,
    log_error,
    log_info,
    log_warning,
    render_template,
    safe_float,
    safe_int,
    timestamp,
)


# ---------------------------------------------------------------------------
# Enums and Constants
# ---------------------------------------------------------------------------

class ConditionType(Enum):
    """Types of event conditions."""
    THRESHOLD = "threshold"
    CHANGE_RATE = "change_rate"
    AP_COUNT = "ap_count"
    ANOMALY = "anomaly"
    TREND = "trend"
    FINGERPRINT = "fingerprint"
    TIME_WINDOW = "time_window"


class ActionType(Enum):
    """Types of event actions."""
    SHELL = "shell"
    LOG = "log"
    WEBHOOK = "webhook"
    NTFY = "ntfy"
    SCRIPT = "script"
    PRINT = "print"


class LogicOperator(Enum):
    """Logic operators for combining conditions."""
    AND = "AND"
    OR = "OR"
    NOT = "NOT"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class Condition:
    """A single condition to evaluate against analysis data.

    Attributes:
        condition_type: The type of condition.
        field: The data field to check (e.g., 'rssi', 'quality').
        operator: Comparison operator ('below', 'above', 'equals',
                  'not_equals', 'in_range').
        value: The threshold value to compare against.
        secondary_value: Second value for 'in_range' operator.
    """

    condition_type: ConditionType = ConditionType.THRESHOLD
    field: str = "rssi"
    operator: str = "below"
    value: Any = None
    secondary_value: Any = None

    def evaluate(self, context: Dict[str, Any]) -> bool:
        """Evaluate this condition against the provided context.

        Args:
            context: Dictionary of field names to values.

        Returns:
            True if the condition is satisfied.
        """
        field_value = context.get(self.field)
        if field_value is None:
            return False

        threshold = safe_float(self.value) if isinstance(self.value, (int, float, str)) else self.value

        if self.operator == "below":
            return safe_float(field_value) < threshold
        elif self.operator == "above":
            return safe_float(field_value) > threshold
        elif self.operator == "equals":
            return field_value == threshold
        elif self.operator == "not_equals":
            return field_value != threshold
        elif self.operator == "in_range":
            low = threshold
            high = safe_float(self.secondary_value)
            return low <= safe_float(field_value) <= high
        elif self.operator == "contains":
            return str(threshold) in str(field_value)
        elif self.operator == "matches":
            import re
            return bool(re.search(str(threshold), str(field_value)))

        return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.condition_type.value,
            "field": self.field,
            "operator": self.operator,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Condition:
        """Create a condition from a dictionary."""
        return cls(
            condition_type=ConditionType(data.get("type", "threshold")),
            field=data.get("field", "rssi"),
            operator=data.get("operator", "below"),
            value=data.get("value"),
            secondary_value=data.get("secondary_value"),
        )


@dataclass
class Action:
    """An action to execute when a rule is triggered.

    Attributes:
        action_type: The type of action.
        command: Shell command to execute (for SHELL type).
        url: URL for webhook/ntfy notification.
        method: HTTP method for webhook.
        body: Template body for webhook/ntfy.
        headers: HTTP headers for webhook.
        log_file: File path for LOG action.
        log_message: Template message for LOG action.
        script: Script path for SCRIPT action.
        message: Message template for PRINT action.
    """

    action_type: ActionType = ActionType.LOG
    command: str = ""
    url: str = ""
    method: str = "POST"
    body: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    log_file: str = ""
    log_message: str = ""
    script: str = ""
    message: str = ""

    def execute(self, context: Dict[str, Any]) -> bool:
        """Execute this action with the given context.

        Args:
            context: Dictionary of field names to values for template rendering.

        Returns:
            True if the action executed successfully.
        """
        try:
            if self.action_type == ActionType.SHELL:
                return self._execute_shell(context)
            elif self.action_type == ActionType.LOG:
                return self._execute_log(context)
            elif self.action_type == ActionType.WEBHOOK:
                return self._execute_webhook(context)
            elif self.action_type == ActionType.NTFY:
                return self._execute_ntfy(context)
            elif self.action_type == ActionType.SCRIPT:
                return self._execute_script(context)
            elif self.action_type == ActionType.PRINT:
                return self._execute_print(context)
            else:
                log_warning(f"Unknown action type: {self.action_type}")
                return False
        except Exception as e:
            log_error(f"Action execution failed: {e}")
            return False

    def _execute_shell(self, context: Dict[str, Any]) -> bool:
        """Execute a shell command."""
        cmd = render_template(self.command, context)
        log_debug(f"Executing shell: {cmd}")
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                log_warning(
                    f"Shell command returned {result.returncode}: "
                    f"{result.stderr.strip()}"
                )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            log_error("Shell command timed out")
            return False
        except Exception as e:
            log_error(f"Shell execution error: {e}")
            return False

    def _execute_log(self, context: Dict[str, Any]) -> bool:
        """Write a log entry to a file."""
        message = render_template(self.log_message, context)
        log_file = render_template(self.log_file, context)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] {message}\n"

        try:
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(entry)
            return True
        except IOError as e:
            log_error(f"Failed to write log: {e}")
            return False

    def _execute_webhook(self, context: Dict[str, Any]) -> bool:
        """Send a webhook HTTP request."""
        url = render_template(self.url, context)
        body = render_template(self.body, context)
        method = self.method.upper()

        log_debug(f"Sending webhook {method} to {url}")

        try:
            data = body.encode("utf-8") if body else None
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Content-Type", "text/plain")
            for key, value in self.headers.items():
                req.add_header(
                    key, render_template(value, context)
                )

            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status < 400:
                    log_debug(f"Webhook response: {resp.status}")
                    return True
                else:
                    log_warning(f"Webhook returned status {resp.status}")
                    return False
        except urllib.error.URLError as e:
            log_error(f"Webhook request failed: {e}")
            return False
        except Exception as e:
            log_error(f"Webhook error: {e}")
            return False

    def _execute_ntfy(self, context: Dict[str, Any]) -> bool:
        """Send a notification via ntfy.sh."""
        url = render_template(self.url, context)
        message = render_template(self.body, context)
        title = render_template(
            context.get("title", "WiFiSense Alert"), context
        )

        log_debug(f"Sending ntfy notification to {url}")

        try:
            data = message.encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "text/plain")
            req.add_header("Title", title)
            req.add_header("Priority", "default")
            req.add_header("Tags", "wifi")

            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 400
        except Exception as e:
            log_error(f"ntfy notification failed: {e}")
            return False

    def _execute_script(self, context: Dict[str, Any]) -> bool:
        """Execute a script file."""
        script_path = render_template(self.script, context)
        log_debug(f"Executing script: {script_path}")

        if not os.path.isfile(script_path):
            log_error(f"Script not found: {script_path}")
            return False

        try:
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, **{f"WS_{k.upper()}": str(v) for k, v in context.items()}},
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            log_error("Script execution timed out")
            return False
        except Exception as e:
            log_error(f"Script execution error: {e}")
            return False

    def _execute_print(self, context: Dict[str, Any]) -> bool:
        """Print a message to stdout."""
        message = render_template(self.message, context)
        print(f"[EVENT] {message}")
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        d = {"type": self.action_type.value}
        if self.command:
            d["command"] = self.command
        if self.url:
            d["url"] = self.url
        if self.method != "POST":
            d["method"] = self.method
        if self.body:
            d["body"] = self.body
        if self.headers:
            d["headers"] = self.headers
        if self.log_file:
            d["log_file"] = self.log_file
        if self.log_message:
            d["log_message"] = self.log_message
        if self.script:
            d["script"] = self.script
        if self.message:
            d["message"] = self.message
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Action:
        """Create an action from a dictionary."""
        return cls(
            action_type=ActionType(data.get("type", "log")),
            command=data.get("command", ""),
            url=data.get("url", ""),
            method=data.get("method", "POST"),
            body=data.get("body", ""),
            headers=data.get("headers", {}),
            log_file=data.get("log_file", ""),
            log_message=data.get("log_message", ""),
            script=data.get("script", ""),
            message=data.get("message", ""),
        )


@dataclass
class Rule:
    """An event rule consisting of conditions and actions.

    Attributes:
        name: Unique rule name.
        description: Human-readable description.
        enabled: Whether the rule is active.
        conditions: List of conditions (combined with AND by default).
        logic: Logic operator for combining conditions.
        actions: List of actions to execute when triggered.
        cooldown: Minimum seconds between triggers.
        last_triggered: Timestamp of last trigger.
        trigger_count: Total number of times triggered.
    """

    name: str = ""
    description: str = ""
    enabled: bool = True
    conditions: List[Condition] = field(default_factory=list)
    logic: LogicOperator = LogicOperator.AND
    actions: List[Action] = field(default_factory=list)
    cooldown: float = 30.0
    last_triggered: float = 0.0
    trigger_count: int = 0

    def evaluate(self, context: Dict[str, Any]) -> bool:
        """Evaluate all conditions against the context.

        Args:
            context: Dictionary of field names to values.

        Returns:
            True if all conditions are satisfied.
        """
        if not self.enabled or not self.conditions:
            return False

        # Check cooldown
        import time as _time
        now = _time.monotonic()
        if now - self.last_triggered < self.cooldown:
            return False

        if self.logic == LogicOperator.AND:
            return all(c.evaluate(context) for c in self.conditions)
        elif self.logic == LogicOperator.OR:
            return any(c.evaluate(context) for c in self.conditions)
        elif self.logic == LogicOperator.NOT:
            return not any(c.evaluate(context) for c in self.conditions)

        return False

    def trigger(self, context: Dict[str, Any]) -> bool:
        """Execute all actions for this rule.

        Args:
            context: Dictionary for template rendering.

        Returns:
            True if all actions succeeded.
        """
        import time as _time
        self.last_triggered = _time.monotonic()
        self.trigger_count += 1

        log_info(f"Rule '{self.name}' triggered (count: {self.trigger_count})")

        all_success = True
        for action in self.actions:
            if not action.execute(context):
                all_success = False

        return all_success

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "conditions": [c.to_dict() for c in self.conditions],
            "logic": self.logic.value,
            "actions": [a.to_dict() for a in self.actions],
            "cooldown": self.cooldown,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Rule:
        """Create a rule from a dictionary."""
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            conditions=[
                Condition.from_dict(c) for c in data.get("conditions", [])
            ],
            logic=LogicOperator(data.get("logic", "AND")),
            actions=[Action.from_dict(a) for a in data.get("actions", [])],
            cooldown=safe_float(data.get("cooldown", 30.0)),
        )


@dataclass
class EventRecord:
    """Record of a triggered event.

    Attributes:
        timestamp: When the event was triggered.
        rule_name: Name of the rule that triggered.
        context: The data context at trigger time.
        actions_executed: List of action types executed.
        success: Whether all actions succeeded.
    """

    timestamp: str = ""
    rule_name: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    actions_executed: List[str] = field(default_factory=list)
    success: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "rule_name": self.rule_name,
            "context": self.context,
            "actions_executed": self.actions_executed,
            "success": self.success,
        }


# ---------------------------------------------------------------------------
# Event Engine
# ---------------------------------------------------------------------------

class EventEngine:
    """Rule-based event engine for WiFi signal analysis.

    Manages a collection of rules, evaluates them against incoming
    analysis data, and triggers actions when conditions are met.

    Attributes:
        rules: List of registered rules.
        enabled: Whether the engine is active.
        event_log: History of triggered events.
        max_log_size: Maximum number of event records to keep.
        max_events_per_minute: Rate limiting for event triggers.
    """

    def __init__(
        self,
        enabled: bool = True,
        max_log_size: int = 1000,
        max_events_per_minute: int = 10,
        rules_file: str = "rules.json",
    ) -> None:
        """Initialize the event engine.

        Args:
            enabled: Whether the engine is active.
            max_log_size: Maximum event log entries.
            max_events_per_minute: Rate limit for triggers.
            rules_file: Path to the rules JSON file.
        """
        self.rules: List[Rule] = []
        self.enabled = enabled
        self.event_log: List[EventRecord] = []
        self.max_log_size = max_log_size
        self.max_events_per_minute = max_events_per_minute
        self.rules_file = rules_file

        # Rate limiting
        self._trigger_times: List[float] = []

        # Load rules from file if it exists
        self.load_rules(rules_file)

    def add_rule(self, rule: Rule) -> None:
        """Add a rule to the engine.

        Args:
            rule: The rule to add.
        """
        # Check for duplicate names
        for existing in self.rules:
            if existing.name == rule.name:
                log_warning(f"Rule '{rule.name}' already exists, replacing")
                self.rules.remove(existing)
                break
        self.rules.append(rule)
        log_debug(f"Added rule: {rule.name}")

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name.

        Args:
            name: Name of the rule to remove.

        Returns:
            True if the rule was found and removed.
        """
        for i, rule in enumerate(self.rules):
            if rule.name == name:
                self.rules.pop(i)
                log_debug(f"Removed rule: {name}")
                return True
        return False

    def get_rule(self, name: str) -> Optional[Rule]:
        """Get a rule by name.

        Args:
            name: Name of the rule.

        Returns:
            The Rule object, or None if not found.
        """
        for rule in self.rules:
            if rule.name == name:
                return rule
        return None

    def enable_rule(self, name: str) -> bool:
        """Enable a rule by name.

        Args:
            name: Name of the rule to enable.

        Returns:
            True if the rule was found.
        """
        rule = self.get_rule(name)
        if rule:
            rule.enabled = True
            return True
        return False

    def disable_rule(self, name: str) -> bool:
        """Disable a rule by name.

        Args:
            name: Name of the rule to disable.

        Returns:
            True if the rule was found.
        """
        rule = self.get_rule(name)
        if rule:
            rule.enabled = False
            return True
        return False

    def evaluate(self, analysis_results: List[Any]) -> List[EventRecord]:
        """Evaluate all rules against analysis results.

        Args:
            analysis_results: List of AnalysisResult objects or dicts.

        Returns:
            List of EventRecord objects for triggered rules.
        """
        if not self.enabled:
            return []

        triggered: List[EventRecord] = []

        for result in analysis_results:
            # Convert to dict if needed
            if hasattr(result, "to_dict"):
                context = result.to_dict()
            elif isinstance(result, dict):
                context = result
            else:
                continue

            for rule in self.rules:
                if not rule.enabled:
                    continue

                if rule.evaluate(context):
                    # Rate limiting check
                    if not self._check_rate_limit():
                        log_warning("Event rate limit reached, skipping trigger")
                        continue

                    success = rule.trigger(context)
                    record = EventRecord(
                        timestamp=timestamp(),
                        rule_name=rule.name,
                        context=context,
                        actions_executed=[
                            a.action_type.value for a in rule.actions
                        ],
                        success=success,
                    )
                    triggered.append(record)
                    self.event_log.append(record)

        # Trim event log
        if len(self.event_log) > self.max_log_size:
            self.event_log = self.event_log[-self.max_log_size:]

        return triggered

    def _check_rate_limit(self) -> bool:
        """Check if event triggers are within rate limits.

        Returns:
            True if under the rate limit.
        """
        import time as _time
        now = _time.monotonic()
        one_minute_ago = now - 60.0

        # Clean old entries
        self._trigger_times = [
            t for t in self._trigger_times if t > one_minute_ago
        ]

        if len(self._trigger_times) >= self.max_events_per_minute:
            return False

        self._trigger_times.append(now)
        return True

    # ------------------------------------------------------------------
    # Rule Persistence
    # ------------------------------------------------------------------

    def load_rules(self, path: str) -> bool:
        """Load rules from a JSON file.

        Args:
            path: Path to the rules JSON file.

        Returns:
            True if rules were loaded successfully.
        """
        if not os.path.isfile(path):
            log_debug(f"Rules file not found: {path}")
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            rules_data = data.get("rules", [])
            for rule_data in rules_data:
                rule = Rule.from_dict(rule_data)
                self.add_rule(rule)

            log_info(f"Loaded {len(rules_data)} rules from {path}")
            return True
        except (json.JSONDecodeError, IOError) as e:
            log_error(f"Failed to load rules: {e}")
            return False

    def save_rules(self, path: Optional[str] = None) -> bool:
        """Save current rules to a JSON file.

        Args:
            path: Path to save to. If None, uses rules_file.

        Returns:
            True if saved successfully.
        """
        save_path = path or self.rules_file
        try:
            os.makedirs(
                os.path.dirname(save_path) if os.path.dirname(save_path) else ".",
                exist_ok=True,
            )
            data = {
                "rules": [r.to_dict() for r in self.rules],
            }
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            log_info(f"Saved {len(self.rules)} rules to {save_path}")
            return True
        except IOError as e:
            log_error(f"Failed to save rules: {e}")
            return False

    # ------------------------------------------------------------------
    # Built-in Rule Templates
    # ------------------------------------------------------------------

    @staticmethod
    def create_rssi_threshold_rule(
        name: str = "rssi_drop_alert",
        threshold: float = -75,
        action_type: str = "log",
        **action_kwargs: Any,
    ) -> Rule:
        """Create a rule that triggers when RSSI drops below a threshold.

        Args:
            name: Rule name.
            threshold: RSSI threshold in dBm.
            action_type: Type of action ('log', 'webhook', 'ntfy', 'print').
            **action_kwargs: Additional action parameters.

        Returns:
            Configured Rule object.
        """
        condition = Condition(
            condition_type=ConditionType.THRESHOLD,
            field="rssi",
            operator="below",
            value=threshold,
        )

        if action_type == "webhook":
            action = Action(
                action_type=ActionType.WEBHOOK,
                url=action_kwargs.get("url", ""),
                body=action_kwargs.get(
                    "body",
                    "WiFi signal degraded: {{rssi}} dBm on {{ssid}}",
                ),
            )
        elif action_type == "ntfy":
            action = Action(
                action_type=ActionType.NTFY,
                url=action_kwargs.get("url", "https://ntfy.sh/mychannel"),
                body=action_kwargs.get(
                    "body",
                    "WiFi signal degraded: {{rssi}} dBm on {{ssid}}",
                ),
            )
        elif action_type == "print":
            action = Action(
                action_type=ActionType.PRINT,
                message="ALERT: WiFi signal on {{ssid}} is {{rssi}} dBm (below {{value}} dBm)",
            )
        else:
            action = Action(
                action_type=ActionType.LOG,
                log_file=action_kwargs.get("log_file", "events.log"),
                log_message=action_kwargs.get(
                    "log_message",
                    "RSSI drop: {{ssid}} {{rssi}} dBm",
                ),
            )

        return Rule(
            name=name,
            description=f"Alert when RSSI drops below {threshold} dBm",
            conditions=[condition],
            actions=[action],
        )

    @staticmethod
    def create_anomaly_rule(
        name: str = "anomaly_alert",
        action_type: str = "log",
        **action_kwargs: Any,
    ) -> Rule:
        """Create a rule that triggers on anomaly detection.

        Args:
            name: Rule name.
            action_type: Type of action.
            **action_kwargs: Additional action parameters.

        Returns:
            Configured Rule object.
        """
        condition = Condition(
            condition_type=ConditionType.ANOMALY,
            field="is_anomaly",
            operator="equals",
            value=True,
        )

        action = Action(
            action_type=ActionType(action_type),
            log_file=action_kwargs.get("log_file", "events.log"),
            log_message=action_kwargs.get(
                "log_message",
                "Anomaly detected: {{ssid}} RSSI={{rssi}} Z={{z_score}}",
            ),
            message=action_kwargs.get(
                "message",
                "ANOMALY: {{ssid}} RSSI={{rssi}} dBm Z-score={{z_score}}",
            ),
        )

        return Rule(
            name=name,
            description="Alert when signal anomaly is detected",
            conditions=[condition],
            actions=[action],
        )

    @staticmethod
    def create_ap_count_rule(
        name: str = "ap_count_change",
        min_aps: int = 1,
        max_aps: int = 20,
        action_type: str = "log",
        **action_kwargs: Any,
    ) -> Rule:
        """Create a rule that triggers when AP count changes significantly.

        Args:
            name: Rule name.
            min_aps: Minimum expected AP count.
            max_aps: Maximum expected AP count.
            action_type: Type of action.
            **action_kwargs: Additional action parameters.

        Returns:
            Configured Rule object.
        """
        condition = Condition(
            condition_type=ConditionType.AP_COUNT,
            field="ap_count",
            operator="in_range",
            value=min_aps,
            secondary_value=max_aps,
        )

        action = Action(
            action_type=ActionType(action_type),
            log_file=action_kwargs.get("log_file", "events.log"),
            log_message="AP count changed: {{ap_count}} APs detected",
            message="AP count: {{ap_count}} APs visible",
        )

        return Rule(
            name=name,
            description=f"Alert when AP count is outside {min_aps}-{max_aps}",
            conditions=[condition],
            actions=[action],
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the event engine state.

        Returns:
            Dictionary with summary information.
        """
        return {
            "enabled": self.enabled,
            "total_rules": len(self.rules),
            "enabled_rules": sum(1 for r in self.rules if r.enabled),
            "total_events": len(self.event_log),
            "rules": [
                {
                    "name": r.name,
                    "enabled": r.enabled,
                    "trigger_count": r.trigger_count,
                    "conditions": len(r.conditions),
                    "actions": len(r.actions),
                }
                for r in self.rules
            ],
        }

    def get_event_log(self, limit: int = 50) -> List[EventRecord]:
        """Get recent event records.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of recent EventRecord objects.
        """
        return self.event_log[-limit:]

    def clear_event_log(self) -> None:
        """Clear all event records."""
        self.event_log.clear()

    def __repr__(self) -> str:
        return (
            f"EventEngine(rules={len(self.rules)}, "
            f"events={len(self.event_log)}, "
            f"enabled={self.enabled})"
        )
