"""
Infra AI Platform - Telegram Bot

Main bot module with command handlers, 2FA confirmations,
live dashboard, and alert notifications.

Standalone version for testing without Gateway.
"""

import asyncio
import functools
import logging
import random
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from collections import deque

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.error import BadRequest

from config import settings
from dashboard import DashboardRenderer, ServerMetrics, ContainerInfo, Alert, NodeStatus, ContainerStatus


# === Alert History ===

@dataclass
class AlertRecord:
    """Record of an alert with timestamp."""
    id: str
    level: str  # "!" for critical, "i" for info/warning
    message: str
    source: str
    timestamp: datetime
    acknowledged: bool = False


class AlertManager:
    """Manages alerts, history, and notifications."""

    def __init__(self, max_history: int = 100):
        self.history: deque[AlertRecord] = deque(maxlen=max_history)
        self.active_alert_messages: dict[int, int] = {}  # chat_id -> message_id
        self.last_critical: Optional[AlertRecord] = None
        self.alert_counter = 0

    def add_alert(self, level: str, message: str, source: str = "system") -> AlertRecord:
        """Add new alert to history."""
        self.alert_counter += 1
        alert = AlertRecord(
            id=f"ALR-{self.alert_counter:04d}",
            level=level,
            message=message,
            source=source,
            timestamp=datetime.utcnow()
        )
        self.history.append(alert)

        if level == "!":
            self.last_critical = alert

        return alert

    def get_history(self, limit: int = 20) -> list[AlertRecord]:
        """Get recent alert history."""
        return list(self.history)[-limit:]

    def get_active_critical(self) -> Optional[AlertRecord]:
        """Get current active critical alert."""
        if self.last_critical and not self.last_critical.acknowledged:
            return self.last_critical
        return None

    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        for alert in self.history:
            if alert.id == alert_id:
                alert.acknowledged = True
                return True
        return False

    def acknowledge_all(self):
        """Acknowledge all alerts."""
        for alert in self.history:
            alert.acknowledged = True
        self.last_critical = None

    def clear_active_message(self, chat_id: int):
        """Clear active alert message reference."""
        if chat_id in self.active_alert_messages:
            del self.active_alert_messages[chat_id]


alert_manager = AlertManager()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# === Access Control ===

def authorized(func):
    """Decorator to check if user is authorized."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        # If whitelist is empty, allow all users
        if settings.allowed_user_ids and user_id not in settings.allowed_user_ids:
            logger.warning(f"Unauthorized access attempt from user {user_id}")
            await update.message.reply_text(
                f"Access denied. Your user ID ({user_id}) is not in the whitelist."
            )
            return
        return await func(update, context)
    return wrapper


# === Mock Data Generator ===

class RealDataProvider:
    """Provides real system monitoring data."""

    # Thresholds for alerts
    CPU_WARNING = 80
    CPU_CRITICAL = 95
    MEM_WARNING = 80
    MEM_CRITICAL = 95
    DISK_WARNING = 80
    DISK_CRITICAL = 95

    def __init__(self):
        self._last_alerts: list[Alert] = []
        self._last_critical: Optional[Alert] = None

    def get_servers(self) -> list[ServerMetrics]:
        """Get real server metrics."""
        import subprocess
        import socket

        hostname = socket.gethostname()[:20]
        metrics = ServerMetrics(
            name=hostname,
            cpu_percent=None,
            mem_percent=None,
            disk_percent=None,
            status=NodeStatus.OK
        )

        try:
            # Get CPU usage
            result = subprocess.run(
                ["sh", "-c", "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                cpu = float(result.stdout.strip().replace(',', '.'))
                metrics.cpu_percent = cpu

            # Get memory usage
            result = subprocess.run(
                ["sh", "-c", "free | grep Mem | awk '{printf \"%.1f\", $3/$2 * 100}'"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                metrics.mem_percent = float(result.stdout.strip())

            # Get disk usage
            result = subprocess.run(
                ["sh", "-c", "df / | tail -1 | awk '{print $5}' | tr -d '%'"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                metrics.disk_percent = float(result.stdout.strip())

            # Determine status
            if (metrics.cpu_percent and metrics.cpu_percent >= self.CPU_CRITICAL) or \
               (metrics.mem_percent and metrics.mem_percent >= self.MEM_CRITICAL) or \
               (metrics.disk_percent and metrics.disk_percent >= self.DISK_CRITICAL):
                metrics.status = NodeStatus.CRITICAL
            elif (metrics.cpu_percent and metrics.cpu_percent >= self.CPU_WARNING) or \
                 (metrics.mem_percent and metrics.mem_percent >= self.MEM_WARNING) or \
                 (metrics.disk_percent and metrics.disk_percent >= self.DISK_WARNING):
                metrics.status = NodeStatus.WARNING

        except Exception as e:
            logger.error(f"Failed to get server metrics: {e}")
            metrics.status = NodeStatus.OFFLINE

        return [metrics]

    def get_containers(self) -> list[ContainerInfo]:
        """Get real Docker container info."""
        import subprocess

        containers = []
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}|{{.State}}"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if not line:
                        continue
                    parts = line.split('|')
                    if len(parts) >= 3:
                        name = parts[0][:20]
                        status_text = parts[1]
                        state = parts[2].lower()

                        # Parse uptime from status
                        uptime = "unknown"
                        if "Up" in status_text:
                            # "Up 3 days" -> "3d"
                            import re
                            match = re.search(r'Up\s+(\d+)\s+(\w+)', status_text)
                            if match:
                                num, unit = match.groups()
                                uptime = f"{num}{unit[0]}"

                        if state == "running":
                            status = ContainerStatus.RUNNING
                        elif state == "exited":
                            status = ContainerStatus.STOPPED
                            uptime = "stopped"
                        elif state == "restarting":
                            status = ContainerStatus.RESTARTING
                        else:
                            status = ContainerStatus.ERROR

                        containers.append(ContainerInfo(name, status, uptime))

        except Exception as e:
            logger.error(f"Failed to get containers: {e}")

        return containers

    def get_alerts(self) -> list[Alert]:
        """Get current alerts based on thresholds."""
        alerts = []
        servers = self.get_servers()

        for server in servers:
            if server.cpu_percent and server.cpu_percent >= self.CPU_WARNING:
                level = "!" if server.cpu_percent >= self.CPU_CRITICAL else "i"
                alerts.append(Alert(level, f"CPU {server.cpu_percent:.0f}% on {server.name}"))

            if server.mem_percent and server.mem_percent >= self.MEM_WARNING:
                level = "!" if server.mem_percent >= self.MEM_CRITICAL else "i"
                alerts.append(Alert(level, f"Memory {server.mem_percent:.0f}% on {server.name}"))

            if server.disk_percent and server.disk_percent >= self.DISK_WARNING:
                level = "!" if server.disk_percent >= self.DISK_CRITICAL else "i"
                alerts.append(Alert(level, f"Disk {server.disk_percent:.0f}% on {server.name}"))

        # Check for stopped containers
        containers = self.get_containers()
        stopped = [c for c in containers if c.status == ContainerStatus.STOPPED]
        for c in stopped:
            alerts.append(Alert("i", f"Container {c.name} stopped"))

        self._last_alerts = alerts
        return alerts

    def check_critical_alerts(self) -> Optional[Alert]:
        """Check for critical alerts."""
        alerts = self.get_alerts()
        critical = [a for a in alerts if a.level == "!"]

        if critical:
            # Return new critical alert if different from last
            new_alert = critical[0]
            if self._last_critical is None or self._last_critical.message != new_alert.message:
                self._last_critical = new_alert
                return new_alert
        else:
            self._last_critical = None

        return None


monitor = RealDataProvider()


# === Dashboard State ===

class DashboardState:
    """Manages live dashboard state."""

    def __init__(self):
        self.renderer = DashboardRenderer()
        self.active_messages: dict[int, Message] = {}
        self.refresh_interval = settings.dashboard_refresh_interval

    async def update_dashboard(self, context: ContextTypes.DEFAULT_TYPE):
        """Update all active dashboards."""
        if not self.active_messages:
            return

        try:
            servers = monitor.get_servers()
            containers = monitor.get_containers()
            alerts = monitor.get_alerts()

            content = self.renderer.render(
                servers=servers,
                containers=containers,
                alerts=alerts,
                refresh_interval=self.refresh_interval
            )

            for chat_id, message in list(self.active_messages.items()):
                try:
                    keyboard = self._get_dashboard_keyboard()
                    await message.edit_text(
                        f"```\n{content}\n```",
                        parse_mode="MarkdownV2",
                        reply_markup=keyboard
                    )
                except Exception as e:
                    logger.warning(f"Failed to update dashboard for {chat_id}: {e}")
                    if "Message is not modified" not in str(e):
                        del self.active_messages[chat_id]

        except Exception as e:
            logger.error(f"Dashboard update failed: {e}")

    def _get_dashboard_keyboard(self) -> InlineKeyboardMarkup:
        """Get dashboard inline keyboard."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Refresh", callback_data="dashboard:refresh"),
                InlineKeyboardButton("Servers", callback_data="menu:servers"),
            ],
            [
                InlineKeyboardButton("Alerts", callback_data="menu:alerts"),
                InlineKeyboardButton("Settings", callback_data="menu:settings"),
            ],
            [
                InlineKeyboardButton("Close Dashboard", callback_data="dashboard:close"),
            ]
        ])


dashboard_state = DashboardState()


# === Command Handlers ===

@authorized
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    r = dashboard_state.renderer

    welcome = f"""
```
{r.TOP_LEFT}{r.HORIZONTAL * 40}{r.TOP_RIGHT}
{r.VERTICAL}                                        {r.VERTICAL}
{r.VERTICAL}    INFRA AI PLATFORM                   {r.VERTICAL}
{r.VERTICAL}    Control Center v1.0                 {r.VERTICAL}
{r.VERTICAL}                                        {r.VERTICAL}
{r.T_RIGHT}{r.HORIZONTAL * 40}{r.T_LEFT}
{r.VERTICAL}                                        {r.VERTICAL}
{r.VERTICAL}  Welcome, {user.first_name[:20]:<20}       {r.VERTICAL}
{r.VERTICAL}  ID: {user.id:<32}  {r.VERTICAL}
{r.VERTICAL}                                        {r.VERTICAL}
{r.VERTICAL}  Commands:                             {r.VERTICAL}
{r.VERTICAL}  /status  - Live dashboard             {r.VERTICAL}
{r.VERTICAL}  /servers - Server list                {r.VERTICAL}
{r.VERTICAL}  /alerts  - View alerts                {r.VERTICAL}
{r.VERTICAL}  /config  - Settings                   {r.VERTICAL}
{r.VERTICAL}  /help    - Help                       {r.VERTICAL}
{r.VERTICAL}                                        {r.VERTICAL}
{r.BOTTOM_LEFT}{r.HORIZONTAL * 40}{r.BOTTOM_RIGHT}
```
"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Dashboard", callback_data="menu:dashboard"),
            InlineKeyboardButton("Servers", callback_data="menu:servers"),
        ],
        [
            InlineKeyboardButton("Alerts", callback_data="menu:alerts"),
            InlineKeyboardButton("Settings", callback_data="menu:settings"),
        ]
    ])

    await update.message.reply_text(
        welcome,
        parse_mode="MarkdownV2",
        reply_markup=keyboard
    )


@authorized
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - show live dashboard."""
    chat_id = update.effective_chat.id

    try:
        servers = monitor.get_servers()
        containers = monitor.get_containers()
        alerts = monitor.get_alerts()

        content = dashboard_state.renderer.render(
            servers=servers,
            containers=containers,
            alerts=alerts
        )

        keyboard = dashboard_state._get_dashboard_keyboard()

        message = await update.message.reply_text(
            f"```\n{content}\n```",
            parse_mode="MarkdownV2",
            reply_markup=keyboard
        )

        dashboard_state.active_messages[chat_id] = message
        logger.info(f"Dashboard activated for chat {chat_id}")

    except Exception as e:
        logger.error(f"Failed to show dashboard: {e}")
        await update.message.reply_text(f"Failed to fetch status: {str(e)}")


@authorized
async def cmd_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /servers command."""
    servers = monitor.get_servers()
    r = dashboard_state.renderer

    lines = [
        f"{r.TOP_LEFT}{r.HORIZONTAL * 35}{r.TOP_RIGHT}",
        f"{r.VERTICAL}  SERVER LIST                       {r.VERTICAL}",
        f"{r.T_RIGHT}{r.HORIZONTAL * 35}{r.T_LEFT}",
    ]

    for s in servers:
        name = s.name[:15].ljust(15)
        status = "[#]" if s.status == NodeStatus.OK else "[ ]" if s.status == NodeStatus.OFFLINE else "[!]"
        cpu = f"{s.cpu_percent}%" if s.cpu_percent else "---"
        lines.append(f"{r.VERTICAL}  {status} {name} CPU:{cpu:>4}   {r.VERTICAL}")

    lines.append(f"{r.BOTTOM_LEFT}{r.HORIZONTAL * 35}{r.BOTTOM_RIGHT}")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Refresh", callback_data="servers:refresh")],
        [InlineKeyboardButton("Back", callback_data="menu:main")]
    ])

    await update.message.reply_text(
        f"```\n{chr(10).join(lines)}\n```",
        parse_mode="MarkdownV2",
        reply_markup=keyboard
    )


@authorized
async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alerts command."""
    alerts = monitor.get_alerts()
    r = dashboard_state.renderer

    if not alerts:
        await update.message.reply_text("No active alerts.")
        return

    lines = [
        f"{r.TOP_LEFT}{r.HORIZONTAL * 40}{r.TOP_RIGHT}",
        f"{r.VERTICAL}  ACTIVE ALERTS ({len(alerts)})                    {r.VERTICAL}",
        f"{r.T_RIGHT}{r.HORIZONTAL * 40}{r.T_LEFT}",
    ]

    for a in alerts:
        level = "[!]" if a.level == "!" else "[i]"
        msg = a.message[:32]
        lines.append(f"{r.VERTICAL}  {level} {msg:<34}  {r.VERTICAL}")

    lines.append(f"{r.BOTTOM_LEFT}{r.HORIZONTAL * 40}{r.BOTTOM_RIGHT}")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Acknowledge All", callback_data="alerts:ack_all"),
            InlineKeyboardButton("Refresh", callback_data="alerts:refresh"),
        ],
        [InlineKeyboardButton("Back", callback_data="menu:main")]
    ])

    await update.message.reply_text(
        f"```\n{chr(10).join(lines)}\n```",
        parse_mode="MarkdownV2",
        reply_markup=keyboard
    )


@authorized
async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /config command."""
    r = dashboard_state.renderer
    refresh = settings.dashboard_refresh_interval
    mode = settings.discovery_mode.value

    text = f"""
```
{r.TOP_LEFT}{r.HORIZONTAL * 35}{r.TOP_RIGHT}
{r.VERTICAL}  SETTINGS                          {r.VERTICAL}
{r.T_RIGHT}{r.HORIZONTAL * 35}{r.T_LEFT}
{r.VERTICAL}                                    {r.VERTICAL}
{r.VERTICAL}  Refresh:    {refresh}s                  {r.VERTICAL}
{r.VERTICAL}  Discovery:  {mode:<12}          {r.VERTICAL}
{r.VERTICAL}  2FA:        Enabled               {r.VERTICAL}
{r.VERTICAL}                                    {r.VERTICAL}
{r.BOTTOM_LEFT}{r.HORIZONTAL * 35}{r.BOTTOM_RIGHT}
```
"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("30s", callback_data="config:refresh:30"),
            InlineKeyboardButton("60s", callback_data="config:refresh:60"),
            InlineKeyboardButton("120s", callback_data="config:refresh:120"),
        ],
        [InlineKeyboardButton("Back", callback_data="menu:main")]
    ])

    await update.message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=keyboard
    )


@authorized
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    text = """
```
INFRA AI BOT - HELP

COMMANDS:
  /start   - Welcome screen
  /status  - Live dashboard
  /servers - List all servers
  /alerts  - View active alerts
  /history - Alert history
  /logs    - Container logs
  /config  - Bot settings
  /help    - This help

DASHBOARD:
  Auto-refreshes every 30s
  Click Refresh for manual update
  Click Close to stop updates

ALERTS:
  [!] - Critical alert
  [i] - Info/Warning

Critical alerts are sent as
separate messages every 10s
```
"""
    await update.message.reply_text(text, parse_mode="MarkdownV2")


@authorized
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history command - show alert history."""
    history = alert_manager.get_history(20)

    if not history:
        await update.message.reply_text("```\nNo alerts in history.\n```", parse_mode="MarkdownV2")
        return

    lines = [
        "+==================================+",
        "| ALERT HISTORY                    |",
        "+----------------------------------+",
    ]

    for alert in reversed(history[-10:]):
        time_str = alert.timestamp.strftime("%H:%M:%S")
        ack = "v" if alert.acknowledged else " "
        msg = alert.message[:22]
        lines.append(f"| [{alert.level}][{ack}] {time_str} {msg:<12}|")

    lines.append("+----------------------------------+")
    lines.append(f"| Total: {len(history)} alerts              |")
    lines.append("+==================================+")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Ack All", callback_data="alerts:ack_all"),
            InlineKeyboardButton("Refresh", callback_data="history:refresh"),
        ],
        [InlineKeyboardButton("Back", callback_data="menu:dashboard")]
    ])

    await update.message.reply_text(
        f"```\n{chr(10).join(lines)}\n```",
        parse_mode="MarkdownV2",
        reply_markup=keyboard
    )


@authorized
async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /logs command - show container logs."""
    containers = monitor.get_containers()

    if not containers:
        await update.message.reply_text("```\nNo containers found.\n```", parse_mode="MarkdownV2")
        return

    lines = [
        "+======================================+",
        "| SELECT CONTAINER FOR LOGS            |",
        "+--------------------------------------+",
    ]

    # Create buttons for each container
    buttons = []
    for c in containers:
        status = "+" if c.status == ContainerStatus.RUNNING else "-"
        lines.append(f"| [{status}] {c.name:<32} |")
        buttons.append([InlineKeyboardButton(
            f"{c.name}",
            callback_data=f"logs:{c.name}"
        )])

    lines.append("+======================================+")

    buttons.append([InlineKeyboardButton("Back", callback_data="menu:dashboard")])
    keyboard = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        f"```\n{chr(10).join(lines)}\n```",
        parse_mode="MarkdownV2",
        reply_markup=keyboard
    )


async def get_container_logs(container_name: str, lines: int = 30) -> str:
    """Get logs from a Docker container."""
    import subprocess

    try:
        result = subprocess.run(
            ["docker", "logs", container_name, "--tail", str(lines)],
            capture_output=True, text=True, timeout=10
        )
        # Docker logs go to stderr for some containers
        output = result.stdout or result.stderr
        if output:
            return output.strip()
        return "No logs available"
    except subprocess.TimeoutExpired:
        return "Timeout getting logs"
    except Exception as e:
        return f"Error: {str(e)}"


# === Callback Handlers ===

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split(":")

    try:
        if parts[0] == "dashboard":
            await handle_dashboard_callback(query, parts, context)
        elif parts[0] == "menu":
            await handle_menu_callback(query, parts, context)
        elif parts[0] == "config":
            await handle_config_callback(query, parts, context)
        elif parts[0] == "alerts":
            await handle_alerts_callback(query, parts, context)
        elif parts[0] == "alert":
            await handle_alerts_callback(query, parts, context)
        elif parts[0] == "servers":
            await handle_servers_callback(query, parts, context)
        elif parts[0] == "history":
            await query.answer("Use /history command")
        elif parts[0] == "logs":
            await handle_logs_callback(query, parts, context)
        elif parts[0] == "logs50":
            # More logs (50 lines)
            parts[0] = "logs"
            await handle_logs_callback(query, parts, context, lines=50)
    except Exception as e:
        logger.error(f"Callback error: {e}")


async def handle_dashboard_callback(query, parts, context):
    """Handle dashboard callbacks."""
    action = parts[1] if len(parts) > 1 else None

    if action == "refresh":
        await dashboard_state.update_dashboard(context)
        await query.answer("Refreshed!")
    elif action == "close":
        chat_id = query.message.chat_id
        if chat_id in dashboard_state.active_messages:
            del dashboard_state.active_messages[chat_id]
        await query.message.edit_text("Dashboard closed. Use /status to reopen.")
        await query.answer("Dashboard closed")


async def handle_menu_callback(query, parts, context):
    """Handle menu navigation callbacks."""
    menu = parts[1] if len(parts) > 1 else "main"
    r = dashboard_state.renderer

    if menu == "dashboard":
        # Start new dashboard
        chat_id = query.message.chat_id
        servers = monitor.get_servers()
        containers = monitor.get_containers()
        alerts = monitor.get_alerts()

        content = dashboard_state.renderer.render(
            servers=servers,
            containers=containers,
            alerts=alerts
        )

        keyboard = dashboard_state._get_dashboard_keyboard()

        message = await query.message.edit_text(
            f"```\n{content}\n```",
            parse_mode="MarkdownV2",
            reply_markup=keyboard
        )
        dashboard_state.active_messages[chat_id] = message

    elif menu == "servers":
        servers = monitor.get_servers()
        lines = [
            "+==================================+",
            "| SERVER LIST                      |",
            "+----------------------------------+",
        ]
        for s in servers:
            name = s.name[:12].ljust(12)
            cpu = f"{s.cpu_percent}%" if s.cpu_percent else "---"
            stat = "OK" if s.status == NodeStatus.OK else "--" if s.status == NodeStatus.OFFLINE else "!!"
            lines.append(f"| {name} CPU:{cpu:>4} [{stat}]     |")
        lines.append("+==================================+")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Refresh", callback_data="menu:servers")],
            [InlineKeyboardButton("Back", callback_data="menu:dashboard")]
        ])

        await query.message.edit_text(
            f"```\n{chr(10).join(lines)}\n```",
            parse_mode="MarkdownV2",
            reply_markup=keyboard
        )

    elif menu == "alerts":
        alerts = monitor.get_alerts()
        if not alerts:
            lines = [
                "+==================================+",
                "| NO ACTIVE ALERTS                 |",
                "+==================================+",
            ]
        else:
            lines = [
                "+==================================+",
                f"| ALERTS ({len(alerts)})                        |",
                "+----------------------------------+",
            ]
            for a in alerts:
                msg = a.message[:28]
                lines.append(f"| [{a.level}] {msg:<28} |")
            lines.append("+==================================+")

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Ack All", callback_data="alerts:ack_all"),
                InlineKeyboardButton("Refresh", callback_data="menu:alerts"),
            ],
            [InlineKeyboardButton("Back", callback_data="menu:dashboard")]
        ])

        await query.message.edit_text(
            f"```\n{chr(10).join(lines)}\n```",
            parse_mode="MarkdownV2",
            reply_markup=keyboard
        )

    elif menu == "settings":
        refresh = dashboard_state.refresh_interval
        lines = [
            "+==================================+",
            "| SETTINGS                         |",
            "+----------------------------------+",
            f"| Refresh interval: {refresh}s           |",
            "| Discovery: auto                  |",
            "| 2FA: enabled                     |",
            "+==================================+",
        ]

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("30s", callback_data="config:refresh:30"),
                InlineKeyboardButton("60s", callback_data="config:refresh:60"),
                InlineKeyboardButton("120s", callback_data="config:refresh:120"),
            ],
            [InlineKeyboardButton("Back", callback_data="menu:dashboard")]
        ])

        await query.message.edit_text(
            f"```\n{chr(10).join(lines)}\n```",
            parse_mode="MarkdownV2",
            reply_markup=keyboard
        )

    elif menu == "logs":
        # Show container list for logs
        containers = monitor.get_containers()
        buttons = []
        for c in containers:
            buttons.append([InlineKeyboardButton(
                f"{c.name}",
                callback_data=f"logs:{c.name}"
            )])
        buttons.append([InlineKeyboardButton("Back", callback_data="menu:dashboard")])
        keyboard = InlineKeyboardMarkup(buttons)

        await query.message.edit_text(
            "```\nSelect container for logs:\n```",
            parse_mode="MarkdownV2",
            reply_markup=keyboard
        )

    elif menu == "main":
        await query.message.edit_text("Use /start to return to main menu.")


async def handle_config_callback(query, parts, context):
    """Handle config callbacks."""
    if len(parts) >= 3 and parts[1] == "refresh":
        new_interval = int(parts[2])
        dashboard_state.refresh_interval = new_interval
        await query.answer(f"Refresh interval: {new_interval}s")


async def handle_alerts_callback(query, parts, context):
    """Handle alerts callbacks."""
    action = parts[1] if len(parts) > 1 else None

    if action == "ack_all":
        alert_manager.acknowledge_all()
        await query.answer("All alerts acknowledged")
    elif action == "refresh":
        await query.answer("Alerts refreshed")
    elif action == "ack" and len(parts) >= 3:
        alert_id = parts[2]
        if alert_manager.acknowledge(alert_id):
            # Clear active message for this user
            alert_manager.clear_active_message(query.from_user.id)
            await query.message.edit_text(
                f"```\nAlert {alert_id} acknowledged.\n```",
                parse_mode="MarkdownV2"
            )
            await query.answer("Alert acknowledged")
        else:
            await query.answer("Alert not found")


async def handle_servers_callback(query, parts, context):
    """Handle servers callbacks."""
    action = parts[1] if len(parts) > 1 else None

    if action == "refresh":
        await query.answer("Servers refreshed")


async def handle_logs_callback(query, parts, context, lines=25):
    """Handle logs callbacks - show container logs."""
    if len(parts) < 2:
        await query.answer("Invalid container")
        return

    container_name = parts[1]
    await query.answer(f"Loading logs for {container_name}...")

    # Get logs
    logs = await asyncio.get_event_loop().run_in_executor(
        None, lambda: get_container_logs_sync(container_name, lines)
    )

    # Escape special characters for MarkdownV2
    def escape_md(text):
        chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for c in chars:
            text = text.replace(c, f'\\{c}')
        return text

    # Truncate if too long (Telegram limit ~4096)
    if len(logs) > 3500:
        logs = logs[-3500:]
        logs = "...(truncated)\n" + logs

    escaped_logs = escape_md(logs)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Refresh", callback_data=f"logs:{container_name}"),
            InlineKeyboardButton("More (50)", callback_data=f"logs50:{container_name}"),
        ],
        [InlineKeyboardButton("Back to /logs", callback_data="menu:logs")]
    ])

    try:
        await query.message.edit_text(
            f"```\n{container_name} logs:\n\n{escaped_logs}\n```",
            parse_mode="MarkdownV2",
            reply_markup=keyboard
        )
    except Exception as e:
        # If message too long or other error, send plain text
        await query.message.edit_text(
            f"Logs for {container_name}:\n\n{logs[:3000]}",
            reply_markup=keyboard
        )


def get_container_logs_sync(container_name: str, lines: int = 30) -> str:
    """Get logs from a Docker container (sync version)."""
    import subprocess

    try:
        result = subprocess.run(
            ["docker", "logs", container_name, "--tail", str(lines)],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout or result.stderr
        if output:
            return output.strip()
        return "No logs available"
    except subprocess.TimeoutExpired:
        return "Timeout getting logs"
    except Exception as e:
        return f"Error: {str(e)}"


# === Background Jobs ===

async def dashboard_refresh_job(context: ContextTypes.DEFAULT_TYPE):
    """Background job to refresh dashboards."""
    await dashboard_state.update_dashboard(context)


async def critical_alert_job(context: ContextTypes.DEFAULT_TYPE):
    """Background job to check and send critical alerts every 10s."""
    # Check for new critical alerts
    critical = monitor.check_critical_alerts()

    if critical:
        # Add to history
        record = alert_manager.add_alert(critical.level, critical.message, "monitor")
        logger.warning(f"Critical alert: {critical.message}")

        # Send/update alert message to all users
        for user_id in settings.allowed_user_ids:
            try:
                # Create alert message
                lines = [
                    "+==================================+",
                    "|    !! CRITICAL ALERT !!         |",
                    "+----------------------------------+",
                    f"| {record.timestamp.strftime('%H:%M:%S')}                        |",
                    f"| {critical.message[:30]:<30} |",
                    "+----------------------------------+",
                    f"| ID: {record.id}                     |",
                    "+==================================+",
                ]

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("Acknowledge", callback_data=f"alert:ack:{record.id}")],
                ])

                # Delete old alert message if exists
                if user_id in alert_manager.active_alert_messages:
                    try:
                        await context.bot.delete_message(
                            chat_id=user_id,
                            message_id=alert_manager.active_alert_messages[user_id]
                        )
                    except BadRequest:
                        pass  # Message already deleted

                # Send new alert
                msg = await context.bot.send_message(
                    chat_id=user_id,
                    text=f"```\n{chr(10).join(lines)}\n```",
                    parse_mode="MarkdownV2",
                    reply_markup=keyboard
                )
                alert_manager.active_alert_messages[user_id] = msg.message_id

            except Exception as e:
                logger.error(f"Failed to send critical alert to {user_id}: {e}")


# === Error Handler ===

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors."""
    logger.error(f"Update {update} caused error {context.error}")


# === Main ===

def main():
    """Start the bot."""
    logger.info("Starting Infra AI Telegram Bot...")
    logger.info(f"Allowed users: {settings.allowed_user_ids}")

    # Create application
    app = Application.builder().token(settings.telegram_bot_token).build()

    # Add command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("servers", cmd_servers))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("help", cmd_help))

    # Add callback handler
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Add error handler
    app.add_error_handler(error_handler)

    # Add background jobs
    job_queue = app.job_queue
    if job_queue:
        # Dashboard refresh every 30s
        job_queue.run_repeating(
            dashboard_refresh_job,
            interval=settings.dashboard_refresh_interval,
            first=10
        )
        logger.info(f"Dashboard auto-refresh: every {settings.dashboard_refresh_interval}s")

        # Critical alert check every 10s
        job_queue.run_repeating(
            critical_alert_job,
            interval=10,
            first=5
        )
        logger.info("Critical alert check: every 10s")

    logger.info("Bot started! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
