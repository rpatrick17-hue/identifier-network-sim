"""Test Server – 业务测试服务器.

Provides:
    - Application-layer traffic generation (HTTP / FTP / Video streaming).
    - Performance measurement (bandwidth, latency, jitter).
    - Identifier-network packet construction and monitoring.
    - RID probe packets for CR core-forwarding verification.

In simulation mode the payloads are synthetic; the server tracks
send / receive timestamps to compute per-flow statistics.

Task spec ref: §4.2.1 (标识组网), §6.2 表11 (TS 功能需求)
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
    lost_packets: int = 0

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

    @property
    def loss_rate_pct(self) -> float:
        if self.sent_packets == 0:
            return 0.0
        return (self.lost_packets / self.sent_packets) * 100


class TestServer(BaseNode):
    """业务测试服务器 – 流量生成 & 性能监测.

    Per task spec §6.2 表11:
      (1) 部署用户网页、文件、视频提供等功能
      (2) 支持网络带宽、时延抖动等测试功能
      (3) 具备标识数据包构建和收发监测功能
    """

    def __init__(self, name: str = "") -> None:
        super().__init__(name=name)
        self.aid: Optional[AID] = None
        self.rid: Optional[RID] = None
        self._flows: dict[str, FlowStats] = {}
        self._active_traffic: bool = False
        self._iface_idx: int = -1

        # Service simulation
        self._http_pages: list[bytes] = []
        self._ftp_files: dict[str, bytes] = {}
        self._video_chunks: list[bytes] = []

        # Monitoring state
        self._monitor_task: Optional[asyncio.Task] = None
        self._monitor_interval: float = 2.0
        self._packet_counts: dict[str, int] = {"aid_rx": 0, "rid_rx": 0, "probe_rx": 0}

    # ==================================================================
    #  Service simulation  (§6.2 表11 item 1)
    # ==================================================================

    async def start_http_server(self, page_size: int = 1024, num_pages: int = 5) -> None:
        """Generate synthetic HTTP pages."""
        for i in range(num_pages):
            content = f"<html><body><h1>Page {i}</h1>{'X' * page_size}</body></html>"
            self._http_pages.append(content.encode("utf-8"))
        self.logger.info(f"HTTP server ready: {num_pages} pages × {page_size}B")

    async def start_ftp_server(self, file_count: int = 3, file_size: int = 100_000) -> None:
        """Generate synthetic FTP files."""
        for i in range(file_count):
            content = bytes([random.randint(0, 255) for _ in range(file_size)])
            self._ftp_files[f"file_{i}.bin"] = content
        self.logger.info(f"FTP server ready: {file_count} files × {file_size}B")

    async def start_video_server(self, chunk_count: int = 10, chunk_size: int = 50_000) -> None:
        """Generate synthetic video chunks."""
        for i in range(chunk_count):
            self._video_chunks.append(
                bytes([random.randint(0, 255) for _ in range(chunk_size)])
            )
        self.logger.info(f"Video server ready: {chunk_count} chunks × {chunk_size}B")

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

    # ==================================================================
    #  Probe packets  (§6.2 表11 item 3 — 标识数据包构建)
    # ==================================================================

    async def send_aid_probe(
        self, dst_aid: AID, seq: int, dst_mac: str = "ff:ff:ff:ff:ff:ff"
    ) -> float:
        """Send an AID-format latency probe; returns send timestamp.

        Used for access-network (AID domain) reachability testing.
        """
        ts = time.time()
        payload = f"PROBE:AID:{seq}:{ts}".encode("utf-8")
        aid_pkt = AIDPacket(
            source_aid=self.aid or AID(0),
            destination_aid=dst_aid,
            payload=payload,
            data_type=DataType.USER_DATA,
            ttl=DEFAULT_TTL,
        )
        await self.send_aid_packet(self._iface_idx, aid_pkt, bytes.fromhex(dst_mac.replace(":", "")))
        flow = self._get_flow(f"aid-probe-{dst_aid}")
        flow.sent_packets += 1
        flow.sent_bytes += len(payload)
        return ts

    async def send_rid_probe(
        self,
        dst_rid: RID,
        seq: int,
        space_id: int = 100,
        dst_mac: str = "ff:ff:ff:ff:ff:ff",
    ) -> float:
        """Send a RID-format probe to test CR core-forwarding.

        Builds a raw RID packet (NOT AID-encapsulated) and sends it
        directly into the core network.  The destination CR should
        recognize the probe and echo it back (if probe-echo is enabled)
        or the CR can be monitored via tcpdump for receipt.

        Task spec ref: §4.2.1 标识组网验证.
        """
        ts = time.time()
        payload = f"PROBE:RID:{seq}:{ts}:{self.rid or RID(0,0)}".encode("utf-8")
        rid_pkt = RIDPacket(
            source_rid=self.rid or RID(0, 0),
            destination_rid=dst_rid,
            payload=payload,
            network_space_id=space_id,
            data_type=DataType.USER_DATA,
            ttl=DEFAULT_TTL,
        )
        await self.send_rid_packet(self._iface_idx, rid_pkt, bytes.fromhex(dst_mac.replace(":", "")))
        flow = self._get_flow(f"rid-probe-{dst_rid}")
        flow.sent_packets += 1
        flow.sent_bytes += len(payload)
        self.logger.debug(f"RID probe seq={seq} → {dst_rid} space={space_id}")
        return ts

    # ==================================================================
    #  Bandwidth test  (§6.2 表11 item 2)
    # ==================================================================

    async def run_bandwidth_test(
        self,
        dst_aid: AID,
        duration_s: float = 5.0,
        packet_size: int = 1400,
        packets_per_sec: int = 100,
        dst_mac: str = "ff:ff:ff:ff:ff:ff",
    ) -> dict:
        """Send bulk data at a controlled rate; return throughput stats.

        This is a sender-side bandwidth test.  For full-duplex testing,
        pair with a receiver that echoes or counts packets.
        """
        flow_id = f"bw-test-{dst_aid}"
        flow = self._get_flow(flow_id)
        flow.start_time = time.time()

        total_packets = int(duration_s * packets_per_sec)
        interval = 1.0 / packets_per_sec if packets_per_sec > 0 else 0.01
        payload = bytes([random.randint(0, 255) for _ in range(packet_size)])

        self.logger.info(
            f"Bandwidth test start: {total_packets} pkts × {packet_size}B "
            f"over {duration_s}s → {dst_aid}"
        )

        for seq in range(total_packets):
            ts = time.time()
            pkt_payload = f"BW:{seq}:{ts}:".encode("utf-8") + payload[20:]
            aid_pkt = AIDPacket(
                source_aid=self.aid or AID(0),
                destination_aid=dst_aid,
                payload=pkt_payload,
                data_type=DataType.USER_DATA,
                ttl=DEFAULT_TTL,
            )
            await self.send_aid_packet(
                self._iface_idx, aid_pkt, bytes.fromhex(dst_mac.replace(":", ""))
            )
            flow.sent_packets += 1
            flow.sent_bytes += len(pkt_payload)

            # Rate-limit
            elapsed = time.time() - ts
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)

        elapsed = time.time() - flow.start_time
        result = {
            "flow_id": flow_id,
            "duration_s": round(elapsed, 2),
            "sent_packets": flow.sent_packets,
            "sent_bytes": flow.sent_bytes,
            "throughput_mbps": round(flow.throughput_mbps, 3),
            "packets_per_sec": round(flow.sent_packets / elapsed, 1) if elapsed > 0 else 0,
        }
        self.logger.info(f"Bandwidth test done: {result}")
        return result

    # ==================================================================
    #  Latency / jitter test  (§6.2 表11 item 2)
    # ==================================================================

    async def run_latency_test(
        self,
        dst_aid: AID,
        num_probes: int = 20,
        interval_s: float = 0.1,
        dst_mac: str = "ff:ff:ff:ff:ff:ff",
    ) -> dict:
        """Send N AID probes; collect RTT/jitter stats from responses.

        Requires the destination to echo probes back (or the probes
        to be looped back by a CR/AP that recognizes PROBE: payloads).
        """
        flow_id = f"latency-{dst_aid}"
        flow = self._get_flow(flow_id)
        flow.start_time = time.time()
        flow.sent_packets = 0
        flow.recv_packets = 0
        flow.rtt_samples.clear()

        self.logger.info(f"Latency test start: {num_probes} probes → {dst_aid}")

        for seq in range(num_probes):
            await self.send_aid_probe(dst_aid, seq, dst_mac)
            await asyncio.sleep(interval_s)

        # Wait for responses
        await asyncio.sleep(1.0)

        result = {
            "flow_id": flow_id,
            "probes_sent": flow.sent_packets,
            "probes_recv": flow.recv_packets,
            "loss_rate_pct": round(flow.loss_rate_pct, 2),
            "avg_rtt_ms": round(flow.avg_rtt_ms, 2),
            "jitter_ms": round(flow.jitter_ms, 2),
            "min_rtt_ms": round(min(flow.rtt_samples) * 1000, 2) if flow.rtt_samples else 0,
            "max_rtt_ms": round(max(flow.rtt_samples) * 1000, 2) if flow.rtt_samples else 0,
        }
        self.logger.info(f"Latency test done: {result}")
        return result

    # ==================================================================
    #  RID forwarding verification  (§4.2.1)
    # ==================================================================

    async def run_rid_forwarding_test(
        self,
        target_rids: list[RID],
        probes_per_target: int = 5,
        space_id: int = 100,
    ) -> dict:
        """Send RID probes to each target CR; verify core forwarding.

        This tests that CRs in the core network can receive RID packets.
        Verification is done via tcpdump on the CR side or by checking
        CR interface statistics.

        Returns per-target send counts.
        """
        results = {}
        self.logger.info(
            f"RID forwarding test: {len(target_rids)} targets × {probes_per_target} probes"
        )

        for target_rid in target_rids:
            flow_id = f"rid-fwd-{target_rid}"
            flow = self._get_flow(flow_id)
            for seq in range(probes_per_target):
                await self.send_rid_probe(target_rid, seq, space_id)
                await asyncio.sleep(0.05)
            results[str(target_rid)] = {
                "probes_sent": probes_per_target,
                "target_rid": target_rid.to_tuple(),
                "space_id": space_id,
            }
            self.logger.info(f"  RID fwd → {target_rid}: {probes_per_target} probes sent")

        return results

    # ==================================================================
    #  Test orchestrator
    # ==================================================================

    async def run_all_tests(
        self,
        dst_aid: Optional[AID] = None,
        target_rids: Optional[list[RID]] = None,
    ) -> dict:
        """Run a comprehensive test suite and return all results.

        Order:
          1. RID forwarding test (if target_rids provided)
          2. Latency test (if dst_aid provided)
          3. Bandwidth test (if dst_aid provided)
        """
        all_results: dict = {"timestamp": time.time()}

        # 1. RID forwarding
        if target_rids:
            all_results["rid_forwarding"] = await self.run_rid_forwarding_test(target_rids)

        # 2. Latency
        if dst_aid:
            all_results["latency"] = await self.run_latency_test(dst_aid)

        # 3. Bandwidth
        if dst_aid:
            all_results["bandwidth"] = await self.run_bandwidth_test(dst_aid, duration_s=3.0)

        # Print summary
        self.print_test_report(all_results)
        return all_results

    def print_test_report(self, results: dict) -> None:
        """Pretty-print test results."""
        lines = [
            "=" * 60,
            "  TS Test Report",
            "=" * 60,
        ]

        if "rid_forwarding" in results:
            lines.append("  [RID Forwarding Test]")
            for rid_str, r in results["rid_forwarding"].items():
                lines.append(f"    {rid_str}: {r['probes_sent']} probes sent")

        if "latency" in results:
            r = results["latency"]
            lines.append("  [Latency Test]")
            lines.append(f"    Sent/Recv: {r['probes_sent']}/{r['probes_recv']}")
            lines.append(f"    Loss:      {r['loss_rate_pct']}%")
            lines.append(f"    Avg RTT:   {r['avg_rtt_ms']} ms")
            lines.append(f"    Jitter:    {r['jitter_ms']} ms")
            lines.append(f"    Min/Max:   {r['min_rtt_ms']}/{r['max_rtt_ms']} ms")

        if "bandwidth" in results:
            r = results["bandwidth"]
            lines.append("  [Bandwidth Test]")
            lines.append(f"    Duration:  {r['duration_s']} s")
            lines.append(f"    Packets:   {r['sent_packets']}")
            lines.append(f"    Data:      {r['sent_bytes']} B")
            lines.append(f"    Throughput:{r['throughput_mbps']} Mbps")
            lines.append(f"    Pkt Rate:  {r['packets_per_sec']} pps")

        lines.append("=" * 60)
        for line in lines:
            self.logger.info(line)

    # ==================================================================
    #  Packet monitoring  (§6.2 表11 item 3 — 收发监测)
    # ==================================================================

    async def on_frame(self, iface_idx: int, frame: EthernetFrame) -> None:
        """Handle incoming frames — both AID and RID."""
        if frame.is_aid:
            self._packet_counts["aid_rx"] += 1
            aid_pkt = frame.inner_aid()
            self._record_aid_recv(aid_pkt)
        elif frame.is_rid:
            self._packet_counts["rid_rx"] += 1
            rid_pkt = frame.inner_rid()
            self._record_rid_recv(rid_pkt)

    def _record_aid_recv(self, pkt: AIDPacket) -> None:
        """Parse AID packet; track probes and bandwidth test responses."""
        try:
            text = pkt.payload.decode("utf-8")
            if text.startswith("PROBE:"):
                self._packet_counts["probe_rx"] += 1
                parts = text.split(":")
                # PROBE:AID:seq:timestamp
                # PROBE:RID:seq:timestamp:src_rid
                probe_type = parts[1] if len(parts) > 1 else "?"
                seq = int(parts[2]) if len(parts) > 2 else 0
                send_ts = float(parts[3]) if len(parts) > 3 else 0.0
                rtt = time.time() - send_ts

                flow = self._get_flow(f"probe-{pkt.source_aid}")
                flow.rtt_samples.append(rtt)
                flow.recv_packets += 1
                flow.recv_bytes += len(pkt.payload)
                flow.seq_nr = seq
                self.logger.debug(
                    f"probe {probe_type} seq={seq} rtt={rtt*1000:.2f}ms"
                )
            elif text.startswith("BW:"):
                # BW:seq:timestamp:data...
                parts = text.split(":")
                seq = int(parts[1]) if len(parts) > 1 else 0
                flow = self._get_flow(f"bw-recv-{pkt.source_aid}")
                flow.recv_packets += 1
                flow.recv_bytes += len(pkt.payload)
                flow.seq_nr = seq
        except (ValueError, UnicodeDecodeError):
            pass
        self.metrics.record_recv(len(pkt.payload))

    def _record_rid_recv(self, pkt: RIDPacket) -> None:
        """Parse RID packet; track RID-level probes and statistics."""
        self.metrics.record_recv(len(pkt.payload))
        try:
            text = pkt.payload.decode("utf-8")
            if text.startswith("PROBE:RID:"):
                self._packet_counts["probe_rx"] += 1
                parts = text.split(":")
                seq = int(parts[2]) if len(parts) > 2 else 0
                send_ts = float(parts[3]) if len(parts) > 3 else 0.0
                rtt = time.time() - send_ts

                flow = self._get_flow(f"rid-echo-{pkt.source_rid}")
                flow.rtt_samples.append(rtt)
                flow.recv_packets += 1
                flow.recv_bytes += len(pkt.payload)
                flow.seq_nr = seq
                self.logger.debug(
                    f"RID echo seq={seq} from {pkt.source_rid} rtt={rtt*1000:.2f}ms"
                )
        except (ValueError, UnicodeDecodeError):
            pass

    def _get_flow(self, flow_id: str) -> FlowStats:
        if flow_id not in self._flows:
            self._flows[flow_id] = FlowStats(flow_id=flow_id)
        return self._flows[flow_id]

    # ==================================================================
    #  Live monitor  (§6.2 表11 item 3)
    # ==================================================================

    async def start_monitor(self, interval_s: float = 2.0) -> None:
        """Start a periodic statistics reporter."""
        self._monitor_interval = interval_s
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            self.logger.info(f"Monitor started (interval={interval_s}s)")

    async def stop_monitor(self) -> None:
        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None

    async def _monitor_loop(self) -> None:
        while True:
            await asyncio.sleep(self._monitor_interval)
            summary = self.monitor_summary()
            self.logger.info(summary)

    def monitor_summary(self) -> str:
        """One-line statistics snapshot."""
        m = self.metrics.summary()
        active_flows = len(self._flows)
        return (
            f"[TS Monitor] aid_rx={self._packet_counts['aid_rx']} "
            f"rid_rx={self._packet_counts['rid_rx']} "
            f"probes={self._packet_counts['probe_rx']} "
            f"flows={active_flows} "
            f"sent={m['sent_packets']}pkt/{m['sent_bytes']}B "
            f"recv={m['recv_packets']}pkt/{m['recv_bytes']}B"
        )

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
                f"jitter={flow.jitter_ms:.2f}ms, "
                f"loss={flow.loss_rate_pct:.1f}%"
            )
        lines.append(
            f"  monitor: aid_rx={self._packet_counts['aid_rx']}, "
            f"rid_rx={self._packet_counts['rid_rx']}, "
            f"probes={self._packet_counts['probe_rx']}"
        )
        lines.append(f"  total: {self.metrics.summary()}")
        return "\n".join(lines)

    # ==================================================================
    #  Lifecycle
    # ==================================================================

    async def on_start(self) -> None:
        self._iface_idx = 0 if self.interfaces else -1
        self.logger.info(f"TestServer started, aid={self.aid}, rid={self.rid}")
