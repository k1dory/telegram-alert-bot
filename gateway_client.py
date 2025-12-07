"""
Gateway API client for communicating with Infra AI Platform.
"""

import httpx
import asyncio
from typing import Optional, Any
from dataclasses import dataclass
from datetime import datetime
import structlog

from config import settings
from dashboard import ServerMetrics, ContainerInfo, NodeStatus, ContainerStatus

logger = structlog.get_logger()


@dataclass
class CommandConfirmation:
    """2FA command confirmation request."""
    confirmation_id: str
    command: str
    target: str
    level: str
    user_id: str
    timestamp: datetime
    expires_at: datetime


@dataclass
class SystemStatus:
    """System status from gateway."""
    status: str
    version: str
    uptime: int
    servers: list[ServerMetrics]
    containers: list[ContainerInfo]


class GatewayClient:
    """Client for Gateway API communication."""

    def __init__(self):
        self.base_url = settings.gateway_url.rstrip("/")
        self.token = settings.gateway_token
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=30.0
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        json: Any = None,
        params: dict = None
    ) -> dict:
        """Make API request."""
        client = await self._get_client()
        try:
            response = await client.request(
                method=method,
                url=path,
                json=json,
                params=params
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("API error", status=e.response.status_code, path=path)
            raise
        except httpx.RequestError as e:
            logger.error("Request failed", error=str(e), path=path)
            raise

    # === System Status ===

    async def get_status(self) -> SystemStatus:
        """Get system status."""
        data = await self._request("GET", "/api/v1/system/status")

        servers = []
        for name, info in data.get("servers", {}).items():
            status = NodeStatus.OK
            if info.get("status") == "offline":
                status = NodeStatus.OFFLINE
            elif info.get("cpu_percent", 0) > 80:
                status = NodeStatus.WARNING

            servers.append(ServerMetrics(
                name=name,
                cpu_percent=info.get("cpu_percent"),
                mem_percent=info.get("memory_percent"),
                disk_percent=info.get("disk_percent"),
                status=status
            ))

        containers = []
        for name, info in data.get("containers", {}).items():
            status_str = info.get("status", "unknown")
            if status_str == "running":
                status = ContainerStatus.RUNNING
            elif status_str == "stopped":
                status = ContainerStatus.STOPPED
            elif status_str == "restarting":
                status = ContainerStatus.RESTARTING
            else:
                status = ContainerStatus.ERROR

            containers.append(ContainerInfo(
                name=name,
                status=status,
                uptime=info.get("uptime", "unknown")
            ))

        return SystemStatus(
            status=data.get("status", "unknown"),
            version=data.get("version", "unknown"),
            uptime=data.get("uptime", 0),
            servers=servers,
            containers=containers
        )

    async def get_servers(self) -> list[dict]:
        """Get list of servers."""
        data = await self._request("GET", "/api/v1/servers")
        return data.get("servers", [])

    # === Command Execution ===

    async def execute_command(
        self,
        target: str,
        command: str,
        level: str,
        confirmation_id: Optional[str] = None
    ) -> dict:
        """Execute command on target server."""
        payload = {
            "target": target,
            "command": command,
            "level": level,
        }
        if confirmation_id:
            payload["confirmation_id"] = confirmation_id

        return await self._request("POST", "/api/v1/commands/execute", json=payload)

    # === 2FA Confirmations ===

    async def get_pending_confirmations(self, user_id: str) -> list[CommandConfirmation]:
        """Get pending 2FA confirmations for user."""
        data = await self._request(
            "GET",
            "/api/v1/confirmations/pending",
            params={"user_id": user_id}
        )

        confirmations = []
        for item in data.get("confirmations", []):
            confirmations.append(CommandConfirmation(
                confirmation_id=item["id"],
                command=item["command"],
                target=item["target"],
                level=item["level"],
                user_id=item["user_id"],
                timestamp=datetime.fromisoformat(item["timestamp"]),
                expires_at=datetime.fromisoformat(item["expires_at"])
            ))

        return confirmations

    async def approve_confirmation(self, confirmation_id: str) -> dict:
        """Approve 2FA confirmation."""
        return await self._request(
            "POST",
            f"/api/v1/confirmations/{confirmation_id}/approve"
        )

    async def deny_confirmation(self, confirmation_id: str) -> dict:
        """Deny 2FA confirmation."""
        return await self._request(
            "POST",
            f"/api/v1/confirmations/{confirmation_id}/deny"
        )

    # === Alerts ===

    async def get_alerts(self, limit: int = 10) -> list[dict]:
        """Get recent alerts."""
        data = await self._request(
            "GET",
            "/api/v1/alerts",
            params={"limit": limit}
        )
        return data.get("alerts", [])

    async def acknowledge_alert(self, alert_id: str) -> dict:
        """Acknowledge an alert."""
        return await self._request(
            "POST",
            f"/api/v1/alerts/{alert_id}/acknowledge"
        )

    # === Logs ===

    async def get_logs(
        self,
        target: str,
        lines: int = 50,
        container: Optional[str] = None
    ) -> str:
        """Get logs from target."""
        params = {"lines": lines}
        if container:
            params["container"] = container

        data = await self._request(
            "GET",
            f"/api/v1/servers/{target}/logs",
            params=params
        )
        return data.get("logs", "")

    # === Docker ===

    async def list_containers(self, target: str) -> list[dict]:
        """List containers on target server."""
        data = await self._request("GET", f"/api/v1/servers/{target}/containers")
        return data.get("containers", [])

    async def container_action(
        self,
        target: str,
        container: str,
        action: str  # start, stop, restart
    ) -> dict:
        """Perform action on container."""
        return await self._request(
            "POST",
            f"/api/v1/servers/{target}/containers/{container}/{action}"
        )

    # === Health Check ===

    async def health_check(self) -> bool:
        """Check if gateway is healthy."""
        try:
            data = await self._request("GET", "/health")
            return data.get("status") == "healthy"
        except Exception:
            return False


# Global client instance
gateway = GatewayClient()
