"""Small utilities: logging setup, hash helpers, timer."""

from __future__ import annotations

import asyncio
import hashlib
import sys
import time
from typing import Callable, Coroutine

from loguru import logger as _logger


# ============================================================================
#  Logging
# ============================================================================

def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Configure loguru for the simulation."""
    _logger.remove()
    _logger.add(
        sink=sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan> | "
        "<level>{message}</level>",
    )
    if log_file:
        _logger.add(log_file, level="DEBUG", rotation="10 MB", retention="3 days")


logger = _logger


# ============================================================================
#  AID generation
# ============================================================================

def generate_aid(username: str, pin: str = "", device_id: str = "") -> bytes:
    """Generate 128-bit AID from user attributes (SHA-256 truncated)."""
    material = f"{username}:{pin}:{device_id}".encode("utf-8")
    return hashlib.sha256(material).digest()[:16]


# ============================================================================
#  MAC generation
# ============================================================================

def random_mac(prefix: str = "00:00:00") -> str:
    """Generate a random unicast MAC with given OUI prefix."""
    import random

    suffix = ":".join(f"{random.randint(0, 255):02x}" for _ in range(3))
    return f"{prefix}:{suffix}"


# ============================================================================
#  Lightweight periodic timer for asyncio tasks
# ============================================================================

class PeriodicTimer:
    """Fire a callback at a fixed interval (runs inside the node's loop)."""

    def __init__(self, interval: float, callback: Callable[[], Coroutine], name: str = ""):
        self.interval = interval
        self.callback = callback
        self.name = name
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval)
                break  # stopped
            except asyncio.TimeoutError:
                await self.callback()

    def start(self) -> None:
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()

    def __repr__(self) -> str:
        return f"PeriodicTimer({self.name or self.interval}s)"


# ============================================================================
#  Performance metrics accumulator
# ============================================================================

class MetricsAccumulator:
    """Collect per-flow bandwidth / latency / jitter statistics."""

    def __init__(self) -> None:
        self._sent_packets: int = 0
        self._sent_bytes: int = 0
        self._recv_packets: int = 0
        self._recv_bytes: int = 0
        self._rtt_samples: list[float] = []
        self._start_time: float = time.time()

    # -- record --------------------------------------------------------------

    def record_send(self, n_bytes: int) -> None:
        self._sent_packets += 1
        self._sent_bytes += n_bytes

    def record_recv(self, n_bytes: int, rtt: float | None = None) -> None:
        self._recv_packets += 1
        self._recv_bytes += n_bytes
        if rtt is not None:
            self._rtt_samples.append(rtt)

    # -- query ---------------------------------------------------------------

    @property
    def elapsed(self) -> float:
        return time.time() - self._start_time

    @property
    def throughput_mbps(self) -> float:
        elapsed = self.elapsed
        if elapsed == 0:
            return 0.0
        return (self._recv_bytes * 8) / (elapsed * 1_000_000)

    @property
    def packet_loss_rate(self) -> float:
        if self._sent_packets == 0:
            return 0.0
        return 1.0 - (self._recv_packets / self._sent_packets)

    @property
    def avg_rtt_ms(self) -> float:
        if not self._rtt_samples:
            return 0.0
        return sum(self._rtt_samples) / len(self._rtt_samples) * 1000

    @property
    def jitter_ms(self) -> float:
        """Std-dev of RTT as a simple jitter proxy."""
        if len(self._rtt_samples) < 2:
            return 0.0
        avg = sum(self._rtt_samples) / len(self._rtt_samples)
        var = sum((s - avg) ** 2 for s in self._rtt_samples) / len(self._rtt_samples)
        return (var ** 0.5) * 1000

    def summary(self) -> dict:
        return {
            "sent_packets": self._sent_packets,
            "recv_packets": self._recv_packets,
            "sent_bytes": self._sent_bytes,
            "recv_bytes": self._recv_bytes,
            "throughput_mbps": round(self.throughput_mbps, 3),
            "packet_loss_rate": round(self.packet_loss_rate, 4),
            "avg_rtt_ms": round(self.avg_rtt_ms, 3),
            "jitter_ms": round(self.jitter_ms, 3),
            "elapsed_s": round(self.elapsed, 1),
        }
