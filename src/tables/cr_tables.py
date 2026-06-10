"""Core Router (CR) in-memory table definitions.

Each CR maintains 9 table structures.  This module provides the plain
dataclass / container definitions; mutation logic lives in
``routing/`` and ``nodes/core_router.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from ..common.constants import InterfaceStatus, InterfaceType, SpacePolicy, UserStatus
from ..common.addressing import AID, RID, RIDSpace


# ============================================================================
#  1. Interface Table
# ============================================================================


@dataclass
class InterfaceEntry:
    index: int
    name: str
    mac: str  # "00:0c:ab:..."  human-readable
    status: InterfaceStatus = InterfaceStatus.UP
    if_type: InterfaceType = InterfaceType.ACCESS


# ============================================================================
#  2. RID Space Table
# ============================================================================


@dataclass
class RIDSpaceEntry:
    space_id: int
    rid_space: RIDSpace  # (x, y, x_mask_bits, y_mask_bits)
    policy: SpacePolicy = SpacePolicy.DEFAULT


# ============================================================================
#  3. ROUTE Neighbour Table  (core side)
# ============================================================================


@dataclass
class RouteNeighborEntry:
    space_id: int
    neighbor_rid: RID
    neighbor_mac: str
    interface_index: int


# ============================================================================
#  4. ACCESS Neighbour Table  (access side)
# ============================================================================


@dataclass
class AccessNeighborEntry:
    neighbor_aid: AID
    neighbor_mac: str
    interface_index: int


# ============================================================================
#  5. RID Routing Table
# ============================================================================


@dataclass
class RIDRouteEntry:
    """A RID routing-table row.

    ``dest_rid_space`` is a RIDSpace that describes the destination
    prefix.  ``next_hop_rid`` is the immediate next CR's RID.
    """

    space_id: int
    dest_rid_space: RIDSpace
    next_hop_rid: RID


# ============================================================================
#  6. AID Routing Table
# ============================================================================


@dataclass
class AIDRouteEntry:
    destination_aid: AID
    next_hop_aid: AID


# ============================================================================
#  7. Mapping Table  (local + remote)
# ============================================================================


@dataclass
class MappingEntry:
    aid: AID
    mapped_rid: RID
    remote_cr_rid: RID
    space_id: int = 0


# ============================================================================
#  8. Associated AP List
# ============================================================================


@dataclass
class AssociatedAPEntry:
    ap_aid: AID
    ap_rid: RID
    interface_index: int


# ============================================================================
#  9. User Status List
# ============================================================================


@dataclass
class UserStatusEntry:
    user_aid: AID
    ap_aid: AID
    status: UserStatus = UserStatus.ONLINE
    custom_attributes: str = ""  # e.g. "UR:3;BW:10Mbps"


# ============================================================================
#  Aggregate CR table holder
# ============================================================================


@dataclass
class CRTables:
    """All CR-side tables in one place."""

    interfaces: Dict[int, InterfaceEntry] = field(default_factory=dict)
    rid_spaces: Dict[int, RIDSpaceEntry] = field(default_factory=dict)
    route_neighbors: List[RouteNeighborEntry] = field(default_factory=list)
    access_neighbors: List[AccessNeighborEntry] = field(default_factory=list)
    rid_routes: List[RIDRouteEntry] = field(default_factory=list)
    aid_routes: List[AIDRouteEntry] = field(default_factory=list)
    local_mappings: Dict[AID, RID] = field(default_factory=dict)
    remote_mappings: Dict[AID, MappingEntry] = field(default_factory=dict)
    associated_aps: Dict[AID, AssociatedAPEntry] = field(default_factory=dict)
    user_statuses: Dict[AID, UserStatusEntry] = field(default_factory=dict)

    # -- helpers ------------------------------------------------------------

    def rid_space_for(self, space_id: int) -> Optional[RIDSpaceEntry]:
        return self.rid_spaces.get(space_id)

    def matching_rid_space(self, rid: RID) -> Optional[RIDSpaceEntry]:
        """Return the first RID space entry whose prefix covers *rid*."""
        for entry in self.rid_spaces.values():
            if entry.rid_space.contains(rid):
                return entry
        return None

    def is_local_rid(self, rid: RID) -> bool:
        """Check whether *rid* is associated with a local AP."""
        for ap in self.associated_aps.values():
            if ap.ap_rid == rid:
                return True
        return False

    def is_local_aid(self, aid: AID) -> bool:
        """Check whether *aid* is a locally-attached user."""
        entry = self.user_statuses.get(aid)
        return entry is not None and entry.status == UserStatus.ONLINE

    def user_ap_aid(self, user_aid: AID) -> Optional[AID]:
        """Return the AP-AID that serves *user_aid*, if local."""
        entry = self.user_statuses.get(user_aid)
        if entry and entry.status == UserStatus.ONLINE:
            return entry.ap_aid
        return None

    def ap_interface(self, ap_aid: AID) -> Optional[int]:
        """Return the interface index for a given AP."""
        ap = self.associated_aps.get(ap_aid)
        return ap.interface_index if ap else None
