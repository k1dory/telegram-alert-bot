"""
ASCII Dashboard renderer for Telegram.
Style: Variant B - Clean with sections.
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

    # Box drawing characters
    TOP_LEFT = "\u250f"      # ┏
    TOP_RIGHT = "\u2513"     # ┓
    BOTTOM_LEFT = "\u2517"   # ┗
    BOTTOM_RIGHT = "\u251b"  # ┛
    HORIZONTAL = "\u2501"    # ━
    VERTICAL = "\u2503"      # ┃
    T_RIGHT = "\u2523"       # ┣
    T_LEFT = "\u252b"        # ┫

    # Inner box
    INNER_TL = "\u250c"      # ┌
    INNER_TR = "\u2510"      # ┐
    INNER_BL = "\u2514"      # └
    INNER_BR = "\u2518"      # ┘
    INNER_H = "\u2500"       # ─
    INNER_V = "\u2502"       # │

    # Status indicators
    STATUS_OK = "[#]"        # ■
    STATUS_WARN = "[!]"
    STATUS_OFFLINE = "[ ]"   # □

    WIDTH = 43  # Total width of dashboard

    def __init__(self):
        self.last_update: Optional[datetime] = None

    def _center(self, text: str, width: int = None) -> str:
        """Center text within width."""
        w = width or (self.WIDTH - 4)
        return text.center(w)

    def _pad_line(self, content: str) -> str:
        """Pad line to fit within borders."""
        inner_width = self.WIDTH - 4
        if len(content) > inner_width:
            content = content[:inner_width]
        return f"{self.VERTICAL}  {content.ljust(inner_width)}{self.VERTICAL}"

    def _top_border(self) -> str:
        return f"{self.TOP_LEFT}{self.HORIZONTAL * (self.WIDTH - 2)}{self.TOP_RIGHT}"

    def _bottom_border(self) -> str:
        return f"{self.BOTTOM_LEFT}{self.HORIZONTAL * (self.WIDTH - 2)}{self.BOTTOM_RIGHT}"

    def _separator(self) -> str:
        return f"{self.T_RIGHT}{self.HORIZONTAL * (self.WIDTH - 2)}{self.T_LEFT}"

    def _empty_line(self) -> str:
        return self._pad_line("")

    def _inner_box_top(self, title: str) -> str:
        """Create inner box top with title."""
        title_part = f"{self.INNER_H} {title} "
        remaining = self.WIDTH - 8 - len(title_part)
        return f"{self.VERTICAL}  {self.INNER_TL}{title_part}{self.INNER_H * remaining}{self.INNER_TR}  {self.VERTICAL}"

    def _inner_box_bottom(self) -> str:
        """Create inner box bottom."""
        inner_width = self.WIDTH - 8
        return f"{self.VERTICAL}  {self.INNER_BL}{self.INNER_H * inner_width}{self.INNER_BR}  {self.VERTICAL}"

    def _inner_box_line(self, content: str) -> str:
        """Create inner box content line."""
        inner_width = self.WIDTH - 10
        if len(content) > inner_width:
            content = content[:inner_width]
        return f"{self.VERTICAL}  {self.INNER_V}  {content.ljust(inner_width - 2)}{self.INNER_V}  {self.VERTICAL}"

    def _format_status(self, status: NodeStatus) -> str:
        """Format node status indicator."""
        if status == NodeStatus.OK:
            return self.STATUS_OK
        elif status == NodeStatus.WARNING:
            return self.STATUS_WARN
        elif status == NodeStatus.CRITICAL:
            return self.STATUS_WARN
        return self.STATUS_OFFLINE

    def _format_container_status(self, status: ContainerStatus) -> str:
        """Format container status."""
        if status == ContainerStatus.RUNNING:
            return "#"  # ■
        elif status == ContainerStatus.STOPPED:
            return " "  # □
        elif status == ContainerStatus.RESTARTING:
            return "~"
        return "x"

    def _format_percent(self, value: Optional[float]) -> str:
        """Format percentage value."""
        if value is None:
            return "---"
        return f"{int(value)}%"

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
        lines.append(self._top_border())
        lines.append(self._pad_line(self._center("INFRASTRUCTURE MONITOR")))
        lines.append(self._pad_line(self._center(time_str)))
        lines.append(self._separator())
        lines.append(self._empty_line())

        # Servers section
        lines.append(self._inner_box_top("SERVERS"))
        lines.append(self._inner_box_line(""))
        lines.append(self._inner_box_line("NAME          CPU   MEM   STAT"))
        lines.append(self._inner_box_line(self.INNER_H * 30))

        for server in servers:
            cpu = self._format_percent(server.cpu_percent)
            mem = self._format_percent(server.mem_percent)
            stat = self._format_status(server.status)
            name = server.name[:12].ljust(12)
            line = f"{name}  {cpu:>4}  {mem:>4}  {stat}"
            lines.append(self._inner_box_line(line))

        lines.append(self._inner_box_line(""))
        lines.append(self._inner_box_bottom())
        lines.append(self._empty_line())

        # Containers section
        if containers:
            lines.append(self._inner_box_top("CONTAINERS"))
            lines.append(self._inner_box_line(""))

            # Group containers in rows of 3
            for i in range(0, len(containers), 3):
                chunk = containers[i:i+3]
                parts = []
                for c in chunk:
                    status_char = self._format_container_status(c.status)
                    parts.append(f"{status_char} {c.name[:10]:<10}")
                line = "  ".join(parts)
                lines.append(self._inner_box_line(line))

            # Show stopped containers separately
            stopped = [c for c in containers if c.status == ContainerStatus.STOPPED]
            for c in stopped:
                lines.append(self._inner_box_line(f"  {c.name} (stopped {c.uptime})"))

            lines.append(self._inner_box_line(""))
            lines.append(self._inner_box_bottom())
            lines.append(self._empty_line())

        # Alerts section
        alert_count = len(alerts)
        if alert_count > 0:
            lines.append(self._inner_box_top(f"ALERTS ({alert_count})"))
            for alert in alerts[:5]:  # Max 5 alerts
                line = f"[{alert.level}] {alert.message[:28]}"
                lines.append(self._inner_box_line(line))
            lines.append(self._inner_box_bottom())
            lines.append(self._empty_line())

        # Footer
        lines.append(self._separator())
        footer1 = f"Last alert: {alerts[0].message[:20] if alerts else 'None'}..."
        footer2 = f"Auto-refresh: {refresh_interval}s"
        lines.append(self._pad_line(f"> {footer1[:35]}"))
        lines.append(self._pad_line(f"> {footer2}"))
        lines.append(self._bottom_border())

        return "\n".join(lines)

    def render_minimal(self, servers: list[ServerMetrics]) -> str:
        """Render minimal status view."""
        now = datetime.utcnow()
        time_str = now.strftime("%H:%M:%S")

        lines = [
            f"{self.TOP_LEFT}{self.HORIZONTAL * 30}{self.TOP_RIGHT}",
            f"{self.VERTICAL}  QUICK STATUS  {time_str}   {self.VERTICAL}",
            f"{self.T_RIGHT}{self.HORIZONTAL * 30}{self.T_LEFT}",
        ]

        for server in servers:
            stat = self._format_status(server.status)
            cpu = self._format_percent(server.cpu_percent)
            name = server.name[:14].ljust(14)
            lines.append(f"{self.VERTICAL} {stat} {name} {cpu:>4}   {self.VERTICAL}")

        lines.append(f"{self.BOTTOM_LEFT}{self.HORIZONTAL * 30}{self.BOTTOM_RIGHT}")

        return "\n".join(lines)

    def render_alert(self, alert: Alert, server: str = None) -> str:
        """Render single alert notification."""
        now = datetime.utcnow()
        time_str = now.strftime("%H:%M:%S")

        level_marker = "!!" if alert.level == "!" else "i "
        server_str = f" on {server}" if server else ""

        lines = [
            f"{self.TOP_LEFT}{self.HORIZONTAL * 40}{self.TOP_RIGHT}",
            f"{self.VERTICAL}  [{level_marker}] ALERT  {time_str}             {self.VERTICAL}",
            f"{self.T_RIGHT}{self.HORIZONTAL * 40}{self.T_LEFT}",
            f"{self.VERTICAL}                                        {self.VERTICAL}",
            f"{self.VERTICAL}  {alert.message[:36]:<36}  {self.VERTICAL}",
            f"{self.VERTICAL}  {server_str:<36}  {self.VERTICAL}",
            f"{self.VERTICAL}                                        {self.VERTICAL}",
            f"{self.BOTTOM_LEFT}{self.HORIZONTAL * 40}{self.BOTTOM_RIGHT}",
        ]

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
