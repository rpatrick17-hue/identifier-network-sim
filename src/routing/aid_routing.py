"""AID-based access-side routing – exact-match lookup.

In the access network data is forwarded according to AID.  The AID
routing table maps destination AID → next-hop AID.
"""

from __future__ import annotations

from typing import Optional

from ..common.addressing import AID
from ..tables.cr_tables import AIDRouteEntry, CRTables


def aid_lookup(tables: CRTables, dst_aid: AID) -> Optional[AIDRouteEntry]:
    """Exact-match AID route lookup."""
    for entry in tables.aid_routes:
        if entry.destination_aid == dst_aid:
            return entry
    return None


def aid_lookup_next_hop(tables: CRTables, dst_aid: AID) -> Optional[AID]:
    entry = aid_lookup(tables, dst_aid)
    return entry.next_hop_aid if entry else None


def aid_route_add(tables: CRTables, dst_aid: AID, next_hop_aid: AID) -> None:
    tables.aid_routes.append(AIDRouteEntry(destination_aid=dst_aid, next_hop_aid=next_hop_aid))
