"""Virtual link / switch layer for the Identifier Network simulation.

Provides two abstractions:

``VirtualLink``
    Point-to-point connection between two interfaces with optional delay
    and packet-loss injection.

``VirtualSwitch``
    Multi-port switch with MAC learning and **port isolation** rules.
    Used on the access side to enforce that AP-CR pairs are isolated
    from each other at L2.
"""

from __future__ import annotations

import asyncio
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from loguru import logger


# ============================================================================
#  VirtualLink  – point-to-point
# ============================================================================


class VirtualLink:
    """A unidirectional or bidirectional link between two endpoints.

    Each endpoint enqueues frames into the link; the link delivers them
    after an optional delay, possibly dropping frames according to
    *loss_rate*.
    """

    def __init__(
        self,
        name: str = "",
        delay_ms: float = 0.0,
        loss_rate: float = 0.0,
        bandwidth_mbps: float = 1_000.0,  # for future rate-limiting
    ):
        self.name = name
        self.delay_ms = delay_ms
        self.loss_rate = loss_rate
        self.bandwidth_mbps = bandwidth_mbps

        # Maps interface-id → asyncio.Queue (one per attached interface)
        self._queues: Dict[str, asyncio.Queue[bytes]] = {}
        self._metrics = _LinkMetrics()

    # -- attach / detach ----------------------------------------------------

    def attach(self, iface_id: str) -> None:
        """Register an interface endpoint on this link."""
        if iface_id not in self._queues:
            self._queues[iface_id] = asyncio.Queue(maxsize=1000)
            logger.debug(f"[{self.name}] attached {iface_id}")

    def detach(self, iface_id: str) -> None:
        self._queues.pop(iface_id, None)

    # -- send ---------------------------------------------------------------

    async def send(self, from_iface: str, to_iface: str, data: bytes) -> bool:
        """Deliver *data* from one interface to another.

        Returns ``False`` if the frame was dropped.
        """
        # loss injection
        if self.loss_rate > 0 and random.random() < self.loss_rate:
            self._metrics.dropped += 1
            return False

        # delay injection
        if self.delay_ms > 0:
            await asyncio.sleep(self.delay_ms / 1000.0)

        # delivery
        q = self._queues.get(to_iface)
        if q is None:
            logger.warning(f"[{self.name}] unknown destination {to_iface}")
            self._metrics.dropped += 1
            return False

        await q.put(data)
        self._metrics.sent += 1
        self._metrics.bytes_sent += len(data)
        return True

    # -- broadcast ----------------------------------------------------------

    @property
    def peers(self) -> list[str]:
        """Return all attached interface IDs."""
        return list(self._queues.keys())

    async def broadcast(self, from_iface: str, data: bytes) -> bool:
        """Send *data* to all attached interfaces except *from_iface*.

        Returns ``True`` if at least one delivery succeeded.
        """
        ok = False
        for to_id in self._queues:
            if to_id != from_iface:
                ok |= await self.send(from_iface, to_id, data)
        return ok

    # -- receive ------------------------------------------------------------

    async def recv(self, iface_id: str, timeout: float | None = None) -> bytes:
        """Wait for the next frame addressed to *iface_id*."""
        q = self._queues.get(iface_id)
        if q is None:
            raise ValueError(f"Interface {iface_id} not attached to [{self.name}]")
        if timeout is not None:
            return await asyncio.wait_for(q.get(), timeout=timeout)
        return await q.get()

    # -- stats --------------------------------------------------------------

    @property
    def stats(self) -> dict:
        return self._metrics.snapshot()

    def __repr__(self) -> str:
        return (
            f"VirtualLink({self.name}, delay={self.delay_ms}ms, "
            f"loss={self.loss_rate:.1%})"
        )


# ============================================================================
#  VirtualSwitch  – multi-port with port isolation
# ============================================================================


@dataclass
class _SwitchPort:
    mac: bytes
    queue: asyncio.Queue[bytes]


class VirtualSwitch:
    """A layer-2 switch with MAC learning and port-isolation groups.

    Isolation rules
    ---------------
    Ports that belong to the same *isolation group* may communicate with
    each other.  Ports in different groups **cannot** directly exchange
    frames – traffic must go through a router (CR in the core network).

    Typical usage on the access side::

        switch = VirtualSwitch("access-switch")
        switch.add_port(0, cr_mac)   # port 0 = CR
        switch.add_port(1, ap1_mac)  # port 1 = AP1
        switch.add_port(2, ap2_mac)  # port 2 = AP2

        # CR can talk to both APs; AP1 & AP2 cannot talk to each other
        switch.set_isolation_group(1, [0, 1])   # CR ↔ AP1
        switch.set_isolation_group(2, [0, 2])   # CR ↔ AP2
    """

    def __init__(self, name: str = "switch"):
        self.name = name
        self._ports: Dict[int, _SwitchPort] = {}
        self._mac_table: Dict[bytes, int] = {}  # MAC → port

        # isolation_groups[group_id] = set of port numbers
        self._isolation_groups: Dict[int, Set[int]] = {}

        self._metrics = _LinkMetrics()

    # -- port management ----------------------------------------------------

    def add_port(self, port: int, mac: bytes) -> None:
        self._ports[port] = _SwitchPort(mac=mac, queue=asyncio.Queue(maxsize=1000))
        self._mac_table[mac] = port
        logger.debug(f"[{self.name}] port {port} ← {mac.hex(':')}")

    # -- isolation ----------------------------------------------------------

    def set_isolation_group(self, group_id: int, ports: List[int]) -> None:
        """Declare that *ports* may communicate with each other."""
        self._isolation_groups[group_id] = set(ports)

    def _can_forward(self, from_port: int, to_port: int) -> bool:
        """Check whether L2 forwarding is allowed between two ports.

        If no isolation groups are configured, all ports can communicate
        (no port isolation).
        """
        if from_port == to_port:
            return False  # no hairpin
        # No groups → open switch (no isolation)
        if not self._isolation_groups:
            return True
        for ports in self._isolation_groups.values():
            if from_port in ports and to_port in ports:
                return True
        return False  # not in the same group → blocked

    # -- send / recv --------------------------------------------------------

    async def send(self, from_port: int, to_port: int | None, data: bytes) -> bool:
        """Send a frame through the switch.

        If *to_port* is None the switch does MAC learning on the
        destination and forwards accordingly.  If the destination MAC is
        unknown the frame is flooded to all allowed ports.
        """
        if from_port not in self._ports:
            logger.warning(f"[{self.name}] unknown from_port {from_port}")
            return False

        # deliver
        delivered = False
        targets: list[int] = []

        if to_port is not None:
            targets = [to_port]
        else:
            # Use MAC table to find destination
            # (extract dst_mac from Ethernet frame)
            dst_mac = data[0:6]
            if dst_mac in self._mac_table:
                targets = [self._mac_table[dst_mac]]
            else:
                # flood to allowed ports
                targets = [
                    p
                    for p in self._ports
                    if self._can_forward(from_port, p)
                ]

        for tp in targets:
            if not self._can_forward(from_port, tp):
                logger.trace(
                    f"[{self.name}] port-isolation blocked {from_port} → {tp}"
                )
                continue
            if tp in self._ports:
                await self._ports[tp].queue.put(data)
                delivered = True
                self._metrics.sent += 1
                self._metrics.bytes_sent += len(data)

        if not delivered:
            self._metrics.dropped += 1
        return delivered

    async def recv(self, port: int, timeout: float | None = None) -> bytes:
        if port not in self._ports:
            raise ValueError(f"Port {port} not on [{self.name}]")
        if timeout is not None:
            return await asyncio.wait_for(self._ports[port].queue.get(), timeout=timeout)
        return await self._ports[port].queue.get()

    # -- stats --------------------------------------------------------------

    @property
    def stats(self) -> dict:
        return self._metrics.snapshot()

    def __repr__(self) -> str:
        groups = {gid: list(ports) for gid, ports in self._isolation_groups.items()}
        return f"VirtualSwitch({self.name}, ports={list(self._ports.keys())}, groups={groups})"


# ============================================================================
#  Internal metrics
# ============================================================================

@dataclass
class _LinkMetrics:
    sent: int = 0
    dropped: int = 0
    bytes_sent: int = 0

    def snapshot(self) -> dict:
        return {
            "sent": self.sent,
            "dropped": self.dropped,
            "bytes_sent": self.bytes_sent,
        }
