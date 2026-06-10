"""End-to-end integration tests for the Identifier Network simulation."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.common.addressing import AID, RID, RIDSpace
from src.common.constants import InterfaceType, SpacePolicy, UserStatus, DataType
from src.common.ethernet import EthernetFrame, mac_from_str
from src.common.packets import AIDPacket, RIDPacket
from src.common.utils import MetricsAccumulator
from src.nodes.core_router import CoreRouter
from src.nodes.access_point import AccessPoint
from src.nodes.control_server import ControlServer
from src.nodes.host import Host
from src.nodes.test_server import TestServer
from src.simulation.virtual_link import VirtualLink, VirtualSwitch
from src.simulation.topology import Topology


class TestTopologyLoading:
    """Verify topology YAML loads correctly."""

    def test_load_full_topology(self):
        config = Path(__file__).resolve().parent.parent / "config" / "topology.yaml"
        topo = Topology.from_yaml(str(config))
        assert len(topo.core_routers) == 6
        assert len(topo.access_points) == 2
        assert topo.control_server is not None
        assert topo.test_server is not None
        assert len(topo.hosts) == 2
        assert len(topo.switches) == 2

    def test_cr_routing_configured(self):
        config = Path(__file__).resolve().parent.parent / "config" / "topology.yaml"
        topo = Topology.from_yaml(str(config))
        cr1 = topo.core_routers["CR-1"]
        assert len(cr1.tables.rid_routes) >= 1
        assert len(cr1.tables.rid_spaces) >= 1


class TestCoreRouterForwarding:
    """Test CR packet handling in isolation."""

    @pytest.fixture
    def cr(self) -> CoreRouter:
        cr = CoreRouter(name="test-cr")
        cr.my_rid = RID(10001, 36191)

        # Interfaces
        cr.add_interface("Eth0", "00:18:54:fd:29:01", InterfaceType.ACCESS)
        cr.add_interface("Eth1", "00:0c:ab:1e:76:8a", InterfaceType.ROUTE)
        cr.configure_interface(0, "Eth0", "00:18:54:fd:29:01", InterfaceType.ACCESS)
        cr.configure_interface(1, "Eth1", "00:0c:ab:1e:76:8a", InterfaceType.ROUTE)

        # RID spaces
        cr.add_rid_space(0, RIDSpace(10028, 36181, 20, 20), SpacePolicy.MANAGEMENT)
        cr.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)

        # Routes
        cr.add_rid_route(100, 12345, 34267, 20, 24, RID(12360, 34280))

        # AP
        cr.add_associated_ap(AID.from_hex("8d969eef6ecad3c29a3a629280e686cf"),
                             RID(10001, 36191), 0)

        # Users
        cr.set_user_status(
            AID.from_hex("cad3c29a3a629280e686cf8d969eef6e"),
            AID.from_hex("8d969eef6ecad3c29a3a629280e686cf"),
            UserStatus.ONLINE,
        )

        # Mapping
        cr.add_local_mapping(AID.from_hex("8d969eef6ecad3c29a3a629280e686cf"),
                             RID(10001, 36191), 0)

        return cr

    def test_cr_configuration(self, cr):
        assert cr.my_rid == RID(10001, 36191)
        assert len(cr.tables.rid_routes) == 1
        assert len(cr.tables.associated_aps) == 1
        assert cr.tables.is_local_aid(
            AID.from_hex("cad3c29a3a629280e686cf8d969eef6e"))

    def test_rid_route_lookup(self, cr):
        from src.routing.rid_routing import rid_lookup_next_hop
        hop = rid_lookup_next_hop(cr.tables, RID(12345, 34267), 100)
        assert hop == RID(12360, 34280)


class TestVirtualLink:
    """Test the virtual link layer."""

    @pytest.mark.asyncio
    async def test_link_send_recv(self):
        link = VirtualLink(name="test-link")

        # Attach two interfaces
        link.attach("node-a:0")
        link.attach("node-b:0")

        # Send from A to B
        ok = await link.send("node-a:0", "node-b:0", b"hello")
        assert ok

        # B receives
        data = await link.recv("node-b:0", timeout=1.0)
        assert data == b"hello"

    @pytest.mark.asyncio
    async def test_link_broadcast(self):
        link = VirtualLink(name="test-link")
        link.attach("a:0")
        link.attach("b:0")
        link.attach("c:0")

        ok = await link.broadcast("a:0", b"broadcast-msg")
        assert ok

        # b and c should both receive
        d1 = await link.recv("b:0", timeout=1.0)
        d2 = await link.recv("c:0", timeout=1.0)
        assert d1 == b"broadcast-msg"
        assert d2 == b"broadcast-msg"

    @pytest.mark.asyncio
    async def test_link_delay(self):
        link = VirtualLink(name="delay-link", delay_ms=100)
        link.attach("a:0")
        link.attach("b:0")

        import time
        t0 = time.time()
        ok = await link.send("a:0", "b:0", b"delayed")
        elapsed = time.time() - t0
        assert ok
        assert elapsed >= 0.095  # at least ~100ms

    @pytest.mark.asyncio
    async def test_link_loss(self):
        link = VirtualLink(name="lossy-link", loss_rate=1.0)
        link.attach("a:0")
        link.attach("b:0")
        ok = await link.send("a:0", "b:0", b"lost")
        assert not ok  # 100% loss → always dropped


class TestVirtualSwitch:
    """Test the switch with port isolation."""

    @pytest.mark.asyncio
    async def test_switch_forward(self):
        sw = VirtualSwitch(name="test-sw")
        sw.add_port(1, bytes.fromhex("000c29ab1e01"))
        sw.add_port(2, bytes.fromhex("000c29ab1e02"))
        sw.set_isolation_group(1, [1, 2])

        # Build a simple Ethernet frame
        from src.common.serializer import ETH_HEADER_STRUCT
        frame = ETH_HEADER_STRUCT.pack(
            bytes.fromhex("000c29ab1e02"),  # dst = port 2
            bytes.fromhex("000c29ab1e01"),  # src = port 1
            0x88B5,
        ) + b"test-payload"

        ok = await sw.send(1, None, frame)
        assert ok

        data = await sw.recv(2, timeout=1.0)
        assert b"test-payload" in data

    @pytest.mark.asyncio
    async def test_port_isolation_block(self):
        from src.common.serializer import ETH_HEADER_STRUCT

        sw = VirtualSwitch(name="iso-sw")
        sw.add_port(1, bytes.fromhex("000c29ab1e01"))
        sw.add_port(2, bytes.fromhex("000c29ab1e02"))
        sw.add_port(3, bytes.fromhex("000c29ab1e03"))
        # Ports 1 and 3 share group; Port 2 is isolated
        sw.set_isolation_group(1, [1, 3])

        frame = ETH_HEADER_STRUCT.pack(
            bytes.fromhex("000c29ab1e02"),
            bytes.fromhex("000c29ab1e01"),
            0x88B5,
        ) + b"blocked"

        ok = await sw.send(1, None, frame)
        assert not ok  # blocked: port 1→2 not in same isolation group


class TestEndToEnd:
    """End-to-end AID → RID → AID flow."""

    def test_topology_builds(self):
        """Verify the full topology builds without errors."""
        config = Path(__file__).resolve().parent.parent / "config" / "topology.yaml"
        topo = Topology.from_yaml(str(config))
        assert topo.control_server is not None
        assert len(topo.core_routers) == 6
        assert len(topo.access_points) == 2
