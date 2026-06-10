"""Control Server (CS) – 控制平面服务器.

Integrates three sub-services:
    - AAA: authentication, user registration
    - Mapping Service: AID↔RID registry
    - Route Manager: RID space & routing table management

Communicates with CRs and APs via RID-encapsulated control signalling
(Data Type = CONTROL_SIGNALING) over the management space (space_id=0).
"""

from __future__ import annotations

from typing import Optional

from ..common.constants import DEFAULT_TTL, DataType, SpacePolicy
from ..common.addressing import AID, RID
from ..common.ethernet import EthernetFrame
from ..common.packets import RIDPacket
from ..control_plane.signaling import (
    AuthRequest,
    AuthResponse,
    MappingQueryRequest,
    MappingQueryResponse,
    MappingRegisterRequest,
    MappingUpdateNotification,
    NeighborAdvertisement,
    MobilityAlert,
    RouteConfigPush,
    SignalType,
    decode_signal,
    encode_signal,
)
from ..routing.mapping import cs_register_mapping, cs_query_mapping
from ..tables.cs_tables import CSDatabase, UserRegistryEntry
from .base_node import BaseNode


class ControlServer(BaseNode):
    """控制平面服务器 – AAA + Mapping + Route Management."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name=name)
        self.db = CSDatabase()
        self.rid: Optional[RID] = None  # this CS's own RID

        # Interface indices
        self._mgmt_iface: int = -1  # towards management switch

    # ==================================================================
    #  User Registry (document §4.2)
    # ==================================================================

    def register_user(
        self,
        username: str,
        password: str,
        pin: str = "0000",
        custom_attributes: str = "",
        device_id: str = "",
    ) -> UserRegistryEntry:
        """Register a new user. AID is generated from username+pin+device_id."""
        from ..common.utils import generate_aid

        aid_bytes = generate_aid(username, pin, device_id)
        aid = AID(int.from_bytes(aid_bytes, "big"))

        entry = UserRegistryEntry(
            user_aid=aid,
            pin=pin,
            username=username,
            password=password,
            custom_attributes=custom_attributes,
        )
        self.db.add_user(entry)
        self.logger.info(f"registered user: {username} → {aid}")
        return entry

    # ==================================================================
    #  Frame handler
    # ==================================================================

    async def on_frame(self, iface_idx: int, frame: EthernetFrame) -> None:
        if not frame.is_rid:
            return
        rid_pkt = frame.inner_rid()

        if rid_pkt.data_type != DataType.CONTROL_SIGNALING:
            return

        msg = decode_signal(rid_pkt.payload)
        await self._dispatch(msg, rid_pkt.source_rid)

    async def _dispatch(self, msg, sender_rid: RID) -> None:
        self.logger.debug(f"recv {type(msg).__name__} from {sender_rid}")

        if isinstance(msg, AuthRequest):
            await self._handle_auth(msg, sender_rid)
        elif isinstance(msg, MappingRegisterRequest):
            await self._handle_register(msg)
        elif isinstance(msg, MappingQueryRequest):
            await self._handle_query(msg, sender_rid)
        elif isinstance(msg, MobilityAlert):
            await self._handle_mobility(msg)
        elif isinstance(msg, NeighborAdvertisement):
            # Relay to relevant APs
            self.logger.debug(f"neighbour adv: {msg.user_aid} via {msg.ap_aid}")

    # ==================================================================
    #  Authentication
    # ==================================================================

    async def _handle_auth(self, req: AuthRequest, sender_rid: RID) -> None:
        """Process authentication request (proxied by AP)."""
        entry = self.db.authenticate(req.username, req.password)

        if entry is None:
            resp = AuthResponse(
                success=False,
                user_aid=req.user_aid,
                message="Invalid username or password",
            )
        elif entry.user_aid != req.user_aid:
            resp = AuthResponse(
                success=False,
                user_aid=req.user_aid,
                message="AID mismatch",
            )
        else:
            resp = AuthResponse(
                success=True,
                user_aid=entry.user_aid,
                message="Authentication successful",
                custom_attributes=entry.parse_attributes(),
            )
            self.logger.info(f"auth OK: {req.username} (AID={entry.user_aid})")

        await self._reply_to(sender_rid, resp)

    # ==================================================================
    #  Mapping service
    # ==================================================================

    async def _handle_register(self, msg: MappingRegisterRequest) -> None:
        # 确定这个 AP 所属的 CR
        cr_rid = self.db.ap_to_cr.get(msg.ap_rid, msg.ap_rid)
        cs_register_mapping(self.db, msg.aid, msg.mapped_rid, cr_rid, msg.space_id)
        self.logger.info(f"mapping registered: {msg.aid} → {msg.mapped_rid} (CR={cr_rid})")
        # 通知所有管理的CR: 新用户已注册 (全局传播)
        update = MappingUpdateNotification(
            aid=msg.aid, new_mapped_rid=msg.mapped_rid,
            new_cr_rid=cr_rid,
        )
        for crid in list(self.db.managed_crs.keys()):
            await self._reply_to(crid, update)
        self.logger.info(f"registration propagated to {len(self.db.managed_crs)} CRs")

    async def _handle_query(self, msg: MappingQueryRequest, sender_rid: RID) -> None:
        entry = cs_query_mapping(self.db, msg.aid)
        if entry:
            resp = MappingQueryResponse(
                aid=entry.aid,
                mapped_rid=entry.mapped_rid,
                remote_cr_rid=entry.remote_cr_rid,
                space_id=entry.space_id,
                found=True,
            )
        else:
            resp = MappingQueryResponse(
                aid=msg.aid,
                mapped_rid=RID(0, 0),
                remote_cr_rid=RID(0, 0),
                found=False,
            )
        await self._reply_to(sender_rid, resp)

    # ==================================================================
    #  Mobility
    # ==================================================================

    async def _handle_mobility(self, msg: MobilityAlert) -> None:
        self.logger.info(
            f"mobility alert: {msg.user_aid} moved {msg.old_rid} → {msg.new_rid}"
        )
        # 1. Update mapping in CS database
        if msg.user_aid in self.db.mappings:
            self.db.mappings[msg.user_aid].mapped_rid = msg.new_rid
            self.db.mappings[msg.user_aid].remote_cr_rid = msg.new_cr_rid
        else:
            # Register new mapping from the alert
            from ..routing.mapping import cs_register_mapping
            cs_register_mapping(self.db, msg.user_aid, msg.new_rid, msg.new_cr_rid)

        # 2. Propagate to all managed CRs so they update their cached mappings
        update = MappingUpdateNotification(
            aid=msg.user_aid, new_mapped_rid=msg.new_rid, new_cr_rid=msg.new_cr_rid,
        )
        for cr_rid in list(self.db.managed_crs.keys()):
            await self._reply_to(cr_rid, update)
        self.logger.info(f"mobility propagated to {len(self.db.managed_crs)} CRs")

    # ==================================================================
    #  Reply helper
    # ==================================================================

    async def _reply_to(self, target_rid: RID, msg) -> None:
        """Send a control response back to *target_rid* on all interfaces."""
        data = encode_signal(msg)
        rid_pkt = RIDPacket(
            source_rid=self.rid or RID(0, 0),
            destination_rid=target_rid,
            payload=data,
            network_space_id=0,
            data_type=DataType.CONTROL_SIGNALING,
            ttl=DEFAULT_TTL,
        )
        # Send on all interfaces (CS may be connected to multiple switches)
        for i in range(len(self.interfaces)):
            await self.send_rid_packet(i, rid_pkt, b"\xff" * 6)

    # ==================================================================
    #  Lifecycle
    # ==================================================================

    async def on_start(self) -> None:
        self.logger.info(
            f"CS started, rid={self.rid}, "
            f"users={len(self.db.users)}, "
            f"mappings={len(self.db.mappings)}"
        )
