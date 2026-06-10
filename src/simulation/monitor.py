"""Performance monitor – collects real-time stats from all nodes.

Provides Prometheus-compatible metrics as well as a simple
text-based dashboard for quick debugging.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List

from loguru import logger

from .topology import Topology


@dataclass
class NodeSnapshot:
    name: str
    node_type: str
    uptime: float
    sent_packets: int
    recv_packets: int
    sent_bytes: int
    recv_bytes: int
    throughput_mbps: float
    avg_rtt_ms: float
    jitter_ms: float
    timestamp: float = field(default_factory=time.time)


class Monitor:
    """Periodically snapshot all node metrics."""

    def __init__(self, topology: Topology, interval: float = 1.0):
        self.topology = topology
        self.interval = interval
        self.history: List[Dict[str, NodeSnapshot]] = []

    async def collect(self) -> Dict[str, NodeSnapshot]:
        """Take a snapshot of every node's metrics."""
        snapshots: Dict[str, NodeSnapshot] = {}
        for name, node in self.topology.nodes.items():
            m = node.metrics.summary()
            snapshots[name] = NodeSnapshot(
                name=name,
                node_type=type(node).__name__,
                uptime=m["elapsed_s"],
                sent_packets=m["sent_packets"],
                recv_packets=m["recv_packets"],
                sent_bytes=m["sent_bytes"],
                recv_bytes=m["recv_bytes"],
                throughput_mbps=m["throughput_mbps"],
                avg_rtt_ms=m["avg_rtt_ms"],
                jitter_ms=m["jitter_ms"],
            )
        self.history.append(snapshots)
        return snapshots

    def render_dashboard(self, snapshots: Dict[str, NodeSnapshot]) -> str:
        """Render a simple text dashboard."""
        now = time.strftime("%H:%M:%S")
        lines = [
            f"╔══ Monitor @ {now} ═══════════════════════════════════════════╗",
        ]
        for name, s in snapshots.items():
            line = (
                f"║ {s.node_type:<14s} {name:<12s} "
                f"tx={s.sent_bytes:>8d}B rx={s.recv_bytes:>8d}B"
            )
            if s.throughput_mbps > 0:
                line += f"  {s.throughput_mbps:.1f}Mbps"
            if s.avg_rtt_ms > 0:
                line += f"  RTT={s.avg_rtt_ms:.1f}ms"
            line += " ║"
            lines.append(line)
        lines.append("╚" + "═" * 68 + "╝")
        return "\n".join(lines)

    async def run_forever(self) -> None:
        """Continuously collect and print stats."""
        while True:
            snap = await self.collect()
            print(self.render_dashboard(snap))
            await __import__("asyncio").sleep(self.interval)
