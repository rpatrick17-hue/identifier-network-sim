"""Base class for all Identifier Network simulation nodes.

Each node runs as an independent asyncio task.  Communication between
nodes happens exclusively through *virtual interfaces* that are attached
to ``VirtualLink`` or ``VirtualSwitch`` instances.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple

from loguru import logger as _root_logger

from ..common.constants import InterfaceStatus, InterfaceType
from ..common.ethernet import EthernetFrame, mac_from_str, mac_to_str
from ..common.packets import AIDPacket, RIDPacket
from ..simulation.virtual_link import VirtualLink, VirtualSwitch


# ============================================================================
#  Network interface descriptor
# ============================================================================


@dataclass
class Interface:
    index: int
    name: str
    mac: bytes
    status: InterfaceStatus = InterfaceStatus.UP
    if_type: InterfaceType = InterfaceType.ACCESS

    # which link / switch is this interface connected to?
    link: VirtualLink | None = None
    switch: VirtualSwitch | None = None
    switch_port: int = -1

    @property
    def mac_str(self) -> str:
        return mac_to_str(self.mac)


# ============================================================================
#  BaseNode
# ============================================================================


class BaseNode:
    """Abstract base for CoreRouter, AccessPoint, ControlServer, TestServer, Host.

    Subclasses override :meth:`on_start`, :meth:`on_frame`, and
    :meth:`on_tick` (for periodic work).
    """

    # Class-level counter for unique IDs
    _node_counter: int = 0

    def __init__(self, name: str = "") -> None:
        BaseNode._node_counter += 1
        self.name = name or f"{type(self).__name__}-{BaseNode._node_counter}"
        self.node_id = self.name.lower().replace(" ", "-")

        self.interfaces: List[Interface] = []
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._tick_interval: float = 0.0  # seconds; 0 = disabled

        # per-node logger
        self.logger = _root_logger.bind(node=self.name)
        # metrics accumulator (can be replaced by subclass)
        from ..common.utils import MetricsAccumulator

        self.metrics = MetricsAccumulator()

    # ==================================================================
    #  Interface management
    # ==================================================================

    def add_interface(
        self,
        name: str,
        mac: str,
        if_type: InterfaceType = InterfaceType.ACCESS,
    ) -> int:
        """Register a new interface.  Returns its index."""
        idx = len(self.interfaces)
        iface = Interface(
            index=idx,
            name=name,
            mac=mac_from_str(mac),
            if_type=if_type,
        )
        self.interfaces.append(iface)
        self.logger.info(f"iface[{idx}] {name} ({mac}) type={if_type.name}")
        return idx

    def connect_link(
        self, local_idx: int, link: VirtualLink
    ) -> None:
        """Attach an interface to a point-to-point VirtualLink."""
        iface = self.interfaces[local_idx]
        iface.link = link
        link.attach(f"{self.node_id}:{local_idx}")

    def connect_switch(
        self, local_idx: int, switch: VirtualSwitch, port: int
    ) -> None:
        """Attach an interface to a VirtualSwitch port."""
        iface = self.interfaces[local_idx]
        iface.switch = switch
        iface.switch_port = port
        switch.add_port(port, iface.mac)

    def _my_iface_id(self, idx: int) -> str:
        return f"{self.node_id}:{idx}"

    # ==================================================================
    #  Send / receive primitives
    # ==================================================================

    async def send_frame(self, iface_idx: int, frame: EthernetFrame) -> bool:
        """Send an Ethernet frame out of *iface_idx*."""
        iface = self.interfaces[iface_idx]
        data = frame.serialize()

        if iface.switch is not None:
            # send into switch – let the switch figure out destination
            ok = await iface.switch.send(iface.switch_port, None, data)
        elif iface.link is not None:
            # point-to-point – broadcast to all other attached interfaces
            ok = await iface.link.broadcast(self._my_iface_id(iface_idx), data)
        else:
            self.logger.warning(f"iface[{iface_idx}] has no link/switch attached")
            return False

        if ok:
            self.metrics.record_send(len(data))
        return ok

    async def recv_frame(
        self, iface_idx: int, timeout: float | None = None
    ) -> EthernetFrame | None:
        """Wait for an Ethernet frame on *iface_idx*."""
        iface = self.interfaces[iface_idx]
        try:
            if iface.switch is not None:
                data = await iface.switch.recv(iface.switch_port, timeout=timeout)
            elif iface.link is not None:
                data = await iface.link.recv(
                    self._my_iface_id(iface_idx), timeout=timeout
                )
            else:
                return None
            self.metrics.record_recv(len(data))
            return EthernetFrame.deserialize(data)
        except asyncio.TimeoutError:
            return None

    async def send_aid_packet(
        self, iface_idx: int, pkt: AIDPacket, dst_mac: bytes, src_mac: bytes | None = None
    ) -> bool:
        """Convenience: wrap AID packet in Ethernet and send."""
        if src_mac is None:
            src_mac = self.interfaces[iface_idx].mac
        frame = EthernetFrame.from_aid_packet(pkt, dst_mac, src_mac)
        return await self.send_frame(iface_idx, frame)

    async def send_rid_packet(
        self, iface_idx: int, pkt: RIDPacket, dst_mac: bytes, src_mac: bytes | None = None
    ) -> bool:
        """Convenience: wrap RID packet in Ethernet and send."""
        if src_mac is None:
            src_mac = self.interfaces[iface_idx].mac
        frame = EthernetFrame.from_rid_packet(pkt, dst_mac, src_mac)
        return await self.send_frame(iface_idx, frame)

    # ==================================================================
    #  Lifecycle  (subclass override points)
    # ==================================================================

    async def on_start(self) -> None:
        """Called once when the node is about to enter its main loop."""
        pass

    async def on_frame(self, iface_idx: int, frame: EthernetFrame) -> None:
        """Called for every received Ethernet frame.

        Subclasses **must** override this.
        """
        raise NotImplementedError

    async def on_tick(self) -> None:
        """Called every *tick_interval* seconds (if > 0)."""
        pass

    async def on_stop(self) -> None:
        """Called when the node is shutting down."""
        pass

    @property
    def tick_interval(self) -> float:
        return self._tick_interval

    @tick_interval.setter
    def tick_interval(self, seconds: float) -> None:
        self._tick_interval = seconds

    # ==================================================================
    #  Main loop
    # ==================================================================

    async def run(self) -> None:
        """Start the node's event loop.  Blocks until :meth:`stop` is called."""
        self._running = True
        self.logger.info("starting")

        try:
            await self.on_start()

            # launch one receiver task per interface
            recv_tasks = [
                asyncio.create_task(self._recv_loop(i))
                for i in range(len(self.interfaces))
            ]
            self._tasks.extend(recv_tasks)

            # optional tick loop
            if self._tick_interval > 0:

                async def _tick_loop() -> None:
                    while self._running:
                        await asyncio.sleep(self._tick_interval)
                        if self._running:
                            await self.on_tick()

                self._tasks.append(asyncio.create_task(_tick_loop()))

            # wait for stop signal
            while self._running:
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            self.logger.debug("run task cancelled")
        finally:
            # Always clean up internal tasks
            self._running = False
            for t in self._tasks:
                if not t.done():
                    t.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
            await self.on_stop()
            self.logger.info("stopped")

    async def _recv_loop(self, iface_idx: int) -> None:
        """Per-interface receive loop."""
        while self._running:
            try:
                frame = await self.recv_frame(iface_idx, timeout=0.5)
                if frame is not None:
                    await self.on_frame(iface_idx, frame)
            except asyncio.CancelledError:
                break
            except Exception:
                self.logger.exception(f"error in recv_loop[{iface_idx}]")

    def stop(self) -> None:
        """Signal the node to stop its event loop."""
        self._running = False

    # ==================================================================
    #  Convenience: create_task inside the node's context
    # ==================================================================

    def create_task(self, coro: Coroutine) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.append(task)
        return task
