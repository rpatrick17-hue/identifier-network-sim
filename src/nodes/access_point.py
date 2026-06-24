"""Access Point (AP) – 无线接入设备.

Responsibilities:
    - Authenticate users (proxy between Host and CS).
    - Encapsulate user IPv4/IPv6 packets into AID format for core transit.
    - Decapsulate AID packets from CR back to IPv4/IPv6 for local users.
    - Maintain neighbour-AP cache for fast re-authentication.
    - Dual-mode communication with CR: AID (data) + RID (control).

Document reference: §4.1 (authentication), §4.4 (user interworking), §4.5 (mobility).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..common.constants import DEFAULT_TTL, DataType, InterfaceType, UserStatus
from ..common.addressing import AID, RID
from ..common.ethernet import EthernetFrame, mac_from_str
from ..common.packets import AIDPacket, RIDPacket
from ..common.utils import MetricsAccumulator
from ..control_plane.signaling import (
    AuthRequest,
    AuthResponse,
    MappingRegisterRequest,
    MappingQueryRequest,
    MappingQueryResponse,
    NeighborAdvertisement,
    SignalType,
    decode_signal,
    encode_signal,
)
from ..tables.cs_tables import UserRegistryEntry
from .base_node import BaseNode


@dataclass
class LocalUserEntry:
    """Per-user state maintained by the AP."""
    user_aid: AID
    ip_address: str
    mac_address: str
    custom_attributes: str = ""
    is_authenticated: bool = False


class AccessPoint(BaseNode):
    """无线接入设备 – 用户认证代理 + AID封装/解封装."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name=name)
        self.aid: Optional[AID] = None        # this AP's own AID
        self.rid: Optional[RID] = None         # this AP's own RID
        self.cs_rid: Optional[RID] = None      # Control Server's RID
        self.cs_mac: bytes = b"\xff" * 6       # Control Server's MAC
        self.cr_rid: Optional[RID] = None      # associated CR's RID
        self.cr_mac: bytes = b"\xff" * 6       # associated CR's access MAC

        # Local state
        self._local_users: Dict[AID, LocalUserEntry] = {}
        self._neighbor_cache: Dict[AID, tuple[AID, RID]] = {}  # user_aid → (ap_aid, ap_rid)
        self._pending_auth: Dict[int, asyncio.Future] = {}  # request_id → future
        self._auth_seq: int = 0

        # Wireless-side config
        self.ssid: str = "ID-Network"
        self.frequency: str = "2.4GHz"
        self.ip_subnet: str = "192.168.1.0/24"

        # Interface indices
        self._access_iface: int = -1   # towards Hosts (access side)
        self._cr_iface: int = -1       # towards CR

    # ==================================================================
    #  Authentication (document §4.1)
    # ==================================================================

    async def handle_auth_request(self, req: AuthRequest) -> AuthResponse:
        """Process an authentication request from a local Host.

        First check the neighbour cache for fast re-auth.
        """
        user_aid = req.user_aid

        # -- Fast authentication: check neighbour cache -------------------
        if user_aid in self._neighbor_cache:
            self.logger.info(f"fast-auth: {req.username} found in neighbour cache")
            ap_aid, ap_rid = self._neighbor_cache[user_aid]
            self._add_local_user(user_aid, req.ip_address, req.mac_address, authenticated=True)
            return AuthResponse(success=True, user_aid=user_aid, message="fast-auth OK")

        # -- First-time authentication: proxy to CS -----------------------
        self.logger.info(f"proxy-auth: {req.username} → CS")
        resp = await self._proxy_auth_to_cs(req)

        if resp.success:
            self._add_local_user(
                user_aid, req.ip_address, req.mac_address,
                custom_attributes=resp.custom_attributes,
                authenticated=True,
            )
            # Trigger mapping allocation & notifications (async, don't await)
            self.create_task(self._post_auth_procedures(user_aid, resp.custom_attributes))
        else:
            self._add_local_user(user_aid, req.ip_address, req.mac_address, authenticated=False)

        return resp

    def _add_local_user(
        self, aid: AID, ip: str, mac: str,
        custom_attributes: dict | str = "",
        authenticated: bool = False,
    ) -> None:
        if isinstance(custom_attributes, dict):
            attrs_str = ";".join(f"{k}:{v}" for k, v in custom_attributes.items())
        else:
            attrs_str = custom_attributes
        self._local_users[aid] = LocalUserEntry(
            user_aid=aid, ip_address=ip, mac_address=mac,
            custom_attributes=attrs_str, is_authenticated=authenticated,
        )

    async def _proxy_auth_to_cs(self, req: AuthRequest) -> AuthResponse:
        """Forward authentication request to Control Server.

        Uses an asyncio Future to await the CS response asynchronously
        rather than a sleep-based hack.
        """
        if self.cs_rid is None:
            return AuthResponse(success=False, user_aid=req.user_aid, message="CS unreachable")

        # Register a future for this request
        self._auth_seq += 1
        seq = self._auth_seq
        future: asyncio.Future[AuthResponse] = asyncio.get_event_loop().create_future()
        self._pending_auth[seq] = future

        # Encode auth request as control signal
        payload = encode_signal(req)
        rid_pkt = RIDPacket(
            source_rid=self.rid or RID(0, 0),
            destination_rid=self.cs_rid,
            payload=payload,
            network_space_id=0,
            data_type=DataType.CONTROL_SIGNALING,
            ttl=DEFAULT_TTL,
        )
        await self.send_rid_packet(self._cr_iface, rid_pkt, self.cr_mac)

        # Wait for CS response (with timeout)
        try:
            resp = await asyncio.wait_for(future, timeout=5.0)
            return resp
        except asyncio.TimeoutError:
            self._pending_auth.pop(seq, None)
            return AuthResponse(success=False, user_aid=req.user_aid, message="CS timeout")

    async def _post_auth_procedures(
        self, user_aid: AID, custom_attributes: dict | str
    ) -> None:
        """After successful auth: allocate mapping, notify CR, register CS, notify neighbours."""
        # Map user to this AP's RID (same as associated CR's RID)
        mapped_rid = self.cr_rid or RID(user_aid.value >> 64 & 0xFFFFFFFF, user_aid.value & 0xFFFFFFFF)

        # 1. Register mapping with CS
        reg = MappingRegisterRequest(
            aid=user_aid, mapped_rid=mapped_rid,
            ap_rid=self.rid or RID(0, 0), space_id=100,
        )
        await self._send_control_to_cs(reg)

        # 2. Notify associated CR
        await self._notify_cr_mapping(user_aid, mapped_rid)

        # 3. Advertise to neighbour APs
        adv = NeighborAdvertisement(
            user_aid=user_aid, ap_aid=self.aid or AID(0),
            ap_rid=self.rid or RID(0, 0), action="attach",
        )
        await self._broadcast_to_neighbors(adv)

    # ==================================================================
    #  Data handling  (document §4.4)
    # ==================================================================

    async def send_user_data(self, user_aid: AID, dst_aid: AID, ip_payload: bytes) -> None:
        """Encapsulate user's IPv4/IPv6 packet in AID and forward to CR."""
        if not self._local_users.get(user_aid, LocalUserEntry(user_aid, "", "")).is_authenticated:
            self.logger.warning(f"User {user_aid} not authenticated – data dropped")
            return

        aid_pkt = AIDPacket(
            source_aid=user_aid,
            destination_aid=dst_aid,
            payload=ip_payload,
            data_type=DataType.USER_DATA,
            ttl=DEFAULT_TTL,
        )
        # Send AID packet to CR
        await self.send_aid_packet(self._cr_iface, aid_pkt, self.cr_mac)

    # ==================================================================
    #  Control helpers
    # ==================================================================

    async def _send_control_to_cs(self, msg) -> None:
        data = encode_signal(msg)
        rid_pkt = RIDPacket(
            source_rid=self.rid or RID(0, 0),
            destination_rid=self.cs_rid or RID(0, 0),
            payload=data, network_space_id=0,
            data_type=DataType.CONTROL_SIGNALING, ttl=DEFAULT_TTL,
        )
        await self.send_rid_packet(self._cr_iface, rid_pkt, self.cr_mac)

    async def _notify_cr_mapping(self, user_aid: AID, mapped_rid: RID) -> None:
        """Send mapping update to the associated CR via RID control signal."""
        reg = MappingRegisterRequest(
            aid=user_aid, mapped_rid=mapped_rid,
            ap_rid=self.rid or RID(0, 0), space_id=100,
        )
        data = encode_signal(reg)
        rid_pkt = RIDPacket(
            source_rid=self.rid or RID(0, 0),
            destination_rid=self.cr_rid or RID(0, 0),
            payload=data, network_space_id=100,
            data_type=DataType.CONTROL_SIGNALING, ttl=DEFAULT_TTL,
        )
        await self.send_rid_packet(self._cr_iface, rid_pkt, self.cr_mac)
        self.logger.info(f"CR notified: {user_aid} → {mapped_rid}")

    async def _broadcast_to_neighbors(self, msg: NeighborAdvertisement) -> None:
        """Send a neighbour advertisement to all peer APs via CS relay."""
        data = encode_signal(msg)
        rid_pkt = RIDPacket(
            source_rid=self.rid or RID(0, 0),
            destination_rid=self.cs_rid or RID(0, 0),
            payload=data, network_space_id=0,
            data_type=DataType.CONTROL_SIGNALING, ttl=DEFAULT_TTL,
        )
        await self.send_rid_packet(self._cr_iface, rid_pkt, self.cr_mac)
        self.logger.info(f"neighbour advertised: {msg.user_aid} via CS")

    async def activate_user(self, user_aid: AID, user_ip: str, user_mac: str,
                            custom_attributes: dict | str = "") -> None:
        """Called when a user connects to this AP (including mobility handover).

        Performs the full procedure per document §4.5:
        1. Register new mapping with CS
        2. Notify associated CR about the new user location
        3. Advertise to neighbour APs for fast re-auth
        """
        self._add_local_user(user_aid, user_ip, user_mac, custom_attributes, authenticated=True)
        mapped_rid = self.cr_rid or RID(user_aid.value >> 64 & 0xFFFFFFFF, user_aid.value & 0xFFFFFFFF)

        # 1. Register with CS (updates global mapping DB)
        reg = MappingRegisterRequest(
            aid=user_aid, mapped_rid=mapped_rid,
            ap_rid=self.rid or RID(0, 0), space_id=100,
        )
        await self._send_control_to_cs(reg)
        self.logger.info(f"CS registered: {user_aid} → {mapped_rid}")

        # 2. Notify CR
        await self._notify_cr_mapping(user_aid, mapped_rid)

        # 3. Advertise to neighbours
        adv = NeighborAdvertisement(
            user_aid=user_aid, ap_aid=self.aid or AID(0),
            ap_rid=self.rid or RID(0, 0), action="attach",
        )
        await self._broadcast_to_neighbors(adv)

    # ==================================================================
    #  Frame handler
    # ==================================================================

    async def on_frame(self, iface_idx: int, frame: EthernetFrame) -> None:
        if frame.is_rid:
            rid_pkt = frame.inner_rid()
            if rid_pkt.data_type == DataType.CONTROL_SIGNALING:
                msg = decode_signal(rid_pkt.payload)
                await self._dispatch_control_signal(msg)
            else:
                # RID data: decapsulate inner AID and deliver to local user
                try:
                    inner = AIDPacket.deserialize(rid_pkt.payload)
                    await self._deliver_to_user(inner)
                except ValueError:
                    pass
        elif frame.is_aid:
            aid_pkt = frame.inner_aid()
            dst_aid = aid_pkt.destination_aid
            # Bridge: uplink (from Host) vs downlink (from CR)
            if dst_aid in self._local_users:
                # Downlink: deliver to local user
                await self._deliver_to_user(aid_pkt)
            else:
                # Uplink: forward AID to CR for core routing
                await self.send_aid_packet(self._cr_iface, aid_pkt, self.cr_mac)
                self.logger.debug(f"uplink AID {aid_pkt.source_aid} → {dst_aid}")

    async def _dispatch_control_signal(self, msg) -> None:
        if isinstance(msg, AuthRequest):
            # Received from Host: handle authentication
            resp = await self.handle_auth_request(msg)
            # Send response back to Host
            payload = encode_signal(resp)
            from ..common.packets import RIDPacket
            resp_pkt = RIDPacket(
                source_rid=self.rid or RID(0, 0),
                destination_rid=RID(0, 0),
                payload=payload,
                data_type=DataType.CONTROL_SIGNALING,
                ttl=DEFAULT_TTL,
            )
            await self.send_rid_packet(self._access_iface, resp_pkt, b"\xff" * 6)
            self.logger.debug(f"auth response sent to host: {'OK' if resp.success else 'FAIL'}")
        elif isinstance(msg, AuthResponse):
            # Received from CS: resolve the pending proxy future
            if self._pending_auth:
                _, future = self._pending_auth.popitem()
                if not future.done():
                    future.set_result(msg)
            self.logger.debug(f"auth response from CS: {'OK' if msg.success else 'FAIL'}")
        elif isinstance(msg, MappingQueryResponse):
            self.logger.debug(f"mapping response: {msg.aid} → {msg.mapped_rid}")
        elif isinstance(msg, NeighborAdvertisement):
            # Cache neighbour info for fast re-auth
            self._neighbor_cache[msg.user_aid] = (msg.ap_aid, msg.ap_rid)
            self.logger.debug(f"neighbour cache updated: {msg.user_aid}")

    async def _deliver_to_user(self, aid_pkt: AIDPacket) -> None:
        """Decapsulate AID → deliver inner IP payload to local user."""
        dst_aid = aid_pkt.destination_aid
        user = self._local_users.get(dst_aid)
        if user is None:
            self.logger.warning(f"AID for unknown user {dst_aid}")
            return
        # In simulation we just log; in a real system we'd send the
        # inner IP packet to the user's network stack.
        self.metrics.record_recv(len(aid_pkt.payload))
        self.logger.debug(f"delivered {len(aid_pkt.payload)}B to user {dst_aid}")

    # ==================================================================
    #  Lifecycle
    # ==================================================================

    async def on_start(self) -> None:
        self.logger.info(
            f"AP started, SSID={self.ssid}, aid={self.aid}, rid={self.rid}"
        )
