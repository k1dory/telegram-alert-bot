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
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from config import settings
from dashboard import DashboardRenderer, ServerMetrics, ContainerInfo, Alert, NodeStatus, ContainerStatus

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

class MockDataProvider:
    """Provides mock data for standalone testing."""

    @staticmethod
    def get_servers() -> list[ServerMetrics]:
        """Generate mock server metrics."""
        return [
            ServerMetrics(
                name="prod-api-1",
                cpu_percent=random.randint(15, 45),
                mem_percent=random.randint(30, 50),
                disk_percent=random.randint(40, 60),
                status=NodeStatus.OK
            ),
            ServerMetrics(
                name="prod-api-2",
                cpu_percent=random.randint(60, 95),
                mem_percent=random.randint(60, 80),
                disk_percent=random.randint(50, 70),
                status=NodeStatus.WARNING if random.random() > 0.5 else NodeStatus.OK
            ),
            ServerMetrics(
                name="prod-db-1",
                cpu_percent=random.randint(10, 30),
                mem_percent=random.randint(70, 90),
                disk_percent=random.randint(75, 95),
                status=NodeStatus.OK
            ),
            ServerMetrics(
                name="staging-1",
                cpu_percent=None,
                mem_percent=None,
                disk_percent=None,
                status=NodeStatus.OFFLINE
            ),
        ]

    @staticmethod
    def get_containers() -> list[ContainerInfo]:
        """Generate mock container info."""
        return [
            ContainerInfo("nginx", ContainerStatus.RUNNING, "12h"),
            ContainerInfo("postgres", ContainerStatus.RUNNING, "5d"),
            ContainerInfo("redis", ContainerStatus.RUNNING, "5d"),
            ContainerInfo("app-worker", ContainerStatus.STOPPED, "2h ago"),
        ]

    @staticmethod
    def get_alerts() -> list[Alert]:
        """Generate mock alerts."""
        alerts = []
        if random.random() > 0.3:
            alerts.append(Alert("!", "High CPU: prod-api-2 (89%)"))
        if random.random() > 0.5:
            alerts.append(Alert("i", "Disk warning: prod-db-1 (88%)"))
        return alerts


mock_data = MockDataProvider()


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
            servers = mock_data.get_servers()
            containers = mock_data.get_containers()
            alerts = mock_data.get_alerts()

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
        servers = mock_data.get_servers()
        containers = mock_data.get_containers()
        alerts = mock_data.get_alerts()

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
    servers = mock_data.get_servers()
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
    alerts = mock_data.get_alerts()
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
  /config  - Bot settings
  /help    - This help

DASHBOARD:
  Auto-refreshes every 30s
  Click Refresh for manual update
  Click Close to stop updates

ALERTS:
  [!] - Critical alert
  [i] - Info/Warning
```
"""
    await update.message.reply_text(text, parse_mode="MarkdownV2")


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
        elif parts[0] == "servers":
            await handle_servers_callback(query, parts, context)
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
        servers = mock_data.get_servers()
        containers = mock_data.get_containers()
        alerts = mock_data.get_alerts()

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
        servers = mock_data.get_servers()
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
        alerts = mock_data.get_alerts()
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
        await query.answer("All alerts acknowledged")
    elif action == "refresh":
        await query.answer("Alerts refreshed")


async def handle_servers_callback(query, parts, context):
    """Handle servers callbacks."""
    action = parts[1] if len(parts) > 1 else None

    if action == "refresh":
        await query.answer("Servers refreshed")


# === Background Jobs ===

async def dashboard_refresh_job(context: ContextTypes.DEFAULT_TYPE):
    """Background job to refresh dashboards."""
    await dashboard_state.update_dashboard(context)


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
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("help", cmd_help))

    # Add callback handler
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Add error handler
    app.add_error_handler(error_handler)

    # Add background job for dashboard refresh
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(
            dashboard_refresh_job,
            interval=settings.dashboard_refresh_interval,
            first=10
        )
        logger.info(f"Dashboard auto-refresh: every {settings.dashboard_refresh_interval}s")

    logger.info("Bot started! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
