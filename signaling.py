"""Control-plane signalling message definitions.

Control messages are carried as RID-packet payloads with
``data_type = DataType.CONTROL_SIGNALING (0x01)``.

Message types defined here:

=========================== ===================================================
Message                     Purpose
=========================== ===================================================
AuthRequest                 终端 → AP: 用户认证请求
AuthProxyRequest            AP → CS: 代理认证请求 (含AP自身标识)
AuthResponse                CS → AP → 终端: 认证结果
MappingRegisterRequest      AP → CS: 注册 AID↔RID 映射
MappingQueryRequest         AP/CR → CS: 查询 AID↔RID 映射
MappingQueryResponse        CS → AP/CR: 映射查询结果
MappingUpdateNotification   CS → AP/CR: 映射变更推送
NeighborAdvertisement       AP → neighbor AP: 用户接入通告
MobilityAlert               CR → AP/CS: 移动切换告警
RouteConfigPush             CS → CR: 路由表项下发
=========================== ===================================================
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, Optional

from ..common.addressing import AID, RID


class SignalType(IntEnum):
    """Control-signalling message type identifier (1 byte)."""

    AUTH_REQUEST = 0x01
    AUTH_RESPONSE = 0x02
    MAPPING_REGISTER = 0x10
    MAPPING_QUERY = 0x11
    MAPPING_QUERY_RESPONSE = 0x12
    MAPPING_UPDATE = 0x13
    NEIGHBOR_ADVERTISEMENT = 0x20
    MOBILITY_ALERT = 0x30
    ROUTE_CONFIG_PUSH = 0x40
    MAPPING_UPDATE_NOTIFICATION = 0x50  # CS → CR: mapping changed (mobility)


# ============================================================================
#  Base
# ============================================================================


@dataclass
class BaseSignal:
    """Common fields for every control message."""

    signal_type: SignalType
    timestamp: float = field(default_factory=lambda: __import__("time").time())

    def to_dict(self) -> Dict[str, Any]:
        return {"signal_type": int(self.signal_type), "timestamp": self.timestamp}

    @classmethod
    def _from_base(cls, d: dict) -> dict:
        return d


# ============================================================================
#  Authentication
# ============================================================================


@dataclass
class AuthRequest:
    """终端 → AP: 用户请求认证."""

    username: str
    password: str
    user_aid: AID
    ip_address: str       # e.g. "192.168.1.100"
    mac_address: str       # e.g. "00:11:22:33:44:55"

    def to_dict(self) -> dict:
        return {
            "type": int(SignalType.AUTH_REQUEST),
            "username": self.username,
            "password": self.password,
            "user_aid": self.user_aid.to_hex(),
            "ip_address": self.ip_address,
            "mac_address": self.mac_address,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AuthRequest:
        return cls(
            username=d["username"],
            password=d["password"],
            user_aid=AID.from_hex(d["user_aid"]),
            ip_address=d.get("ip_address", "0.0.0.0"),
            mac_address=d.get("mac_address", ""),
        )


@dataclass
class AuthResponse:
    """CS → AP → 终端: 认证结果."""

    success: bool
    user_aid: AID
    message: str = ""
    custom_attributes: Dict[str, Any] = field(default_factory=dict)
    # e.g. {"UR": 3, "BW": "10Mbps"}

    def to_dict(self) -> dict:
        return {
            "type": int(SignalType.AUTH_RESPONSE),
            "success": self.success,
            "user_aid": self.user_aid.to_hex(),
            "message": self.message,
            "custom_attributes": self.custom_attributes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AuthResponse:
        return cls(
            success=d["success"],
            user_aid=AID.from_hex(d["user_aid"]),
            message=d.get("message", ""),
            custom_attributes=d.get("custom_attributes", {}),
        )


# ============================================================================
#  Mapping
# ============================================================================


@dataclass
class MappingRegisterRequest:
    """AP → CS: 注册 AID↔RID 映射."""

    aid: AID
    mapped_rid: RID
    ap_rid: RID
    space_id: int = 0

    def to_dict(self) -> dict:
        return {
            "type": int(SignalType.MAPPING_REGISTER),
            "aid": self.aid.to_hex(),
            "mapped_rid": self.mapped_rid.to_tuple(),
            "ap_rid": self.ap_rid.to_tuple(),
            "space_id": self.space_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MappingRegisterRequest:
        return cls(
            aid=AID.from_hex(d["aid"]),
            mapped_rid=RID.from_tuple(tuple(d["mapped_rid"])),
            ap_rid=RID.from_tuple(tuple(d["ap_rid"])),
            space_id=d.get("space_id", 0),
        )


@dataclass
class MappingQueryRequest:
    """AP/CR → CS: 查询某个 AID 的映射信息."""

    aid: AID
    requester_rid: RID

    def to_dict(self) -> dict:
        return {
            "type": int(SignalType.MAPPING_QUERY),
            "aid": self.aid.to_hex(),
            "requester_rid": self.requester_rid.to_tuple(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> MappingQueryRequest:
        return cls(
            aid=AID.from_hex(d["aid"]),
            requester_rid=RID.from_tuple(tuple(d["requester_rid"])),
        )


@dataclass
class MappingQueryResponse:
    """CS → AP/CR: 映射查询结果."""

    aid: AID
    mapped_rid: RID
    remote_cr_rid: RID
    space_id: int = 0
    found: bool = True

    def to_dict(self) -> dict:
        return {
            "type": int(SignalType.MAPPING_QUERY_RESPONSE),
            "aid": self.aid.to_hex(),
            "mapped_rid": self.mapped_rid.to_tuple(),
            "remote_cr_rid": self.remote_cr_rid.to_tuple(),
            "space_id": self.space_id,
            "found": self.found,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MappingQueryResponse:
        return cls(
            aid=AID.from_hex(d["aid"]),
            mapped_rid=RID.from_tuple(tuple(d["mapped_rid"])),
            remote_cr_rid=RID.from_tuple(tuple(d["remote_cr_rid"])),
            space_id=d.get("space_id", 0),
            found=d.get("found", True),
        )


# ============================================================================
#  Neighbour advertisement
# ============================================================================


@dataclass
class NeighborAdvertisement:
    """AP → neighbour APs: 通告某用户已接入本 AP."""

    user_aid: AID
    ap_aid: AID
    ap_rid: RID
    action: str = "attach"  # "attach" | "detach"

    def to_dict(self) -> dict:
        return {
            "type": int(SignalType.NEIGHBOR_ADVERTISEMENT),
            "user_aid": self.user_aid.to_hex(),
            "ap_aid": self.ap_aid.to_hex(),
            "ap_rid": self.ap_rid.to_tuple(),
            "action": self.action,
        }

    @classmethod
    def from_dict(cls, d: dict) -> NeighborAdvertisement:
        return cls(
            user_aid=AID.from_hex(d["user_aid"]),
            ap_aid=AID.from_hex(d["ap_aid"]),
            ap_rid=RID.from_tuple(tuple(d["ap_rid"])),
            action=d.get("action", "attach"),
        )


# ============================================================================
#  Mobility alert
# ============================================================================


@dataclass
class MobilityAlert:
    """旧 CR → AP/CS: 检测到用户已移走，携带新的映射信息."""

    user_aid: AID
    old_rid: RID
    new_rid: RID
    new_cr_rid: RID
    reason: str = "mobility_handover"

    def to_dict(self) -> dict:
        return {
            "type": int(SignalType.MOBILITY_ALERT),
            "user_aid": self.user_aid.to_hex(),
            "old_rid": self.old_rid.to_tuple(),
            "new_rid": self.new_rid.to_tuple(),
            "new_cr_rid": self.new_cr_rid.to_tuple(),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MobilityAlert:
        return cls(
            user_aid=AID.from_hex(d["user_aid"]),
            old_rid=RID.from_tuple(tuple(d["old_rid"])),
            new_rid=RID.from_tuple(tuple(d["new_rid"])),
            new_cr_rid=RID.from_tuple(tuple(d["new_cr_rid"])),
            reason=d.get("reason", "mobility_handover"),
        )


# ============================================================================
#  Route config push
# ============================================================================


@dataclass
class RouteConfigPush:
    """CS → CR: 下发路由表项."""

    space_id: int
    dest_rid_space: tuple  # (x, y, x_mask, y_mask)
    next_hop_rid: RID

    def to_dict(self) -> dict:
        return {
            "type": int(SignalType.ROUTE_CONFIG_PUSH),
            "space_id": self.space_id,
            "dest_rid_space": self.dest_rid_space,
            "next_hop_rid": self.next_hop_rid.to_tuple(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> RouteConfigPush:
        return cls(
            space_id=d["space_id"],
            dest_rid_space=tuple(d["dest_rid_space"]),
            next_hop_rid=RID.from_tuple(tuple(d["next_hop_rid"])),
        )


# ============================================================================
#  Mapping update notification (CS → CR on mobility)
# ============================================================================


@dataclass
class MappingUpdateNotification:
    """CS → CR: a user's mapping has changed due to mobility."""

    aid: AID
    new_mapped_rid: RID
    new_cr_rid: RID

    def to_dict(self) -> dict:
        return {
            "type": int(SignalType.MAPPING_UPDATE_NOTIFICATION),
            "aid": self.aid.to_hex(),
            "new_mapped_rid": self.new_mapped_rid.to_tuple(),
            "new_cr_rid": self.new_cr_rid.to_tuple(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> MappingUpdateNotification:
        return cls(
            aid=AID.from_hex(d["aid"]),
            new_mapped_rid=RID.from_tuple(tuple(d["new_mapped_rid"])),
            new_cr_rid=RID.from_tuple(tuple(d["new_cr_rid"])),
        )
        return cls(
            space_id=d["space_id"],
            dest_rid_space=tuple(d["dest_rid_space"]),
            next_hop_rid=RID.from_tuple(tuple(d["next_hop_rid"])),
        )


# ============================================================================
#  Encode / decode helpers
# ============================================================================

_SIGNAL_TYPE_MAP = {
    SignalType.AUTH_REQUEST: AuthRequest,
    SignalType.AUTH_RESPONSE: AuthResponse,
    SignalType.MAPPING_REGISTER: MappingRegisterRequest,
    SignalType.MAPPING_QUERY: MappingQueryRequest,
    SignalType.MAPPING_QUERY_RESPONSE: MappingQueryResponse,
    SignalType.NEIGHBOR_ADVERTISEMENT: NeighborAdvertisement,
    SignalType.MOBILITY_ALERT: MobilityAlert,
    SignalType.ROUTE_CONFIG_PUSH: RouteConfigPush,
    SignalType.MAPPING_UPDATE_NOTIFICATION: MappingUpdateNotification,
}


def encode_signal(msg) -> bytes:
    """Encode any control-signalling message to JSON bytes."""
    return json.dumps(msg.to_dict(), ensure_ascii=False).encode("utf-8")


def decode_signal(data: bytes):
    """Decode JSON bytes back to the correct message object."""
    d = json.loads(data.decode("utf-8"))
    sig_type = SignalType(d["type"])
    cls = _SIGNAL_TYPE_MAP.get(sig_type)
    if cls is None:
        raise ValueError(f"Unknown signal type: {sig_type}")
    return cls.from_dict(d)
