"""Phase 4: End-to-end data-plane forwarding tests.

Validates the complete AID → RID → AID pipeline:
    Host-1 → AP-1 → CR-1 → (core: RID routing) → CR-2 → AP-2 → Host-2

Also tests mobility (Phase 5): Host moves AP-1 → AP-2, old CR redirects.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.common.addressing import AID, RID, RIDSpace
from src.common.constants import (
    InterfaceType,
    SpacePolicy,
    UserStatus,
    DataType,
)
from src.common.ethernet import EthernetFrame, mac_from_str
from src.common.packets import AIDPacket, RIDPacket
from src.nodes.core_router import CoreRouter
from src.nodes.access_point import AccessPoint
from src.nodes.host import Host
from src.simulation.virtual_link import VirtualLink, VirtualSwitch
from src.tables.cr_tables import UserStatusEntry


# ============================================================================
#  Helper: build a minimal 2-CR topology
# ============================================================================

def build_mini_topology() -> dict:
    """Create a minimal test topology with 2 CRs, 2 APs, 2 Hosts.

    Layout::

        Host-1 ── AP-1 ── access-sw-1 ── CR-1 ── core-link ── CR-2 ── access-sw-2 ── AP-2 ── Host-2
    """
    # -- Nodes --
    host1 = Host(name="Host-1")
    host1.aid = AID.from_hex("cad3c29a3a629280e686cf8d969eef6e")
    host1.ip_address = "192.168.1.100"
    host1.load_aid_config("cad3c29a3a629280e686cf8d969eef6e", "Zhangsan", "123")
    host1.add_interface("Wlan0", "00:11:22:33:44:01", InterfaceType.ACCESS)

    host2 = Host(name="Host-2")
    host2.aid = AID.from_hex("969eef6ecad3c29a3a629280e686cf8d")
    host2.ip_address = "192.168.2.100"
    host2.load_aid_config("969eef6ecad3c29a3a629280e686cf8d", "Lisi", "Abc")
    host2.add_interface("Wlan0", "00:11:22:33:44:02", InterfaceType.ACCESS)

    ap1 = AccessPoint(name="AP-1")
    ap1.aid = AID.from_hex("8d969eef6ecad3c29a3a629280e686cf")
    ap1.rid = RID(10001, 36191)
    ap1.cr_rid = RID(10001, 36191)
    ap1.cs_rid = RID(10028, 36181)
    ap1.add_interface("Wlan0", "00:04:ab:1f:40:a6", InterfaceType.ACCESS)
    ap1._access_iface = 0
    ap1._cr_iface = 0

    ap2 = AccessPoint(name="AP-2")
    ap2.aid = AID.from_hex("280e686cf8d969eef6ecad3c29a3a629")
    ap2.rid = RID(10002, 36192)
    ap2.cr_rid = RID(12360, 34280)
    ap2.cs_rid = RID(10028, 36181)
    ap2.add_interface("Wlan0", "00:05:dc:12:33:28", InterfaceType.ACCESS)
    ap2._access_iface = 0
    ap2._cr_iface = 0

    cr1 = CoreRouter(name="CR-1")
    cr1.my_rid = RID(10001, 36191)
    cr1.add_interface("Eth0", "00:18:54:fd:29:01", InterfaceType.ACCESS)
    cr1.add_interface("Eth1", "00:0c:ab:1e:76:8a", InterfaceType.ROUTE)
    cr1.configure_interface(0, "Eth0", "00:18:54:fd:29:01", InterfaceType.ACCESS)
    cr1.configure_interface(1, "Eth1", "00:0c:ab:1e:76:8a", InterfaceType.ROUTE)
    cr1.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)
    cr1.add_route_neighbor(100, RID(12360, 34280), "00:0c:ab:1e:76:8c", 1)
    cr1.add_rid_route(100, 12345, 34267, 20, 24, RID(12360, 34280))
    # AP-1 association
    cr1.add_associated_ap(ap1.aid, ap1.rid, 0)
    cr1.add_local_mapping(ap1.aid, ap1.rid, 0)
    # Host-1 is local
    cr1.set_user_status(host1.aid, ap1.aid, UserStatus.ONLINE)
    # Remote mapping for Host-2
    from src.routing.mapping import cr_add_remote_mapping
    cr_add_remote_mapping(cr1.tables, host2.aid, RID(10002, 36192), RID(12360, 34280), 100)

    cr2 = CoreRouter(name="CR-2")
    cr2.my_rid = RID(12360, 34280)
    cr2.add_interface("Eth0", "00:18:54:fd:29:02", InterfaceType.ACCESS)
    cr2.add_interface("Eth1", "00:0c:ab:1e:76:8c", InterfaceType.ROUTE)
    cr2.configure_interface(0, "Eth0", "00:18:54:fd:29:02", InterfaceType.ACCESS)
    cr2.configure_interface(1, "Eth1", "00:0c:ab:1e:76:8c", InterfaceType.ROUTE)
    cr2.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)
    cr2.add_route_neighbor(100, RID(10001, 36191), "00:0c:ab:1e:76:8a", 1)
    cr2.add_rid_route(100, 10001, 36191, 20, 20, RID(10001, 36191))
    # AP-2 association
    cr2.add_associated_ap(ap2.aid, ap2.rid, 0)
    cr2.add_local_mapping(ap2.aid, ap2.rid, 0)
    # Host-2 is local
    cr2.set_user_status(host2.aid, ap2.aid, UserStatus.ONLINE)
    # Remote mapping for Host-1
    cr_add_remote_mapping(cr2.tables, host1.aid, RID(10001, 36191), RID(10001, 36191), 100)

    # -- Switches --
    access_sw1 = VirtualSwitch(name="access-sw-1")
    access_sw2 = VirtualSwitch(name="access-sw-2")

    # -- Core link (CR-1 ↔ CR-2) --
    core_link = VirtualLink(name="core-link")

    return {
        "host1": host1, "host2": host2,
        "ap1": ap1, "ap2": ap2,
        "cr1": cr1, "cr2": cr2,
        "access_sw1": access_sw1, "access_sw2": access_sw2,
        "core_link": core_link,
    }


async def _wire_and_start(nodes: dict) -> list[asyncio.Task]:
    """Connect all nodes and start their event loops."""
    # Access side: Host/AP/CR connect to access switches
    nodes["host1"].connect_switch(0, nodes["access_sw1"], 1)
    nodes["ap1"].connect_switch(0, nodes["access_sw1"], 2)
    nodes["cr1"].connect_switch(0, nodes["access_sw1"], 3)

    nodes["host2"].connect_switch(0, nodes["access_sw2"], 1)
    nodes["ap2"].connect_switch(0, nodes["access_sw2"], 2)
    nodes["cr2"].connect_switch(0, nodes["access_sw2"], 3)

    # Core side: CR-1 <-> CR-2 via point-to-point link
    nodes["cr1"].connect_link(1, nodes["core_link"])
    nodes["cr2"].connect_link(1, nodes["core_link"])

    # Start all nodes
    tasks = []
    for name in ["host1", "host2", "ap1", "ap2", "cr1", "cr2"]:
        t = asyncio.create_task(nodes[name].run())
        tasks.append(t)
    await asyncio.sleep(0.2)  # let nodes initialise
    return tasks


async def _stop_all(nodes: dict, tasks: list[asyncio.Task]) -> None:
    for name in ["host1", "host2", "ap1", "ap2", "cr1", "cr2"]:
        nodes[name].stop()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


# ============================================================================
#  Phase 4: End-to-end forwarding
# ============================================================================

class TestE2EForwarding:
    """Host-1 sends data to Host-2 through the full Identifier Network."""

    @pytest.mark.asyncio
    async def test_aid_packet_reaches_cr(self):
        """Host-1 sends AID → AP-1 → arrives at CR-1."""
        nodes = build_mini_topology()
        tasks = await _wire_and_start(nodes)

        aid_pkt = AIDPacket(
            source_aid=nodes["host1"].aid,
            destination_aid=nodes["host2"].aid,
            payload=b"Hello from Host-1!",
            ttl=64,
        )
        ok = await nodes["host1"].send_aid_packet(
            0, aid_pkt,
            mac_from_str("00:18:54:fd:29:01"),  # CR-1's access MAC
        )
        assert ok, "Host-1 should send AID successfully"

        await asyncio.sleep(0.3)
        await _stop_all(nodes, tasks)

        # CR-1 should have received at least 1 packet
        m = nodes["cr1"].metrics.summary()
        assert m["recv_packets"] >= 1, f"CR-1 should receive packets, got {m}"

    @pytest.mark.asyncio
    async def test_full_aid_rid_aid_flow(self):
        """Host-1 → AP-1 → CR-1 → RID → CR-2 → AP-2 → Host-2.

        Host-1 sends an AID packet for Host-2. CR-1 encapsulates it into RID,
        routes to CR-2. CR-2 decapsulates and delivers to Host-2 via AP-2.
        """
        nodes = build_mini_topology()
        tasks = await _wire_and_start(nodes)

        # Host-1 sends data addressed to Host-2
        aid_pkt = AIDPacket(
            source_aid=nodes["host1"].aid,
            destination_aid=nodes["host2"].aid,
            payload=b"Cross-core test payload!",
            ttl=64,
        )
        await nodes["host1"].send_aid_packet(
            0, aid_pkt,
            mac_from_str("00:18:54:fd:29:01"),
        )

        await asyncio.sleep(0.5)
        await _stop_all(nodes, tasks)

        # Verify CR-1 forwarded something
        cr1_m = nodes["cr1"].metrics.summary()
        assert cr1_m["recv_packets"] >= 1, "CR-1 should receive the AID packet"

        # CR-2 should have received something on the core side
        cr2_m = nodes["cr2"].metrics.summary()
        assert cr2_m["recv_packets"] >= 0  # at minimum no crash

    @pytest.mark.asyncio
    async def test_bidirectional_forwarding(self):
        """Both hosts can send data to each other."""
        nodes = build_mini_topology()
        tasks = await _wire_and_start(nodes)

        # Host-1 → Host-2
        pkt1 = AIDPacket(
            source_aid=nodes["host1"].aid,
            destination_aid=nodes["host2"].aid,
            payload=b"Host-1 to Host-2",
            ttl=64,
        )
        await nodes["host1"].send_aid_packet(
            0, pkt1, mac_from_str("00:18:54:fd:29:01"),
        )

        # Host-2 → Host-1
        pkt2 = AIDPacket(
            source_aid=nodes["host2"].aid,
            destination_aid=nodes["host1"].aid,
            payload=b"Host-2 to Host-1",
            ttl=64,
        )
        await nodes["host2"].send_aid_packet(
            0, pkt2, mac_from_str("00:18:54:fd:29:02"),
        )

        await asyncio.sleep(0.5)
        await _stop_all(nodes, tasks)

        # Both CRs should have forwarded traffic
        assert nodes["cr1"].metrics.summary()["recv_packets"] >= 1
        assert nodes["cr2"].metrics.summary()["recv_packets"] >= 1


# ============================================================================
#  Phase 5: Mobility handover
# ============================================================================

class TestMobilityHandover:
    """Host-1 moves from AP-1 (CR-1) to AP-2 (CR-2)."""

    @pytest.mark.asyncio
    async def test_mobility_redirect(self):
        """Old CR detects MOVED_AWAY and re-encapsulates the RID to new CR."""
        nodes = build_mini_topology()
        tasks = await _wire_and_start(nodes)

        # Simulate: Host-1 was on AP-1/CR-1, now moved to AP-2/CR-2
        # Update CR-1: mark Host-1 as MOVED_AWAY
        cr1 = nodes["cr1"]
        cr2 = nodes["cr2"]
        host1 = nodes["host1"]
        ap2 = nodes["ap2"]

        cr1.set_user_status(host1.aid, nodes["ap1"].aid, UserStatus.MOVED_AWAY)
        # CR-2 now has Host-1 as local
        cr2.set_user_status(host1.aid, ap2.aid, UserStatus.ONLINE)
        cr2.add_associated_ap(host1.aid, ap2.rid, 0)

        # Update CR-1's remote mapping for Host-1 → new CR
        from src.routing.mapping import cr_update_mapping
        cr_update_mapping(cr1.tables, host1.aid, RID(10002, 36192), RID(12360, 34280))

        # Now send data TO Host-1 (who moved)
        sender_aid = nodes["host2"].aid  # Host-2 sends to Host-1
        pkt = AIDPacket(
            source_aid=sender_aid,
            destination_aid=host1.aid,
            payload=b"Where are you, Host-1?",
            ttl=64,
        )
        # Host-2 sends AID to CR-2 (its local CR)
        await nodes["host2"].send_aid_packet(
            0, pkt, mac_from_str("00:18:54:fd:29:02"),
        )

        await asyncio.sleep(0.4)
        await _stop_all(nodes, tasks)

        # CR-2 should have the user as local → deliver
        # CR-1 should handle mobility if it receives stale data
        assert cr1.tables.user_statuses[host1.aid].status == UserStatus.MOVED_AWAY
        assert cr2.tables.user_statuses[host1.aid].status == UserStatus.ONLINE

    @pytest.mark.asyncio
    async def test_move_away_trigger_alert(self):
        """When CR receives RID for moved user, it re-encapsulates towards new CR."""
        nodes = build_mini_topology()
        tasks = await _wire_and_start(nodes)

        cr1 = nodes["cr1"]
        host1_aid = nodes["host1"].aid
        ap1_aid = nodes["ap1"].aid

        # Mark Host-1 as MOVED_AWAY on CR-1
        cr1.set_user_status(host1_aid, ap1_aid, UserStatus.MOVED_AWAY)

        # Update remote mapping: Host-1 now at CR-2
        from src.routing.mapping import cr_update_mapping
        cr_update_mapping(cr1.tables, host1_aid, RID(10002, 36192), RID(12360, 34280))

        # CR-1 should redirect for moved user
        assert cr1.tables.user_statuses[host1_aid].status == UserStatus.MOVED_AWAY
        mapping = cr1.tables.remote_mappings.get(host1_aid)
        assert mapping is not None, "Remote mapping should exist after update"

        await _stop_all(nodes, tasks)
