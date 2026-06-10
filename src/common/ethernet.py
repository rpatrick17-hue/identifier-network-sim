"""Ethernet frame helpers for Identifier Network.

Uses custom EtherType values to distinguish AID / RID packets on the wire:
    - 0x88B5  →  AID packet  (Access Identifier)
    - 0x88B6  →  RID packet  (Route Identifier)
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import ETHERTYPE_AID, ETHERTYPE_RID, RID_HEADER_BYTES
from .packets import AIDPacket, RIDPacket
from .serializer import ETH_HEADER_STRUCT


def mac_from_str(s: str) -> bytes:
    """Convert "00:0c:ab:1e:76:8a" → bytes."""
    return bytes(int(b, 16) for b in s.split(":"))


def mac_to_str(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


@dataclass
class EthernetFrame:
    """A raw Ethernet frame carrying an AID or RID packet."""

    dst_mac: bytes  # 6 bytes
    src_mac: bytes  # 6 bytes
    ethertype: int  # 2 bytes
    payload: bytes

    # ------------------------------------------------------------------

    def serialize(self) -> bytes:
        return ETH_HEADER_STRUCT.pack(self.dst_mac, self.src_mac, self.ethertype) + self.payload

    @classmethod
    def deserialize(cls, data: bytes) -> EthernetFrame:
        dst, src, etype = ETH_HEADER_STRUCT.unpack(data[:14])
        return cls(dst_mac=dst, src_mac=src, ethertype=etype, payload=data[14:])

    @classmethod
    def from_aid_packet(cls, pkt: AIDPacket, dst_mac: bytes, src_mac: bytes) -> EthernetFrame:
        return cls(dst_mac=dst_mac, src_mac=src_mac, ethertype=ETHERTYPE_AID, payload=pkt.serialize())

    @classmethod
    def from_rid_packet(cls, pkt: RIDPacket, dst_mac: bytes, src_mac: bytes) -> EthernetFrame:
        return cls(dst_mac=dst_mac, src_mac=src_mac, ethertype=ETHERTYPE_RID, payload=pkt.serialize())

    # ------------------------------------------------------------------

    @property
    def is_aid(self) -> bool:
        return self.ethertype == ETHERTYPE_AID

    @property
    def is_rid(self) -> bool:
        return self.ethertype == ETHERTYPE_RID

    def inner_aid(self) -> AIDPacket:
        if not self.is_aid:
            raise TypeError(f"EtherType 0x{self.ethertype:04x} is not AID")
        return AIDPacket.deserialize(self.payload)

    def inner_rid(self) -> RIDPacket:
        if not self.is_rid:
            raise TypeError(f"EtherType 0x{self.ethertype:04x} is not RID")
        return RIDPacket.deserialize(self.payload)

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        etype = "AID" if self.is_aid else ("RID" if self.is_rid else f"0x{self.ethertype:04x}")
        return (
            f"EthFrame({mac_to_str(self.src_mac)} → {mac_to_str(self.dst_mac)}, "
            f"type={etype}, payload={len(self.payload)}B)"
        )
