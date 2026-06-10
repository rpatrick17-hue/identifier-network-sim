"""Test Server – 业务测试服务器.

Provides:
    - Application-layer traffic generation (HTTP / FTP / Video streaming).
    - Performance measurement (bandwidth, latency, jitter).
    - Identifier-network packet construction and monitoring.

In simulation mode the payloads are synthetic; the server tracks
send / receive timestamps to compute per-flow statistics.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from ..common.constants import DEFAULT_TTL, DataType
from ..common.addressing import AID, RID
from ..common.ethernet import EthernetFrame
from ..common.packets import AIDPacket, RIDPacket
from ..common.utils import MetricsAccumulator
from .base_node import BaseNode


@dataclass
class FlowStats:
    """Per-flow measurement data."""
    flow_id: str
    start_time: float = field(default_factory=time.time)
    sent_bytes: int = 0
    recv_bytes: int = 0
    sent_packets: int = 0
    recv_packets: int = 0
    rtt_samples: list[float] = field(default_factory=list)
    seq_nr: int = 0

    @property
    def throughput_mbps(self) -> float:
        elapsed = time.time() - self.start_time
        return (self.recv_bytes * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0

    @property
    def avg_rtt_ms(self) -> float:
        if not self.rtt_samples:
            return 0.0
        return sum(self.rtt_samples) / len(self.rtt_samples) * 1000

    @property
    def jitter_ms(self) -> float:
        if len(self.rtt_samples) < 2:
            return 0.0
        avg = sum(self.rtt_samples) / len(self.rtt_samples)
        var = sum((s - avg) ** 2 for s in self.rtt_samples) / len(self.rtt_samples)
        return (var ** 0.5) * 1000


class TestServer(BaseNode):
    """业务测试服务器 – 流量生成 & 性能监测."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name=name)
        self.aid: Optional[AID] = None
        self.rid: Optional[RID] = None
        self._flows: dict[str, FlowStats] = {}
        self._active_traffic: bool = False
        self._iface_idx: int = -1

        # Service simulation
        self._http_pages: list[bytes] = []  # synthetic HTTP response bodies
        self._ftp_files: dict[str, bytes] = {}  # filename → content
        self._video_chunks: list[bytes] = []  # synthetic video segments

    # ==================================================================
    #  Traffic generation
    # ==================================================================

    async def start_http_server(self, page_size: int = 1024, num_pages: int = 5) -> None:
        """Generate synthetic HTTP pages."""
        for i in range(num_pages):
            content = f"<html><body><h1>Page {i}</h1>{'X' * page_size}</body></html>"
            self._http_pages.append(content.encode("utf-8"))
        self.logger.info(f"HTTP server ready: {num_pages} pages")

    async def start_ftp_server(self, file_count: int = 3, file_size: int = 100_000) -> None:
        """Generate synthetic FTP files."""
        for i in range(file_count):
            content = bytes([random.randint(0, 255) for _ in range(file_size)])
            self._ftp_files[f"file_{i}.bin"] = content
        self.logger.info(f"FTP server ready: {file_count} files")

    async def start_video_server(self, chunk_count: int = 10, chunk_size: int = 50_000) -> None:
        """Generate synthetic video chunks."""
        for i in range(chunk_count):
            self._video_chunks.append(
                bytes([random.randint(0, 255) for _ in range(chunk_size)])
            )
        self.logger.info(f"Video server ready: {chunk_count} chunks")

    async def send_http_response(
        self, dst_aid: AID, page_index: int = 0, dst_mac: str = "ff:ff:ff:ff:ff:ff"
    ) -> None:
        if not self._http_pages:
            return
        payload = self._http_pages[page_index % len(self._http_pages)]
        aid_pkt = AIDPacket(
            source_aid=self.aid or AID(0),
            destination_aid=dst_aid,
            payload=payload,
            data_type=DataType.USER_DATA,
            ttl=DEFAULT_TTL,
        )
        await self.send_aid_packet(self._iface_idx, aid_pkt, bytes.fromhex(dst_mac.replace(":", "")))
        self.logger.debug(f"HTTP response → {dst_aid}, {len(payload)}B")

    async def send_probe_packet(
        self, dst_aid: AID, seq: int, dst_mac: str = "ff:ff:ff:ff:ff:ff"
    ) -> float:
        """Send a latency-probe packet; returns send timestamp."""
        ts = time.time()
        # Embed timestamp & seq in payload for RTT measurement
        payload = f"PROBE:{seq}:{ts}".encode("utf-8")
        aid_pkt = AIDPacket(
            source_aid=self.aid or AID(0),
            destination_aid=dst_aid,
            payload=payload,
            data_type=DataType.USER_DATA,
            ttl=DEFAULT_TTL,
        )
        await self.send_aid_packet(self._iface_idx, aid_pkt, bytes.fromhex(dst_mac.replace(":", "")))
        return ts

    # ==================================================================
    #  Packet monitoring
    # ==================================================================

    async def on_frame(self, iface_idx: int, frame: EthernetFrame) -> None:
        if frame.is_aid:
            aid_pkt = frame.inner_aid()
            self._record_recv(aid_pkt)

    def _record_recv(self, pkt: AIDPacket) -> None:
        """Parse and record statistics from received packet."""
        try:
            text = pkt.payload.decode("utf-8")
            if text.startswith("PROBE:"):
                parts = text.split(":")
                seq = int(parts[1])
                send_ts = float(parts[2])
                rtt = time.time() - send_ts
                flow = self._get_flow(f"probe-{pkt.source_aid}")
                flow.rtt_samples.append(rtt)
                flow.recv_packets += 1
                flow.recv_bytes += len(pkt.payload)
                flow.seq_nr = seq
                self.logger.trace(f"probe seq={seq} rtt={rtt*1000:.2f}ms")
        except (ValueError, UnicodeDecodeError):
            pass
        self.metrics.record_recv(len(pkt.payload))

    def _get_flow(self, flow_id: str) -> FlowStats:
        if flow_id not in self._flows:
            self._flows[flow_id] = FlowStats(flow_id=flow_id)
        return self._flows[flow_id]

    # ==================================================================
    #  Statistics
    # ==================================================================

    def stats_summary(self) -> str:
        lines = [f"TestServer({self.name}) statistics:", "-" * 50]
        for fid, flow in self._flows.items():
            lines.append(
                f"  {fid}: pkts={flow.recv_packets}, "
                f"throughput={flow.throughput_mbps:.2f}Mbps, "
                f"rtt_avg={flow.avg_rtt_ms:.2f}ms, "
                f"jitter={flow.jitter_ms:.2f}ms"
            )
        lines.append(f"  total: {self.metrics.summary()}")
        return "\n".join(lines)

    # ==================================================================
    #  Lifecycle
    # ==================================================================

    async def on_start(self) -> None:
        self._iface_idx = 0 if self.interfaces else -1
        self.logger.info(f"TestServer started, aid={self.aid}")
