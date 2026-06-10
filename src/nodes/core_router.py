"""Core Router (CR) – 多模态网络核心路由器.

Implements the complete forwarding decision tree (document Fig.17):
    1. Examine Ethernet type → AID or RID?
    2. AID: local delivery or encapsulate into RID for core transit.
    3. RID: match local space → decapsulate & deliver, else core-route.
    4. Mobility: if user has moved, re-encapsulate & forward to new CR.
"""

from __future__ import annotations

from typing import Optional

from ..common.constants import (
    ETHERTYPE_AID,
    ETHERTYPE_RID,
    DEFAULT_TTL,
    DataType,
    InterfaceType,
    UserStatus,
)
from ..common.addressing import AID, RID
from ..common.ethernet import EthernetFrame, mac_to_str
from ..common.packets import AIDPacket, RIDPacket
from ..common.utils import MetricsAccumulator
from ..control_plane.signaling import (
    MobilityAlert,
    NeighborAdvertisement,
    encode_signal,
)
from ..routing.aid_routing import aid_lookup_next_hop
from ..routing.mapping import (
    cr_lookup_any_mapping,
    cr_add_local_mapping,
    cr_update_mapping,
)
from ..routing.rid_routing import rid_lookup_next_hop
from ..tables.cr_tables import (
    AccessNeighborEntry,
    AssociatedAPEntry,
    CRTables,
    InterfaceEntry,
    MappingEntry,
    RIDRouteEntry,
    RIDSpaceEntry,
    RouteNeighborEntry,
    UserStatusEntry,
)
from .base_node import BaseNode


class CoreRouter(BaseNode):
    """标识网络模态 – 核心路由器."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name=name)
        self.tables = CRTables()
        self._my_rid: Optional[RID] = None  # this CR's own RID

    # ==================================================================
    #  Configuration helpers
    # ==================================================================

    @property
    def my_rid(self) -> Optional[RID]:
        return self._my_rid

    @my_rid.setter
    def my_rid(self, rid: RID) -> None:
        self._my_rid = rid

    def configure_interface(
        self, index: int, name: str, mac: str, if_type: InterfaceType
    ) -> None:
        self.tables.interfaces[index] = InterfaceEntry(
            index=index, name=name, mac=mac, if_type=if_type
        )

    def add_rid_space(self, space_id: int, rid_space, policy) -> None:
        self.tables.rid_spaces[space_id] = RIDSpaceEntry(
            space_id=space_id, rid_space=rid_space, policy=policy
        )

    def add_route_neighbor(
        self, space_id: int, neighbor_rid: RID, neighbor_mac: str, iface_idx: int
    ) -> None:
        self.tables.route_neighbors.append(
            RouteNeighborEntry(
                space_id=space_id,
                neighbor_rid=neighbor_rid,
                neighbor_mac=neighbor_mac,
                interface_index=iface_idx,
            )
        )

    def add_access_neighbor(
        self, neighbor_aid: AID, neighbor_mac: str, iface_idx: int
    ) -> None:
        self.tables.access_neighbors.append(
            AccessNeighborEntry(
                neighbor_aid=neighbor_aid,
                neighbor_mac=neighbor_mac,
                interface_index=iface_idx,
            )
        )

    def add_rid_route(
        self, space_id: int, x: int, y: int, x_mask: int, y_mask: int,
        next_hop: RID
    ) -> None:
        from ..routing.rid_routing import rid_route_add
        rid_route_add(self.tables, space_id, x, y, x_mask, y_mask, next_hop)

    def add_aid_route(self, dst_aid: AID, next_hop_aid: AID) -> None:
        from ..routing.aid_routing import aid_route_add
        aid_route_add(self.tables, dst_aid, next_hop_aid)

    def add_local_mapping(self, aid: AID, rid: RID, space_id: int = 0) -> None:
        cr_add_local_mapping(self.tables, aid, rid, space_id)

    def add_associated_ap(self, ap_aid: AID, ap_rid: RID, iface_idx: int) -> None:
        self.tables.associated_aps[ap_aid] = AssociatedAPEntry(
            ap_aid=ap_aid, ap_rid=ap_rid, interface_index=iface_idx
        )

    def set_user_status(
        self, user_aid: AID, ap_aid: AID, status: UserStatus, attrs: str = ""
    ) -> None:
        self.tables.user_statuses[user_aid] = UserStatusEntry(
            user_aid=user_aid, ap_aid=ap_aid, status=status, custom_attributes=attrs
        )

    # ==================================================================
    #  Packet handler  (document Fig.17 decision tree)
    # ==================================================================

    async def on_frame(self, iface_idx: int, frame: EthernetFrame) -> None:
        if frame.is_aid:
            await self._handle_aid(iface_idx, frame)
        elif frame.is_rid:
            await self._handle_rid(iface_idx, frame)
        else:
            self.logger.debug(f"unknown EtherType 0x{frame.ethertype:04x} on iface[{iface_idx}]")

    # ------------------------------------------------------------------
    #  AID packet handling
    # ------------------------------------------------------------------

    async def _handle_aid(self, iface_idx: int, frame: EthernetFrame) -> None:
        aid_pkt = frame.inner_aid()
        dst_aid = aid_pkt.destination_aid

        self.logger.debug(
            f"recv AID: {aid_pkt.source_aid} → {dst_aid}, "
            f"ttl={aid_pkt.ttl}, payload={len(aid_pkt.payload)}B"
        )

        # -- TTL check -------------------------------------------------------
        if not aid_pkt.decrement_ttl():
            self.logger.debug("AID TTL expired – dropped")
            return

        # -- Branch 1: is destination locally attached? ---------------------
        if self.tables.is_local_aid(dst_aid):
            # First try: is the destination a directly-connected access neighbour?
            for nb in self.tables.access_neighbors:
                if nb.neighbor_aid == dst_aid:
                    dst_mac = bytes(int(b, 16) for b in nb.neighbor_mac.split(":"))
                    await self.send_aid_packet(nb.interface_index, aid_pkt, dst_mac)
                    self.logger.debug(f"AID directly delivered to {dst_aid}")
                    return
            # Fallback: forward via serving AP
            ap_aid = self.tables.user_ap_aid(dst_aid)
            if ap_aid is None:
                self.logger.warning(f"AID local but no AP for {dst_aid}")
                return
            ap_iface = self.tables.ap_interface(ap_aid)
            if ap_iface is None:
                self.logger.warning(f"No interface for AP {ap_aid}")
                return

            dst_mac = self._resolve_ap_mac(ap_aid)
            await self.send_aid_packet(ap_iface, aid_pkt, dst_mac)
            self.logger.debug(f"AID local-forwarded to AP {ap_aid}")
            return

        # -- Branch 2: encapsulate into RID ---------------------------------
        mapping = cr_lookup_any_mapping(self.tables, dst_aid)
        if mapping is None:
            self.logger.warning(f"No mapping for {dst_aid} – dropped")
            return

        # Determine which RID space to use
        space_id = mapping.space_id
        if space_id not in self.tables.rid_spaces:
            space_id = list(self.tables.rid_spaces.keys())[0] if self.tables.rid_spaces else 0

        # Build RID packet (encapsulation mapping mode)
        # Re-serialize AID packet as RID payload
        rid_pkt = RIDPacket(
            source_rid=self._my_rid or RID(0, 0),
            destination_rid=mapping.mapped_rid,
            payload=aid_pkt.serialize(),
            network_space_id=space_id,
            data_type=aid_pkt.data_type,
            ttl=DEFAULT_TTL,
        )

        # Route the RID packet through the core
        next_hop = rid_lookup_next_hop(self.tables, mapping.mapped_rid, space_id)
        if next_hop is None:
            self.logger.warning(f"No RID route for {mapping.mapped_rid} – dropped")
            return

        await self._forward_rid_to(next_hop, rid_pkt)
        self.logger.debug(f"AID→RID encapsulated, next_hop={next_hop}")

    # ------------------------------------------------------------------
    #  RID packet handling
    # ------------------------------------------------------------------

    async def _handle_rid(self, iface_idx: int, frame: EthernetFrame) -> None:
        rid_pkt = frame.inner_rid()

        self.logger.debug(
            f"recv RID: {rid_pkt.source_rid} → {rid_pkt.destination_rid}, "
            f"space={rid_pkt.network_space_id}, ttl={rid_pkt.ttl}"
        )

        # -- TTL check (loop prevention) ------------------------------------
        if not rid_pkt.decrement_ttl():
            self.logger.debug("RID TTL expired – dropped")
            return

        # -- Branch 1: does dst RID match any local RID space? --------------
        if not self.tables.matching_rid_space(rid_pkt.destination_rid):
            # Not our space – continue core routing
            next_hop = rid_lookup_next_hop(
                self.tables, rid_pkt.destination_rid, rid_pkt.network_space_id
            )
            if next_hop:
                await self._forward_rid_to(next_hop, rid_pkt)
            elif rid_pkt.data_type == DataType.CONTROL_SIGNALING:
                # Control signalling often broadcast → not an error
                self.logger.debug(
                    f"Control RID for {rid_pkt.destination_rid} – not routed, "
                    f"may be delivered via direct L2 broadcast"
                )
            else:
                self.logger.debug(
                    f"No route for RID {rid_pkt.destination_rid} – dropped"
                )
            return

        # -- Branch 2: space matches – is it addressed to us / a local AP? --
        if (self._my_rid and rid_pkt.destination_rid == self._my_rid) or \
           self.tables.is_local_rid(rid_pkt.destination_rid):
            if rid_pkt.data_type == DataType.CONTROL_SIGNALING:
                await self._handle_control_signal(rid_pkt)
            elif self.tables.is_local_rid(rid_pkt.destination_rid):
                await self._deliver_to_local_ap(rid_pkt)
            else:
                # Packet addressed to this CR itself (e.g. probe) — accept silently
                self.logger.debug(f"Self-addressed RID packet, {len(rid_pkt.payload)}B")
            return

        # -- Branch 3: space matches but NOT us → decapsulate & handle AID --
        await self._decapsulate_and_forward(rid_pkt)

    # ------------------------------------------------------------------
    #  Forwarding helpers
    # ------------------------------------------------------------------

    async def _forward_rid_to(self, next_hop_rid: RID, rid_pkt: RIDPacket) -> None:
        """Send a RID packet towards *next_hop_rid*."""
        iface_idx: Optional[int] = None
        dst_mac: bytes = b"\xff" * 6  # default: broadcast
        for nb in self.tables.route_neighbors:
            if nb.neighbor_rid == next_hop_rid:
                iface_idx = nb.interface_index
                dst_mac = bytes(int(b, 16) for b in nb.neighbor_mac.split(":"))
                break

        if iface_idx is None:
            self.logger.warning(f"No interface for next_hop {next_hop_rid}")
            return

        await self.send_rid_packet(iface_idx, rid_pkt, dst_mac)

    def _resolve_ap_mac(self, ap_aid: AID) -> bytes:
        """Look up an AP's MAC from the access neighbours table."""
        for nb in self.tables.access_neighbors:
            if nb.neighbor_aid == ap_aid:
                return bytes(int(b, 16) for b in nb.neighbor_mac.split(":"))
        return b"\xff" * 6  # fallback broadcast

    async def _deliver_to_local_ap(self, rid_pkt: RIDPacket) -> None:
        """Forward a RID packet to the destination AP on the access side."""
        for ap in self.tables.associated_aps.values():
            if ap.ap_rid == rid_pkt.destination_rid:
                dst_mac = self._resolve_ap_mac(ap.ap_aid)
                await self.send_rid_packet(ap.interface_index, rid_pkt, dst_mac)
                return
        self.logger.warning(f"No local AP for RID {rid_pkt.destination_rid}")

    async def _decapsulate_and_forward(self, rid_pkt: RIDPacket) -> None:
        """Decapsulate RID → AID, then handle according to user status."""
        try:
            inner_aid = AIDPacket.deserialize(rid_pkt.payload)
        except ValueError as e:
            self.logger.warning(f"RID decapsulation failed: {e}")
            return

        dst_aid = inner_aid.destination_aid
        self.logger.debug(f"RID decapsulated → AID {dst_aid}")

        # Check user status
        user_entry = self.tables.user_statuses.get(dst_aid)

        if user_entry is None or user_entry.status == UserStatus.OFFLINE:
            self.logger.warning(f"User {dst_aid} offline – dropped")
            return

        if user_entry.status == UserStatus.MOVED_AWAY:
            # Mobility handover: re-encapsulate & send to new CR
            self.logger.info(f"User {dst_aid} moved away – redirecting")
            mapping = cr_lookup_any_mapping(self.tables, dst_aid)
            if mapping:
                new_rid_pkt = RIDPacket(
                    source_rid=self._my_rid or RID(0, 0),
                    destination_rid=mapping.remote_cr_rid,
                    payload=inner_aid.serialize(),
                    network_space_id=mapping.space_id,
                    data_type=inner_aid.data_type,
                    ttl=DEFAULT_TTL,
                )
                next_hop = rid_lookup_next_hop(
                    self.tables, mapping.remote_cr_rid, mapping.space_id
                )
                if next_hop:
                    await self._forward_rid_to(next_hop, new_rid_pkt)

                # Emit mobility alert
                alert = MobilityAlert(
                    user_aid=dst_aid,
                    old_rid=self._my_rid or RID(0, 0),
                    new_rid=mapping.mapped_rid,
                    new_cr_rid=mapping.remote_cr_rid,
                )
                await self._send_control_to_cs(alert)
            return

        # User ONLINE – forward to serving AP
        if user_entry.status == UserStatus.ONLINE:
            ap_entry = self.tables.associated_aps.get(user_entry.ap_aid)
            if ap_entry:
                dst_mac = self._resolve_ap_mac(ap_entry.ap_aid)
                await self.send_aid_packet(
                    ap_entry.interface_index, inner_aid, dst_mac,
                )
                self.logger.debug(f"AID delivered to AP {user_entry.ap_aid}")

    # ------------------------------------------------------------------
    #  Control signalling
    # ------------------------------------------------------------------

    async def _handle_control_signal(self, rid_pkt: RIDPacket) -> None:
        """Process control-plane messages addressed to this CR."""
        from ..control_plane.signaling import decode_signal, MappingUpdateNotification
        try:
            msg = decode_signal(rid_pkt.payload)
        except Exception:
            return

        if isinstance(msg, MappingUpdateNotification):
            from ..routing.mapping import cr_update_mapping
            cr_update_mapping(self.tables, msg.aid, msg.new_mapped_rid, msg.new_cr_rid)
            if msg.aid in self.tables.user_statuses:
                self.tables.user_statuses[msg.aid].status = UserStatus.MOVED_AWAY
            else:
                # 新用户注册到本CR下的AP (CS传播)
                from ..tables.cr_tables import UserStatusEntry
                self.tables.user_statuses[msg.aid] = UserStatusEntry(
                    user_aid=msg.aid, ap_aid=AID(0),  # AP_AID will be set by AP
                    status=UserStatus.ONLINE,
                )
            # Set AP_AID from managed APs
            for ap_aid, ap_entry in self.tables.associated_aps.items():
                if ap_entry.ap_rid == msg.new_mapped_rid:
                    self.tables.user_statuses[msg.aid].ap_aid = ap_aid
                    break
            self.logger.info(f"mapping updated from CS: {msg.aid} → {msg.new_mapped_rid}")

    async def _send_control_to_cs(self, msg) -> None:
        """Send a control message to the Control Server."""
        from ..control_plane.signaling import encode_signal
        data = encode_signal(msg)
        # Find the CS route neighbour in management space (space_id=0)
        cs_neighbor = None
        for nb in self.tables.route_neighbors:
            if nb.space_id == 0:
                cs_neighbor = nb
                break
        if cs_neighbor is None:
            self.logger.warning("No CS route neighbour configured")
            return

        rid_pkt = RIDPacket(
            source_rid=self._my_rid or RID(0, 0),
            destination_rid=cs_neighbor.neighbor_rid,
            payload=data,
            network_space_id=0,
            data_type=DataType.CONTROL_SIGNALING,
            ttl=DEFAULT_TTL,
        )
        dst_mac = bytes(int(b, 16) for b in cs_neighbor.neighbor_mac.split(":"))
        await self.send_rid_packet(cs_neighbor.interface_index, rid_pkt, dst_mac)

    # ==================================================================
    #  Lifecycle
    # ==================================================================

    async def on_start(self) -> None:
        self.logger.info(
            f"CR started, my_rid={self._my_rid}, "
            f"spaces={list(self.tables.rid_spaces.keys())}"
        )

    def summary(self) -> str:
        return (
            f"CoreRouter({self.name}): "
            f"rid={self._my_rid}, "
            f"ifaces={len(self.tables.interfaces)}, "
            f"rid_routes={len(self.tables.rid_routes)}, "
            f"aid_routes={len(self.tables.aid_routes)}, "
            f"mappings(local={len(self.tables.local_mappings)}, "
            f"remote={len(self.tables.remote_mappings)}), "
            f"users={len(self.tables.user_statuses)}"
        )
