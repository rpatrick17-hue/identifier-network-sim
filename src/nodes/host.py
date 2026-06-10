"""Host / Client – 用户终端.

Represents an end-user device that:
    - Loads an AID from a configuration file (pre-registered).
    - Performs authentication via the local AP.
    - Sends / receives traditional IPv4/IPv6 traffic that is transparently
      encapsulated in AID/RID by the network infrastructure.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Optional

from ..common.constants import DEFAULT_TTL, DataType
from ..common.addressing import AID, RID
from ..common.ethernet import EthernetFrame, mac_from_str
from ..common.packets import AIDPacket
from ..control_plane.signaling import AuthRequest, AuthResponse, decode_signal
from .base_node import BaseNode


class Host(BaseNode):
    """用户终端 – AID配置 + 认证客户端 + 应用流量."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name=name)
        self.aid: Optional[AID] = None       # from auth config file
        self.ip_address: str = "192.168.1.100"
        self.ip_netmask: str = "255.255.255.0"
        self.ip_gateway: str = "192.168.1.1"
        self.username: str = ""
        self.password: str = ""
        self._authenticated: bool = False
        self._auth_future: asyncio.Future | None = None
        self._ap_mac: str = ""
        self._iface_idx: int = -1

    # ==================================================================
    #  Configuration
    # ==================================================================

    def load_aid_config(self, aid_hex: str, username: str, password: str) -> None:
        """Load AID from configuration (simulates reading a config file)."""
        self.aid = AID.from_hex(aid_hex)
        self.username = username
        self.password = password
        self.logger.info(f"loaded AID={self.aid}, user={username}")

    # ==================================================================
    #  Authentication
    # ==================================================================

    async def authenticate(self) -> bool:
        """Send authentication request to AP and wait for response.

        Per document §4.1: 终端发送 Auth_Request → AP 代理转发 → CS 验证
        → 返回 Auth_Response → 终端收到后认证完成.
        """
        if self.aid is None:
            self.logger.error("AID not configured")
            return False

        # 1. Build AuthRequest
        req = AuthRequest(
            username=self.username,
            password=self.password,
            user_aid=self.aid,
            ip_address=self.ip_address,
            mac_address=(
                self.interfaces[self._iface_idx].mac_str
                if self._iface_idx >= 0
                else ""
            ),
        )

        # 2. Create pending future for async response
        self._auth_future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()

        # 3. Send AuthRequest as control signal via AP
        from ..common.packets import RIDPacket
        from ..control_plane.signaling import encode_signal
        payload = encode_signal(req)
        # Encapsulate in RID with CONTROL_SIGNALING type so AP knows to proxy
        from ..common.addressing import RID
        from ..common.constants import DataType, DEFAULT_TTL
        sig_pkt = RIDPacket(
            source_rid=RID(0, 0),           # Host doesn't have a RID, AP fills
            destination_rid=RID(0, 0),       # Will be filled by AP
            payload=payload,
            data_type=DataType.CONTROL_SIGNALING,
            ttl=DEFAULT_TTL,
        )
        dst_mac = bytes.fromhex(self._ap_mac.replace(":", "")) if self._ap_mac else b"\xff" * 6
        await self.send_rid_packet(self._iface_idx, sig_pkt, dst_mac)
        self.logger.info(f"Auth request sent: user={self.username}")

        # 4. Wait for AuthResponse (with timeout)
        try:
            result = await asyncio.wait_for(self._auth_future, timeout=5.0)
            self._authenticated = result
            return result
        except asyncio.TimeoutError:
            self.logger.error(f"Auth timeout for {self.username}")
            self._authenticated = False
            return False

    # ==================================================================
    #  Application traffic
    # ==================================================================

    async def http_get(self, url: str, server_aid: AID) -> bytes:
        """Simulate an HTTP GET request."""
        if not self._authenticated:
            self.logger.warning("Not authenticated")
            return b""
        request = f"GET {url} HTTP/1.1\r\nHost: example.com\r\n\r\n".encode("utf-8")
        await self._send_data(server_aid, request, DataType.USER_DATA)
        self.logger.debug(f"HTTP GET → {server_aid}")
        return request  # return sent bytes for metrics

    async def ftp_download(self, filename: str, server_aid: AID) -> None:
        """Simulate an FTP download request."""
        if not self._authenticated:
            return
        request = f"RETR {filename}\r\n".encode("utf-8")
        await self._send_data(server_aid, request, DataType.USER_DATA)
        self.logger.debug(f"FTP RETR {filename} → {server_aid}")

    async def video_stream(self, server_aid: AID, duration_s: float = 5.0) -> None:
        """Simulate a video streaming request."""
        if not self._authenticated:
            return
        request = b"PLAY /stream/live\r\n"
        await self._send_data(server_aid, request, DataType.USER_DATA)
        self.logger.debug(f"Video PLAY → {server_aid}")

    async def _send_data(self, dst_aid: AID, payload: bytes, data_type: DataType) -> None:
        """Encapsulate application data in AID and send via AP."""
        aid_pkt = AIDPacket(
            source_aid=self.aid or AID(0),
            destination_aid=dst_aid,
            payload=payload,
            data_type=data_type,
            ttl=DEFAULT_TTL,
        )
        # In simulation, the Host sends to its AP interface
        await self.send_aid_packet(
            self._iface_idx, aid_pkt,
            bytes.fromhex(self._ap_mac.replace(":", "")) if self._ap_mac else b"\xff" * 6,
        )

    # ==================================================================
    #  Frame handler
    # ==================================================================

    async def on_frame(self, iface_idx: int, frame: EthernetFrame) -> None:
        if frame.is_aid:
            aid_pkt = frame.inner_aid()
            self.logger.debug(f"recv {len(aid_pkt.payload)}B from {aid_pkt.source_aid}")
            self.metrics.record_recv(len(aid_pkt.payload))
        elif frame.is_rid:
            rid_pkt = frame.inner_rid()
            if rid_pkt.data_type == DataType.CONTROL_SIGNALING:
                try:
                    from ..control_plane.signaling import decode_signal, AuthResponse
                    msg = decode_signal(rid_pkt.payload)
                    if isinstance(msg, AuthResponse) and msg.user_aid == self.aid:
                        self.logger.info(f"Auth response: {'OK' if msg.success else 'FAIL'}")
                        if self._auth_future and not self._auth_future.done():
                            self._auth_future.set_result(msg.success)
                except Exception:
                    pass

    # ==================================================================
    #  Lifecycle
    # ==================================================================

    async def on_start(self) -> None:
        self._iface_idx = 0 if self.interfaces else -1
        self.logger.info(f"Host started, aid={self.aid}, ip={self.ip_address}")
