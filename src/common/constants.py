"""Protocol constants and enumerations for Identifier Network."""

from enum import IntEnum

# ---------------------------------------------------------------------------
# Custom EtherType values for identifier network frames
# ---------------------------------------------------------------------------
ETHERTYPE_AID = 0x88B5  # Access Identifier packet
ETHERTYPE_RID = 0x88B6  # Route Identifier packet
ETHERTYPE_IPv4 = 0x0800  # Standard IPv4 (fallback)

# ---------------------------------------------------------------------------
# Identifier type field (4 bits) in AID / RID headers
# ---------------------------------------------------------------------------
class IDType(IntEnum):
    AID = 0b1000  # Access Identifier (接入标识)
    RID = 0b0100  # Route Identifier  (路由标识)


class Version(IntEnum):
    V1 = 0b0001


class DataType(IntEnum):
    USER_DATA = 0x00         # User-plane data (IPv4/IPv6 payload)
    CONTROL_SIGNALING = 0x01  # Control-plane signalling (auth / mapping / routing)


# ---------------------------------------------------------------------------
# Interface attributes
# ---------------------------------------------------------------------------
class InterfaceType(IntEnum):
    ACCESS = 1  # Access-side interface (connects to AP / access switch)
    ROUTE = 2   # Core-side interface (connects to other CRs)


class InterfaceStatus(IntEnum):
    UP = 1
    DOWN = 0


# ---------------------------------------------------------------------------
# User / mapping state enums
# ---------------------------------------------------------------------------
class UserStatus(IntEnum):
    ONLINE = 0       # 在线
    MOVED_AWAY = 1   # 移走
    OFFLINE = 2      # 离线


class SpacePolicy(IntEnum):
    MANAGEMENT = 0  # 网络管理
    DEFAULT = 1     # 默认空间
    ADVANCED = 2    # 高级映射


# ---------------------------------------------------------------------------
# AID packet header layout  (40 bytes)
# ---------------------------------------------------------------------------
# Version(4b)+IDType(4b)=1B  QoS=1B  Reserved=2B  PayloadLen=2B
# DataType=1B  TTL=1B  SrcAID=16B  DstAID=16B
# ---------------------------------------------------------------------------
AID_HEADER_BYTES = 40

# ---------------------------------------------------------------------------
# RID packet header layout  (24 bytes)
# ---------------------------------------------------------------------------
# Version(4b)+IDType(4b)=1B  QoS=1B  SpaceID=2B  PayloadLen=2B
# DataType=1B  TTL=1B  DstRID=8B  SrcRID=8B
# ---------------------------------------------------------------------------
RID_HEADER_BYTES = 24

# ---------------------------------------------------------------------------
# Default TTL values
# ---------------------------------------------------------------------------
DEFAULT_TTL = 64
