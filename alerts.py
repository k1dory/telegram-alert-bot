"""
Alert management module.
Handles alert notifications, grouping, and cooldowns.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict
import structlog

from telegram import Bot
from telegram.constants import ParseMode

from config import settings, AlertLevel
from dashboard import DashboardRenderer, Alert

logger = structlog.get_logger()


@dataclass
class AlertRecord:
    """Record of an alert."""
    id: str
    level: AlertLevel
    message: str
    source: str  # server/container name
    timestamp: datetime
    acknowledged: bool = False
    notification_sent: bool = False


@dataclass
class AlertGroup:
    """Group of similar alerts."""
    key: str  # e.g., "cpu_high:prod-api"
    alerts: list[AlertRecord] = field(default_factory=list)
    last_notification: Optional[datetime] = None
    count: int = 0


class AlertManager:
    """Manages alerts, notifications, and cooldowns."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.renderer = DashboardRenderer()

        # Alert storage
        self.alerts: dict[str, AlertRecord] = {}
        self.groups: dict[str, AlertGroup] = defaultdict(AlertGroup)

        # Cooldown tracking: alert_key -> last_notified
        self.cooldowns: dict[str, datetime] = {}

        # Configuration
        self.min_level = settings.alert_min_level
        self.cooldown_seconds = settings.alert_cooldown
        self.grouping_enabled = settings.alert_grouping

    def should_notify(self, alert: AlertRecord) -> bool:
        """Check if alert should trigger notification."""
        # Check minimum level
        level_order = {
            AlertLevel.INFO: 0,
            AlertLevel.WARNING: 1,
            AlertLevel.CRITICAL: 2
        }

        if level_order.get(alert.level, 0) < level_order.get(self.min_level, 0):
            return False

        # Check cooldown
        alert_key = f"{alert.level}:{alert.source}:{alert.message[:20]}"
        last_notified = self.cooldowns.get(alert_key)

        if last_notified:
            elapsed = (datetime.utcnow() - last_notified).total_seconds()
            if elapsed < self.cooldown_seconds:
                return False

        return True

    async def process_alert(self, alert: AlertRecord):
        """Process incoming alert."""
        self.alerts[alert.id] = alert

        if not self.should_notify(alert):
            logger.debug("Alert skipped (cooldown/level)", alert_id=alert.id)
            return

        if self.grouping_enabled:
            await self._process_grouped(alert)
        else:
            await self._send_notification(alert)

    async def _process_grouped(self, alert: AlertRecord):
        """Process alert with grouping."""
        # Create group key
        group_key = f"{alert.level}:{alert.source}"

        group = self.groups[group_key]
        group.key = group_key
        group.alerts.append(alert)
        group.count += 1

        # Check if we should send grouped notification
        should_send = False

        # Always send immediately for critical
        if alert.level == AlertLevel.CRITICAL:
            should_send = True

        # For warnings, batch for 30 seconds
        elif group.last_notification is None:
            should_send = True
        else:
            elapsed = (datetime.utcnow() - group.last_notification).total_seconds()
            if elapsed >= 30 and group.count >= 3:
                should_send = True

        if should_send:
            await self._send_grouped_notification(group)
            group.alerts = []
            group.count = 0
            group.last_notification = datetime.utcnow()

    async def _send_notification(self, alert: AlertRecord):
        """Send single alert notification."""
        alert_key = f"{alert.level}:{alert.source}:{alert.message[:20]}"
        self.cooldowns[alert_key] = datetime.utcnow()
        alert.notification_sent = True

        level_indicator = "!!" if alert.level == AlertLevel.CRITICAL else "i "

        text = self._render_alert(alert)

        for user_id in settings.allowed_user_ids:
            try:
                await self.bot.send_message(
                    chat_id=user_id,
                    text=f"```\n{text}\n```",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception as e:
                logger.error("Failed to send alert", user_id=user_id, error=str(e))

    async def _send_grouped_notification(self, group: AlertGroup):
        """Send grouped alert notification."""
        if not group.alerts:
            return

        # Use the most severe alert as the main one
        main_alert = max(group.alerts, key=lambda a: {
            AlertLevel.INFO: 0,
            AlertLevel.WARNING: 1,
            AlertLevel.CRITICAL: 2
        }.get(a.level, 0))

        text = self._render_grouped_alert(main_alert, len(group.alerts))

        for user_id in settings.allowed_user_ids:
            try:
                await self.bot.send_message(
                    chat_id=user_id,
                    text=f"```\n{text}\n```",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception as e:
                logger.error("Failed to send grouped alert", user_id=user_id, error=str(e))

        # Update cooldowns for all alerts in group
        for alert in group.alerts:
            alert_key = f"{alert.level}:{alert.source}:{alert.message[:20]}"
            self.cooldowns[alert_key] = datetime.utcnow()
            alert.notification_sent = True

    def _render_alert(self, alert: AlertRecord) -> str:
        """Render single alert."""
        level_str = "CRITICAL" if alert.level == AlertLevel.CRITICAL else "WARNING" if alert.level == AlertLevel.WARNING else "INFO"
        level_mark = "!!" if alert.level == AlertLevel.CRITICAL else "i "
        time_str = alert.timestamp.strftime("%H:%M:%S")

        r = self.renderer
        lines = [
            f"{r.TOP_LEFT}{r.HORIZONTAL * 40}{r.TOP_RIGHT}",
            f"{r.VERTICAL}  [{level_mark}] {level_str}  {time_str}          {r.VERTICAL}",
            f"{r.T_RIGHT}{r.HORIZONTAL * 40}{r.T_LEFT}",
            f"{r.VERTICAL}                                        {r.VERTICAL}",
            f"{r.VERTICAL}  {alert.message[:36]:<36}  {r.VERTICAL}",
            f"{r.VERTICAL}  Source: {alert.source[:27]:<27}  {r.VERTICAL}",
            f"{r.VERTICAL}                                        {r.VERTICAL}",
            f"{r.BOTTOM_LEFT}{r.HORIZONTAL * 40}{r.BOTTOM_RIGHT}",
        ]

        return "\n".join(lines)

    def _render_grouped_alert(self, main_alert: AlertRecord, count: int) -> str:
        """Render grouped alert."""
        level_str = "CRITICAL" if main_alert.level == AlertLevel.CRITICAL else "WARNING"
        level_mark = "!!" if main_alert.level == AlertLevel.CRITICAL else "i "
        time_str = main_alert.timestamp.strftime("%H:%M:%S")

        r = self.renderer
        lines = [
            f"{r.TOP_LEFT}{r.HORIZONTAL * 40}{r.TOP_RIGHT}",
            f"{r.VERTICAL}  [{level_mark}] {level_str} ({count} alerts)       {r.VERTICAL}",
            f"{r.T_RIGHT}{r.HORIZONTAL * 40}{r.T_LEFT}",
            f"{r.VERTICAL}                                        {r.VERTICAL}",
            f"{r.VERTICAL}  Latest: {main_alert.message[:28]:<28}  {r.VERTICAL}",
            f"{r.VERTICAL}  Source: {main_alert.source[:27]:<27}  {r.VERTICAL}",
            f"{r.VERTICAL}  Time: {time_str}                        {r.VERTICAL}",
            f"{r.VERTICAL}                                        {r.VERTICAL}",
            f"{r.BOTTOM_LEFT}{r.HORIZONTAL * 40}{r.BOTTOM_RIGHT}",
        ]

        return "\n".join(lines)

    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        if alert_id in self.alerts:
            self.alerts[alert_id].acknowledged = True
            return True
        return False

    def acknowledge_all(self):
        """Acknowledge all alerts."""
        for alert in self.alerts.values():
            alert.acknowledged = True

    def get_active_alerts(self) -> list[AlertRecord]:
        """Get all unacknowledged alerts."""
        return [a for a in self.alerts.values() if not a.acknowledged]

    def clear_old_alerts(self, max_age_hours: int = 24):
        """Clear alerts older than max_age_hours."""
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        self.alerts = {
            k: v for k, v in self.alerts.items()
            if v.timestamp > cutoff
        }

    def set_min_level(self, level: AlertLevel):
        """Set minimum notification level."""
        self.min_level = level
        logger.info("Alert min level changed", level=level.value)

    def set_cooldown(self, seconds: int):
        """Set cooldown between notifications."""
        self.cooldown_seconds = seconds
        logger.info("Alert cooldown changed", seconds=seconds)
