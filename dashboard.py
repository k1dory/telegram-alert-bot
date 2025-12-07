"""
ASCII Dashboard renderer for Telegram.
Simple ASCII style that works on all devices.
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from enum import Enum


class NodeStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    OFFLINE = "offline"


class ContainerStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    RESTARTING = "restarting"
    ERROR = "error"


@dataclass
class ServerMetrics:
    """Server metrics data."""
    name: str
    cpu_percent: Optional[float] = None
    mem_percent: Optional[float] = None
    disk_percent: Optional[float] = None
    status: NodeStatus = NodeStatus.OFFLINE


@dataclass
class ContainerInfo:
    """Docker container info."""
    name: str
    status: ContainerStatus
    uptime: str  # "12h", "5d", "2h ago"


@dataclass
class Alert:
    """Alert information."""
    level: str  # "!" for critical, "i" for info
    message: str


class DashboardRenderer:
    """Renders ASCII dashboard for Telegram."""

    # Simple ASCII characters that work everywhere
    TOP_LEFT = "+"
    TOP_RIGHT = "+"
    BOTTOM_LEFT = "+"
    BOTTOM_RIGHT = "+"
    HORIZONTAL = "-"
    VERTICAL = "|"
    T_RIGHT = "+"
    T_LEFT = "+"

    # Inner box (same as outer for simplicity)
    INNER_TL = "+"
    INNER_TR = "+"
    INNER_BL = "+"
    INNER_BR = "+"
    INNER_H = "-"
    INNER_V = "|"

    # Status indicators
    STATUS_OK = "[OK]"
    STATUS_WARN = "[!!]"
    STATUS_OFFLINE = "[--]"

    WIDTH = 36  # Narrower for mobile

    def __init__(self):
        self.last_update: Optional[datetime] = None

    def _line(self, char: str = "-") -> str:
        """Create horizontal line."""
        return "+" + char * (self.WIDTH - 2) + "+"

    def _row(self, content: str) -> str:
        """Create content row."""
        inner = self.WIDTH - 4
        if len(content) > inner:
            content = content[:inner]
        return "| " + content.ljust(inner) + " |"

    def _format_status(self, status: NodeStatus) -> str:
        """Format node status indicator."""
        if status == NodeStatus.OK:
            return "OK"
        elif status == NodeStatus.WARNING:
            return "!!"
        elif status == NodeStatus.CRITICAL:
            return "!!"
        return "--"

    def _format_container_status(self, status: ContainerStatus) -> str:
        """Format container status."""
        if status == ContainerStatus.RUNNING:
            return "+"
        elif status == ContainerStatus.STOPPED:
            return "-"
        elif status == ContainerStatus.RESTARTING:
            return "~"
        return "x"

    def _format_percent(self, value: Optional[float]) -> str:
        """Format percentage value."""
        if value is None:
            return "---"
        return f"{int(value):3d}%"

    def render(
        self,
        servers: list[ServerMetrics],
        containers: list[ContainerInfo],
        alerts: list[Alert],
        refresh_interval: int = 30
    ) -> str:
        """Render full dashboard."""
        now = datetime.utcnow()
        self.last_update = now
        time_str = now.strftime("%H:%M:%S UTC")

        lines = []

        # Header
        lines.append(self._line("="))
        lines.append(self._row("INFRASTRUCTURE MONITOR"))
        lines.append(self._row(time_str.center(self.WIDTH - 4)))
        lines.append(self._line("="))

        # Servers section
        lines.append(self._row(""))
        lines.append(self._row("SERVERS:"))
        lines.append(self._row("-" * (self.WIDTH - 4)))

        for server in servers:
            cpu = self._format_percent(server.cpu_percent)
            mem = self._format_percent(server.mem_percent)
            stat = self._format_status(server.status)
            name = server.name[:10].ljust(10)
            line = f"{name} CPU:{cpu} MEM:{mem} [{stat}]"
            lines.append(self._row(line))

        # Containers section
        lines.append(self._row(""))
        lines.append(self._row("CONTAINERS:"))
        lines.append(self._row("-" * (self.WIDTH - 4)))

        running = [c for c in containers if c.status == ContainerStatus.RUNNING]
        stopped = [c for c in containers if c.status != ContainerStatus.RUNNING]

        if running:
            names = ", ".join([c.name[:8] for c in running[:4]])
            lines.append(self._row(f"[+] {names}"))

        for c in stopped[:2]:
            lines.append(self._row(f"[-] {c.name} ({c.uptime})"))

        # Alerts section
        if alerts:
            lines.append(self._row(""))
            lines.append(self._row(f"ALERTS ({len(alerts)}):"))
            lines.append(self._row("-" * (self.WIDTH - 4)))
            for alert in alerts[:3]:
                msg = alert.message[:28]
                lines.append(self._row(f"[{alert.level}] {msg}"))

        # Footer
        lines.append(self._line("-"))
        lines.append(self._row(f"Refresh: {refresh_interval}s"))
        lines.append(self._line("="))

        return "\n".join(lines)

    def render_minimal(self, servers: list[ServerMetrics]) -> str:
        """Render minimal status view."""
        now = datetime.utcnow()
        time_str = now.strftime("%H:%M:%S")

        lines = [
            self._line("="),
            self._row(f"STATUS {time_str}"),
            self._line("-"),
        ]

        for server in servers:
            stat = self._format_status(server.status)
            cpu = self._format_percent(server.cpu_percent)
            name = server.name[:12].ljust(12)
            lines.append(self._row(f"{name} {cpu} [{stat}]"))

        lines.append(self._line("="))

        return "\n".join(lines)

    def render_alert(self, alert: Alert, server: str = None) -> str:
        """Render single alert notification."""
        now = datetime.utcnow()
        time_str = now.strftime("%H:%M:%S")

        level_marker = "!!" if alert.level == "!" else "i"

        lines = [
            self._line("="),
            self._row(f"[{level_marker}] ALERT {time_str}"),
            self._line("-"),
            self._row(alert.message[:self.WIDTH - 4]),
        ]

        if server:
            lines.append(self._row(f"Source: {server}"))

        lines.append(self._line("="))

        return "\n".join(lines)


# Example usage
if __name__ == "__main__":
    renderer = DashboardRenderer()

    servers = [
        ServerMetrics("prod-api-1", 23, 38, 45, NodeStatus.OK),
        ServerMetrics("prod-api-2", 89, 72, 61, NodeStatus.WARNING),
        ServerMetrics("prod-db-1", 12, 85, 88, NodeStatus.OK),
        ServerMetrics("staging-1", None, None, None, NodeStatus.OFFLINE),
    ]

    containers = [
        ContainerInfo("nginx", ContainerStatus.RUNNING, "12h"),
        ContainerInfo("postgres", ContainerStatus.RUNNING, "5d"),
        ContainerInfo("redis", ContainerStatus.RUNNING, "5d"),
        ContainerInfo("app-worker", ContainerStatus.STOPPED, "2h ago"),
    ]

    alerts = [
        Alert("!", "High CPU: prod-api-2 (89%)"),
        Alert("i", "Disk warning: prod-db-1 (88%)"),
    ]

    print(renderer.render(servers, containers, alerts))
