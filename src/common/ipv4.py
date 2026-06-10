"""Minimal IPv4 header support for realistic Identifier Network payloads.

Provides just enough IPv4 to construct/parse packets carried inside AID.
Not a full TCP/IP stack — only header serialisation.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# IPv4 header (no options): 20 bytes
IPV4_HEADER_STRUCT = struct.Struct("!BBHHHBBH4s4s")


@dataclass
class IPv4Packet:
    """A bare-bones IPv4 datagram."""

    src_ip: str       # "192.168.1.100"
    dst_ip: str       # "192.168.2.100"
    payload: bytes     # TCP/UDP/HTTP …
    protocol: int = 6  # TCP=6, UDP=17
    ttl: int = 64
    identification: int = 0

    # ------------------------------------------------------------------
    def serialize(self) -> bytes:
        ver_ihl = 0x45  # version 4, IHL 5 (20 bytes)
        dscp_ecn = 0
        total_len = 20 + len(self.payload)
        flags_offset = 0x4000  # DF flag
        checksum = 0  # simplified — no real checksum for simulation
        src_b = _ip_to_bytes(self.src_ip)
        dst_b = _ip_to_bytes(self.dst_ip)

        return IPV4_HEADER_STRUCT.pack(
            ver_ihl, dscp_ecn, total_len,
            self.identification, flags_offset,
            self.ttl, self.protocol, checksum,
            src_b, dst_b,
        ) + self.payload

    @classmethod
    def deserialize(cls, data: bytes) -> IPv4Packet:
        if len(data) < 20:
            raise ValueError(f"IPv4: need ≥20 bytes, got {len(data)}")
        (
            _ver_ihl, _dscp, total_len, ident,
            _flags, ttl, proto, _csum, src_b, dst_b,
        ) = IPV4_HEADER_STRUCT.unpack(data[:20])
        return cls(
            src_ip=_bytes_to_ip(src_b),
            dst_ip=_bytes_to_ip(dst_b),
            payload=data[20:total_len],
            protocol=proto,
            ttl=ttl,
            identification=ident,
        )

    @property
    def total_length(self) -> int:
        return 20 + len(self.payload)


def _ip_to_bytes(ip: str) -> bytes:
    return bytes(int(x) for x in ip.split("."))


def _bytes_to_ip(b: bytes) -> str:
    return ".".join(str(x) for x in b)
