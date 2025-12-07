"""
Environment discovery module.
Supports automatic Docker/container discovery or manual configuration.
"""

import asyncio
from typing import Optional
from dataclasses import dataclass
import structlog

from config import settings, DiscoveryMode
from dashboard import ServerMetrics, ContainerInfo, NodeStatus, ContainerStatus

logger = structlog.get_logger()


@dataclass
class DiscoveredEnvironment:
    """Discovered environment state."""
    servers: list[ServerMetrics]
    containers: list[ContainerInfo]
    discovery_time: float


class DockerDiscovery:
    """Docker container discovery."""

    def __init__(self):
        self._client = None

    async def _get_client(self):
        """Get Docker client (lazy init)."""
        if self._client is None:
            try:
                import docker
                self._client = docker.from_env()
            except Exception as e:
                logger.error("Failed to connect to Docker", error=str(e))
                return None
        return self._client

    async def discover_containers(self) -> list[ContainerInfo]:
        """Discover running Docker containers."""
        client = await self._get_client()
        if not client:
            return []

        containers = []
        try:
            for container in client.containers.list(all=True):
                # Parse status
                status_str = container.status.lower()
                if status_str == "running":
                    status = ContainerStatus.RUNNING
                elif status_str in ("exited", "stopped"):
                    status = ContainerStatus.STOPPED
                elif status_str == "restarting":
                    status = ContainerStatus.RESTARTING
                else:
                    status = ContainerStatus.ERROR

                # Calculate uptime
                uptime = self._format_uptime(container)

                containers.append(ContainerInfo(
                    name=container.name,
                    status=status,
                    uptime=uptime
                ))

        except Exception as e:
            logger.error("Failed to list containers", error=str(e))

        return containers

    def _format_uptime(self, container) -> str:
        """Format container uptime."""
        try:
            # Docker API returns status like "Up 2 hours" or "Exited (0) 3 hours ago"
            status = container.attrs.get("Status", "")
            if "Up" in status:
                parts = status.replace("Up ", "").split()
                if len(parts) >= 2:
                    return f"{parts[0]}{parts[1][0]}"  # "2h", "5d", etc.
            elif "Exited" in status or "ago" in status:
                parts = status.split()
                for i, p in enumerate(parts):
                    if p == "ago" and i >= 2:
                        return f"{parts[i-2]}{parts[i-1][0]} ago"
            return "unknown"
        except Exception:
            return "unknown"


class ManualDiscovery:
    """Manual environment configuration."""

    def __init__(self):
        self.servers = settings.servers

    async def get_servers(self) -> list[ServerMetrics]:
        """Get manually configured servers."""
        # In real implementation, would ping/check each server
        return [
            ServerMetrics(
                name=server,
                cpu_percent=None,
                mem_percent=None,
                disk_percent=None,
                status=NodeStatus.OFFLINE
            )
            for server in self.servers
        ]


class EnvironmentDiscovery:
    """Main discovery coordinator."""

    def __init__(self):
        self.mode = settings.discovery_mode
        self.docker = DockerDiscovery()
        self.manual = ManualDiscovery()
        self._cache: Optional[DiscoveredEnvironment] = None
        self._cache_ttl = 30  # seconds

    async def discover(self, force: bool = False) -> DiscoveredEnvironment:
        """Discover environment based on configured mode."""
        import time

        # Check cache
        if not force and self._cache:
            age = time.time() - self._cache.discovery_time
            if age < self._cache_ttl:
                return self._cache

        servers = []
        containers = []

        if self.mode == DiscoveryMode.AUTO:
            # Auto-discover Docker containers
            containers = await self.docker.discover_containers()

            # Try to discover local server
            servers = [await self._discover_local_server()]

        else:
            # Manual mode - use configured servers
            servers = await self.manual.get_servers()

            # Still try to discover Docker if socket is configured
            if settings.docker_socket:
                containers = await self.docker.discover_containers()

        # Cache results
        self._cache = DiscoveredEnvironment(
            servers=servers,
            containers=containers,
            discovery_time=time.time()
        )

        return self._cache

    async def _discover_local_server(self) -> ServerMetrics:
        """Discover local server metrics."""
        try:
            import psutil

            return ServerMetrics(
                name="localhost",
                cpu_percent=psutil.cpu_percent(),
                mem_percent=psutil.virtual_memory().percent,
                disk_percent=psutil.disk_usage('/').percent,
                status=NodeStatus.OK
            )
        except ImportError:
            return ServerMetrics(
                name="localhost",
                status=NodeStatus.OK
            )
        except Exception as e:
            logger.warning("Failed to get local metrics", error=str(e))
            return ServerMetrics(
                name="localhost",
                status=NodeStatus.WARNING
            )

    def set_mode(self, mode: DiscoveryMode):
        """Change discovery mode."""
        self.mode = mode
        self._cache = None  # Clear cache

    def add_server(self, server: str):
        """Add server to manual list."""
        if server not in self.manual.servers:
            self.manual.servers.append(server)
            self._cache = None

    def remove_server(self, server: str):
        """Remove server from manual list."""
        if server in self.manual.servers:
            self.manual.servers.remove(server)
            self._cache = None


# Global instance
discovery = EnvironmentDiscovery()
