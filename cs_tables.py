"""Control Server (CS) database definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..common.addressing import AID, RID


# ============================================================================
#  User Registry entry  (document §4.2 / Table 9)
# ============================================================================


@dataclass
class UserRegistryEntry:
    user_aid: AID
    pin: str             # PIN code
    username: str
    password: str
    custom_attributes: str = ""  # e.g. "UR:3;BW:10Mbps"

    def parse_attributes(self) -> Dict[str, str]:
        """Parse "UR:3;BW:10Mbps" → {"UR": "3", "BW": "10Mbps"}."""
        attrs: Dict[str, str] = {}
        if self.custom_attributes:
            for part in self.custom_attributes.split(";"):
                if ":" in part:
                    k, v = part.split(":", 1)
                    attrs[k.strip()] = v.strip()
        return attrs


# ============================================================================
#  Mapping Registry
# ============================================================================


@dataclass
class MappingRegistryEntry:
    aid: AID
    mapped_rid: RID
    remote_cr_rid: RID
    space_id: int = 0
    registered_by_ap: Optional[AID] = None  # which AP registered this


# ============================================================================
#  CS database holder
# ============================================================================


@dataclass
class CSDatabase:
    """All CS-side tables."""

    # User Registry  (username → entry)
    users: Dict[str, UserRegistryEntry] = field(default_factory=dict)

    # AID → UserRegistryEntry  fast lookup
    aid_to_user: Dict[AID, UserRegistryEntry] = field(default_factory=dict)

    # Mapping Registry  (AID → MappingRegistryEntry)
    mappings: Dict[AID, MappingRegistryEntry] = field(default_factory=dict)

    # Managed CR list  (cr_rid → name)
    managed_crs: Dict[RID, str] = field(default_factory=dict)

    # Managed AP list  (ap_rid → name)
    managed_aps: Dict[RID, str] = field(default_factory=dict)

    # AP → CR mapping  (ap_rid → cr_rid)
    ap_to_cr: Dict[RID, RID] = field(default_factory=dict)

    # Managed AP list  (ap_rid → name)
    managed_aps: Dict[RID, str] = field(default_factory=dict)

    # -- helpers ------------------------------------------------------------

    def add_user(self, entry: UserRegistryEntry) -> None:
        self.users[entry.username] = entry
        self.aid_to_user[entry.user_aid] = entry

    def authenticate(self, username: str, password: str) -> Optional[UserRegistryEntry]:
        entry = self.users.get(username)
        if entry and entry.password == password:
            return entry
        return None

    def lookup_aid_by_ip(self, ip_address: str) -> Optional[AID]:
        """Stub – in real system IP→AID mapping would be maintained."""
        # For now we iterate and match custom_attributes (simplification)
        for entry in self.users.values():
            if ip_address in entry.custom_attributes:
                return entry.user_aid
        return None
