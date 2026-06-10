"""RID-based core routing – 2-D grid prefix-product matching.

Algorithm (document §3 / Fig.7)
--------------------------------
Given a destination RID *dst*, the CR iterates all RID routing entries
in the matching space and selects the one whose

    X_prefix_len × Y_prefix_len

is **largest** (longest 2-D match).

If no entry matches, the packet is sent to a default gateway (if
configured) or dropped.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..common.addressing import RID, RIDSpace
from ..tables.cr_tables import RIDRouteEntry, CRTables


def rid_lookup(
    tables: CRTables,
    dst_rid: RID,
    space_id: int,
) -> Optional[RIDRouteEntry]:
    """Return the best-matching RID route entry, or None.

    Selection metric: ``X_prefix × Y_prefix`` (higher = better).
    Ties are broken by larger X-prefix first, then larger Y-prefix.
    """
    best: Optional[RIDRouteEntry] = None
    best_product = -1
    best_x_mask = -1
    best_y_mask = -1

    for entry in tables.rid_routes:
        if entry.space_id != space_id:
            continue
        ds = entry.dest_rid_space
        target_rid = RID(ds.x, ds.y)

        # Check if destination falls in this entry's RID space
        xp = RID.common_prefix_bits(dst_rid.x, target_rid.x, 32)
        yp = RID.common_prefix_bits(dst_rid.y, target_rid.y, 32)

        # Require at least the mask bits to match
        if xp < ds.x_mask_bits or yp < ds.y_mask_bits:
            continue

        # Product = M1 × M2  (the space's prefix-length product)
        product = ds.x_mask_bits * ds.y_mask_bits

        if (product > best_product
                or (product == best_product and ds.x_mask_bits > best_x_mask)
                or (product == best_product and ds.x_mask_bits == best_x_mask
                    and ds.y_mask_bits > best_y_mask)):
            best = entry
            best_product = product
            best_x_mask = ds.x_mask_bits
            best_y_mask = ds.y_mask_bits

    return best


def rid_lookup_next_hop(
    tables: CRTables,
    dst_rid: RID,
    space_id: int,
) -> Optional[RID]:
    """Return the next-hop RID for *dst_rid*."""
    entry = rid_lookup(tables, dst_rid, space_id)
    return entry.next_hop_rid if entry else None


def rid_route_add(
    tables: CRTables,
    space_id: int,
    x: int, y: int,
    x_mask: int, y_mask: int,
    next_hop_rid: RID,
) -> None:
    """Add a RID routing entry."""
    entry = RIDRouteEntry(
        space_id=space_id,
        dest_rid_space=RIDSpace(x=x, y=y, x_mask_bits=x_mask, y_mask_bits=y_mask),
        next_hop_rid=next_hop_rid,
    )
    tables.rid_routes.append(entry)


def rid_route_remove(
    tables: CRTables,
    space_id: int,
    x: int, y: int,
    x_mask: int, y_mask: int,
) -> bool:
    """Remove a RID routing entry; return True if found."""
    target_space = RIDSpace(x=x, y=y, x_mask_bits=x_mask, y_mask_bits=y_mask)
    for i, entry in enumerate(tables.rid_routes):
        if entry.space_id == space_id and entry.dest_rid_space == target_space:
            tables.rid_routes.pop(i)
            return True
    return False


# ============================================================================
#  Debug helpers
# ============================================================================


def dump_rid_routes(tables: CRTables) -> str:
    lines = ["RID Routing Table:", "-" * 60]
    for e in tables.rid_routes:
        lines.append(
            f"  space={e.space_id:4d}  dest={e.dest_rid_space!s:30s}"
            f"  →  next_hop={e.next_hop_rid!s}"
        )
    return "\n".join(lines)
