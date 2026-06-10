"""Real network interface using AF_PACKET raw sockets.

Replaces VirtualLink/VirtualSwitch with actual Linux network interfaces
(veth pairs in network namespaces).  This allows the simulation to:

- Send/receive real Ethernet frames through the kernel
- Be inspected with tcpdump/Wireshark
- Connect to real physical devices by adding them to the bridge

Architecture
------------
Each node opens an AF_PACKET socket on its veth interface.  Sockets are
polled via asyncio (using loop.add_reader).  Frames are dispatched to
the node's on_frame handler exactly as in the Queue-based simulation.

The socket receives ALL Ethernet frames (ETH_P_ALL), bypassing the
kernel IP stack, giving us raw L2 access.
"""

from __future__ import annotations

import asyncio
import socket
import struct
from typing import Optional

from loguru import logger

# Ethernet header unpack (for debug)
ETH_HEADER_UNPACK = struct.Struct("!6s6sH")

# ETH_P_ALL — receive all Ethernet protocols
ETH_P_ALL = 0x0003

# SO_ATTACH_FILTER is not always available; use BPF for performance if needed
# For simplicity we receive everything and filter in Python


class RawSocket:
    """AF_PACKET raw socket bound to a specific interface.

    Provides async-compatible send/recv of raw Ethernet frames.
    """

    def __init__(self, ifname: str, mtu: int = 1500):
        self.ifname = ifname
        self.mtu = mtu
        self._sock: Optional[socket.socket] = None
        self._recv_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1000)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._rx_bytes = 0
        self._tx_bytes = 0
        self._rx_pkts = 0
        self._tx_pkts = 0

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        """Create and bind the raw socket."""
        self._sock = socket.socket(
            socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL)
        )
        self._sock.bind((self.ifname, 0))
        self._sock.setblocking(False)
        logger.info(f"[{self.ifname}] raw socket opened")

    def close(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()
            self._sock = None
        logger.debug(f"[{self.ifname}] raw socket closed")

    # -- asyncio integration -----------------------------------------------

    def start_recv_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register this socket's fd with the asyncio event loop."""
        self._loop = loop
        self._running = True
        loop.add_reader(self._sock.fileno(), self._on_readable)

    def stop_recv_loop(self) -> None:
        self._running = False
        if self._loop and self._sock:
            try:
                self._loop.remove_reader(self._sock.fileno())
            except Exception:
                pass

    def _on_readable(self) -> None:
        """Called by the event loop when the socket has data."""
        if not self._running or not self._sock:
            return
        try:
            data = self._sock.recv(self.mtu + 14)  # ETH header + payload
            if data:
                self._rx_bytes += len(data)
                self._rx_pkts += 1
                # Put in queue for async consumption
                try:
                    self._recv_queue.put_nowait(data)
                except asyncio.QueueFull:
                    logger.warning(f"[{self.ifname}] recv queue full, dropping")
        except BlockingIOError:
            pass  # no data
        except OSError as e:
            logger.error(f"[{self.ifname}] recv error: {e}")

    # -- send / recv -------------------------------------------------------

    def send(self, data: bytes) -> bool:
        """Send a raw Ethernet frame. Returns True on success."""
        if not self._sock:
            return False
        try:
            n = self._sock.send(data)
            self._tx_bytes += n
            self._tx_pkts += 1
            return n > 0
        except OSError as e:
            logger.error(f"[{self.ifname}] send error: {e}")
            return False

    async def recv(self, timeout: float | None = None) -> Optional[bytes]:
        """Async receive — get next frame from the internal queue."""
        try:
            if timeout is not None:
                return await asyncio.wait_for(self._recv_queue.get(), timeout=timeout)
            return await self._recv_queue.get()
        except asyncio.TimeoutError:
            return None

    # -- stats -------------------------------------------------------------

    @property
    def stats(self) -> dict:
        return {
            "interface": self.ifname,
            "rx_packets": self._rx_pkts,
            "tx_packets": self._tx_pkts,
            "rx_bytes": self._rx_bytes,
            "tx_bytes": self._tx_bytes,
        }

    def __repr__(self) -> str:
        return f"RawSocket({self.ifname}, rx={self._rx_pkts}, tx={self._tx_pkts})"


# ═══════════════════════════════════════════════════════════════
#  Multi-interface poller — one event loop for many sockets
# ═══════════════════════════════════════════════════════════════

class InterfacePoller:
    """Manages multiple RawSocket instances in a single asyncio loop.

    Each socket's fd is registered with loop.add_reader, so incoming
    frames are delivered to the socket's internal queue without busy-waiting.
    """

    def __init__(self):
        self.sockets: dict[str, RawSocket] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def add(self, name: str, sock: RawSocket) -> None:
        self.sockets[name] = sock
        if self._loop:
            sock.start_recv_loop(self._loop)

    def remove(self, name: str) -> None:
        sock = self.sockets.pop(name, None)
        if sock:
            sock.stop_recv_loop()
            sock.close()

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        for sock in self.sockets.values():
            sock.start_recv_loop(loop)

    def stop(self) -> None:
        for sock in self.sockets.values():
            sock.stop_recv_loop()

    async def recv_from(self, name: str, timeout: float | None = None) -> Optional[bytes]:
        sock = self.sockets.get(name)
        if sock is None:
            return None
        return await sock.recv(timeout=timeout)

    def send_to(self, name: str, data: bytes) -> bool:
        sock = self.sockets.get(name)
        if sock is None:
            return False
        return sock.send(data)

    def summary(self) -> str:
        lines = ["InterfacePoller:"]
        for name, sock in self.sockets.items():
            s = sock.stats
            lines.append(f"  {name}: rx={s['rx_packets']} tx={s['tx_packets']} "
                         f"rxB={s['rx_bytes']} txB={s['tx_bytes']}")
        return "\n".join(lines)
