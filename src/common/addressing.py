"""Address types for Identifier Network.

AID (Access Identifier): 128-bit hash-based user identity, immutable during
    a session.  Generated from user attributes (username + device fingerprint).

RID (Route Identifier): 64-bit 2-D grid coordinate (X | Y), used for
    routing in the core network.  Each 32-bit coordinate may carry a
    prefix-length mask for hierarchical matching.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


# ============================================================================
#  AID  – 128-bit Access Identifier
# ============================================================================

@dataclass(frozen=True, order=True)
class AID:
    """128-bit Access Identifier.

    Internally stored as a Python int (0 .. 2**128-1).  Immutable and
    hashable so it can be used as a dict key / set member.
    """

    value: int  # 0 .. 2^128-1

    def __post_init__(self) -> None:
        if not (0 <= self.value < (1 << 128)):
            raise ValueError(f"AID value 0x{self.value:032x} out of 128-bit range")

    # -- constructors --------------------------------------------------------

    @classmethod
    def from_hash(cls, data: bytes) -> AID:
        """SHA-256 truncated to 128 bits."""
        h = hashlib.sha256(data).digest()[:16]
        return cls(int.from_bytes(h, "big"))

    @classmethod
    def from_hex(cls, hex_str: str) -> AID:
        return cls(int(hex_str, 16))

    @classmethod
    def from_bytes(cls, b: bytes) -> AID:
        if len(b) != 16:
            raise ValueError(f"AID.from_bytes expects 16 bytes, got {len(b)}")
        return cls(int.from_bytes(b, "big"))

    # -- serialisation -------------------------------------------------------

    def to_bytes(self) -> bytes:
        return self.value.to_bytes(16, "big")

    def to_hex(self) -> str:
        return format(self.value, "032x")

    # -- display -------------------------------------------------------------

    def __repr__(self) -> str:
        h = self.to_hex()
        return f"AID({h[:8]}…{h[-4:]})"


# ============================================================================
#  RID  – 64-bit Route Identifier  (X | Y)
# ============================================================================

@dataclass(frozen=True, order=True)
class RID:
    """64-bit Route Identifier composed of two 32-bit grid coordinates.

    x : 32-bit unsigned  – X-axis coordinate
    y : 32-bit unsigned  – Y-axis coordinate

    Together they form a 2-D address space.  Routing uses *prefix-product*
    matching: the route whose (X-prefix-len × Y-prefix-len) is largest wins.
    """

    x: int  # 0 .. 2^32-1
    y: int  # 0 .. 2^32-1

    def __post_init__(self) -> None:
        if not (0 <= self.x < (1 << 32)):
            raise ValueError(f"RID.x={self.x} out of 32-bit range")
        if not (0 <= self.y < (1 << 32)):
            raise ValueError(f"RID.y={self.y} out of 32-bit range")

    # -- properties ----------------------------------------------------------

    @property
    def as_int(self) -> int:
        """64-bit integer: (x << 32) | y."""
        return (self.x << 32) | self.y

    # -- constructors --------------------------------------------------------

    @classmethod
    def from_int(cls, value: int) -> RID:
        x = (value >> 32) & 0xFFFFFFFF
        y = value & 0xFFFFFFFF
        return cls(x, y)

    @classmethod
    def from_bytes(cls, b: bytes) -> RID:
        if len(b) != 8:
            raise ValueError(f"RID.from_bytes expects 8 bytes, got {len(b)}")
        return cls.from_int(int.from_bytes(b, "big"))

    @classmethod
    def from_tuple(cls, t: tuple[int, int]) -> RID:
        return cls(t[0], t[1])

    # -- serialisation -------------------------------------------------------

    def to_bytes(self) -> bytes:
        return self.as_int.to_bytes(8, "big")

    def to_tuple(self) -> tuple[int, int]:
        return (self.x, self.y)

    # -- prefix helpers (used by routing) ------------------------------------

    @staticmethod
    def common_prefix_bits(a: int, b: int, width: int = 32) -> int:
        """Count of leading identical bits between *a* and *b* (max *width*)."""
        if a == b:
            return width
        xor = a ^ b
        # count leading zeros of xor (Python int is arbitrary precision)
        leading = xor.bit_length()
        return max(0, width - leading)

    def x_prefix_match(self, other: RID) -> int:
        return self.common_prefix_bits(self.x, other.x, 32)

    def y_prefix_match(self, other: RID) -> int:
        return self.common_prefix_bits(self.y, other.y, 32)

    def prefix_product(self, other: RID) -> int:
        """X-prefix-len × Y-prefix-len used by RID routing algorithm."""
        return self.x_prefix_match(other) * self.y_prefix_match(other)

    # -- display -------------------------------------------------------------

    def __repr__(self) -> str:
        return f"RID({self.x}, {self.y})"


# ============================================================================
#  RID Space descriptor  (used in configuration & routing tables)
# ============================================================================

@dataclass(frozen=True)
class RIDSpace:
    """A RID space defined by a base coordinate and X/Y prefix lengths.

    Stored as (x | x_mask_bits, y | y_mask_bits) where *mask_bits* is the
    number of significant bits (0..32).
    """

    x: int = 0
    y: int = 0
    x_mask_bits: int = 0   # how many MSBs of X are significant
    y_mask_bits: int = 0   # how many MSBs of Y are significant

    def __post_init__(self) -> None:
        if not (0 <= self.x_mask_bits <= 32):
            raise ValueError(f"x_mask_bits={self.x_mask_bits}")
        if not (0 <= self.y_mask_bits <= 32):
            raise ValueError(f"y_mask_bits={self.y_mask_bits}")

    def contains(self, rid: RID) -> bool:
        """Check whether *rid* falls inside this space."""
        if self.x_mask_bits > 0:
            shift = 32 - self.x_mask_bits
            if (rid.x >> shift) != (self.x >> shift):
                return False
        if self.y_mask_bits > 0:
            shift = 32 - self.y_mask_bits
            if (rid.y >> shift) != (self.y >> shift):
                return False
        return True

    def to_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x_mask_bits, self.y_mask_bits)

    def __repr__(self) -> str:
        return f"RIDSpace({self.x}|{self.x_mask_bits}, {self.y}|{self.y_mask_bits})"
