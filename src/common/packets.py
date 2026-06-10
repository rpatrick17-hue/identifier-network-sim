"""AID / RID packet definitions with serialisation support."""

from __future__ import annotations

from dataclasses import dataclass, field

from .addressing import AID, RID
from .constants import (
    AID_HEADER_BYTES,
    DEFAULT_TTL,
    RID_HEADER_BYTES,
    DataType,
    IDType,
    Version,
)
from .serializer import (
    AID_HEADER_STRUCT,
    RID_HEADER_STRUCT,
)


# ============================================================================
#  AID Packet  – 40-byte header + variable payload
# ============================================================================

@dataclass
class AIDPacket:
    """Access Identifier Data Packet.

    Works in the *access network*.  The payload is typically a traditional
    IPv4 / IPv6 datagram.
    """

    source_aid: AID = field(default_factory=lambda: AID(0))
    destination_aid: AID = field(default_factory=lambda: AID(0))
    payload: bytes = b""
    qos_class: int = 0
    data_type: DataType = DataType.USER_DATA
    ttl: int = DEFAULT_TTL

    # -- serialisation -------------------------------------------------------

    def serialize(self) -> bytes:
        """Return ``header + payload`` as bytes."""
        ver_id = (Version.V1 << 4) | IDType.AID
        header = AID_HEADER_STRUCT.pack(
            ver_id,
            self.qos_class,
            0,  # reserved
            len(self.payload),
            int(self.data_type),
            self.ttl,
            self.source_aid.to_bytes(),
            self.destination_aid.to_bytes(),
        )
        return header + self.payload

    @classmethod
    def deserialize(cls, data: bytes) -> AIDPacket:
        """Parse bytes back into an AIDPacket."""
        if len(data) < AID_HEADER_BYTES:
            raise ValueError(
                f"AIDPacket: need ≥{AID_HEADER_BYTES} bytes, got {len(data)}"
            )

        (
            ver_id,
            qos,
            _reserved,
            payload_len,
            data_type,
            ttl,
            src_b,
            dst_b,
        ) = AID_HEADER_STRUCT.unpack(data[:AID_HEADER_BYTES])

        version = (ver_id >> 4) & 0xF
        id_type = ver_id & 0xF

        if version != Version.V1:
            raise ValueError(f"AIDPacket: unsupported version {version}")
        if id_type != IDType.AID:
            raise ValueError(f"AIDPacket: wrong id_type {id_type:#06b}")

        payload = data[AID_HEADER_BYTES : AID_HEADER_BYTES + payload_len]

        return cls(
            source_aid=AID(int.from_bytes(src_b, "big")),
            destination_aid=AID(int.from_bytes(dst_b, "big")),
            payload=payload,
            qos_class=qos,
            data_type=DataType(data_type),
            ttl=ttl,
        )

    # -- helpers -------------------------------------------------------------

    @property
    def header_bytes(self) -> int:
        return AID_HEADER_BYTES

    @property
    def total_length(self) -> int:
        return AID_HEADER_BYTES + len(self.payload)

    def decrement_ttl(self) -> bool:
        """Return True if packet is still alive after decrement."""
        if self.ttl <= 1:
            return False
        self.ttl -= 1
        return True

    def __repr__(self) -> str:
        return (
            f"AIDPacket(src={self.source_aid}, dst={self.destination_aid}, "
            f"ttl={self.ttl}, payload={len(self.payload)}B)"
        )


# ============================================================================
#  RID Packet  – 24-byte header + variable payload
# ============================================================================

@dataclass
class RIDPacket:
    """Route Identifier Data Packet.

    Works in the *core network*.  The payload is typically an AID packet
    (encapsulation mapping mode).
    """

    source_rid: RID = field(default_factory=lambda: RID(0, 0))
    destination_rid: RID = field(default_factory=lambda: RID(0, 0))
    payload: bytes = b""
    qos_class: int = 0
    network_space_id: int = 0
    data_type: DataType = DataType.USER_DATA
    ttl: int = DEFAULT_TTL

    # -- serialisation -------------------------------------------------------

    def serialize(self) -> bytes:
        """Return ``header + payload`` as bytes."""
        ver_id = (Version.V1 << 4) | IDType.RID
        header = RID_HEADER_STRUCT.pack(
            ver_id,
            self.qos_class,
            self.network_space_id,
            len(self.payload),
            int(self.data_type),
            self.ttl,
            self.source_rid.as_int,
            self.destination_rid.as_int,
        )
        return header + self.payload

    @classmethod
    def deserialize(cls, data: bytes) -> RIDPacket:
        """Parse bytes back into a RIDPacket."""
        if len(data) < RID_HEADER_BYTES:
            raise ValueError(
                f"RIDPacket: need ≥{RID_HEADER_BYTES} bytes, got {len(data)}"
            )

        (
            ver_id,
            qos,
            space_id,
            payload_len,
            data_type,
            ttl,
            src_int,
            dst_int,
        ) = RID_HEADER_STRUCT.unpack(data[:RID_HEADER_BYTES])

        version = (ver_id >> 4) & 0xF
        id_type = ver_id & 0xF

        if version != Version.V1:
            raise ValueError(f"RIDPacket: unsupported version {version}")
        if id_type != IDType.RID:
            raise ValueError(f"RIDPacket: wrong id_type {id_type:#06b}")

        payload = data[RID_HEADER_BYTES : RID_HEADER_BYTES + payload_len]

        return cls(
            source_rid=RID.from_int(src_int),
            destination_rid=RID.from_int(dst_int),
            payload=payload,
            qos_class=qos,
            network_space_id=space_id,
            data_type=DataType(data_type),
            ttl=ttl,
        )

    # -- helpers -------------------------------------------------------------

    @property
    def header_bytes(self) -> int:
        return RID_HEADER_BYTES

    @property
    def total_length(self) -> int:
        return RID_HEADER_BYTES + len(self.payload)

    def decrement_ttl(self) -> bool:
        """Return True if packet is still alive after decrement."""
        if self.ttl <= 1:
            return False
        self.ttl -= 1
        return True

    def __repr__(self) -> str:
        return (
            f"RIDPacket(src={self.source_rid}, dst={self.destination_rid}, "
            f"space={self.network_space_id}, ttl={self.ttl}, "
            f"payload={len(self.payload)}B)"
        )
