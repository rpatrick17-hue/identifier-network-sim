"""Binary serialisation / deserialisation helpers.

All identifier-network packet formats are fixed-width; we use the ``struct``
module for maximum portability and performance.
"""

from __future__ import annotations

import struct
from typing import Tuple

# ============================================================================
#  Struct format strings  (network byte-order throughout)
# ============================================================================

# AID header  (40 bytes)
#   version(4b) + id_type(4b)  → 1B
#   qos(8b)                    → 1B
#   reserved(16b)              → 2B
#   payload_len(16b)           → 2B
#   data_type(8b)              → 1B
#   ttl(8b)                    → 1B
#   src_aid(128b)              → 16s
#   dst_aid(128b)              → 16s
AID_HEADER_STRUCT = struct.Struct("!BBHHBB16s16s")  # 40 bytes
assert AID_HEADER_STRUCT.size == 40

# RID header  (24 bytes) — per 任务书 §5.4: SrcRID before DstRID
#   version(4b) + id_type(4b)  → 1B
#   qos(8b)                    → 1B
#   space_id(16b)              → 2B
#   payload_len(16b)           → 2B
#   data_type(8b)              → 1B
#   ttl(8b)                    → 1B
#   src_rid(64b)               → 8B (Q = unsigned long long)
#   dst_rid(64b)               → 8B
RID_HEADER_STRUCT = struct.Struct("!BBHHBBQQ")  # 24 bytes
assert RID_HEADER_STRUCT.size == 24

# Ethernet header  (14 bytes) – dst(6) + src(6) + ethertype(2)
ETH_HEADER_STRUCT = struct.Struct("!6s6sH")
assert ETH_HEADER_STRUCT.size == 14


# ============================================================================
#  Helper functions
# ============================================================================

def pack_aid_header(
    qos_class: int,
    payload_length: int,
    data_type: int,
    ttl: int,
    src_aid_bytes: bytes,
    dst_aid_bytes: bytes,
    version: int = 1,
    id_type: int = 0b1000,
) -> bytes:
    """Pack an AID header (40 bytes)."""
    ver_id = (version << 4) | id_type
    return AID_HEADER_STRUCT.pack(
        ver_id, qos_class, 0, payload_length, data_type, ttl, src_aid_bytes, dst_aid_bytes
    )


def unpack_aid_header(data: bytes) -> dict:
    """Unpack an AID header, returning a dict of fields."""
    ver_id, qos, _reserved, plen, dtype, ttl, src, dst = AID_HEADER_STRUCT.unpack(data)
    return {
        "version": (ver_id >> 4) & 0xF,
        "id_type": ver_id & 0xF,
        "qos_class": qos,
        "payload_length": plen,
        "data_type": dtype,
        "ttl": ttl,
        "source_aid_bytes": src,
        "destination_aid_bytes": dst,
    }


def pack_rid_header(
    qos_class: int,
    space_id: int,
    payload_length: int,
    data_type: int,
    ttl: int,
    src_rid_int: int,
    dst_rid_int: int,
    version: int = 1,
    id_type: int = 0b0100,
) -> bytes:
    """Pack a RID header (24 bytes).  SrcRID before DstRID per 任务书 §5.4."""
    ver_id = (version << 4) | id_type
    return RID_HEADER_STRUCT.pack(
        ver_id, qos_class, space_id, payload_length, data_type, ttl, src_rid_int, dst_rid_int
    )


def unpack_rid_header(data: bytes) -> dict:
    """Unpack a RID header, returning a dict of fields."""
    ver_id, qos, sid, plen, dtype, ttl, src, dst = RID_HEADER_STRUCT.unpack(data)
    return {
        "version": (ver_id >> 4) & 0xF,
        "id_type": ver_id & 0xF,
        "qos_class": qos,
        "network_space_id": sid,
        "payload_length": plen,
        "data_type": dtype,
        "ttl": ttl,
        "source_rid_int": src,
        "destination_rid_int": dst,
    }


def pack_ethernet_header(dst_mac: bytes, src_mac: bytes, ethertype: int) -> bytes:
    return ETH_HEADER_STRUCT.pack(dst_mac, src_mac, ethertype)


def unpack_ethernet_header(data: bytes) -> Tuple[bytes, bytes, int]:
    dst, src, etype = ETH_HEADER_STRUCT.unpack(data)
    return dst, src, etype
