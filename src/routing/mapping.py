"""AID ↔ RID mapping management.

Implements the "encapsulation mapping" approach (document §2.4, Fig.6):
the entire AID packet is wrapped inside a RID packet for core transit.
"""

from __future__ import annotations

from typing import Optional

from ..common.addressing import AID, RID
from ..tables.cr_tables import CRTables, MappingEntry
from ..tables.cs_tables import CSDatabase, MappingRegistryEntry


# ============================================================================
#  CR-side mapping helpers
# ============================================================================


def cr_has_local_mapping(tables: CRTables, aid: AID) -> bool:
    return aid in tables.local_mappings


def cr_lookup_local_mapping(tables: CRTables, aid: AID) -> Optional[RID]:
    return tables.local_mappings.get(aid)


def cr_lookup_remote_mapping(tables: CRTables, aid: AID) -> Optional[MappingEntry]:
    return tables.remote_mappings.get(aid)


def cr_lookup_any_mapping(tables: CRTables, aid: AID) -> Optional[MappingEntry]:
    """Look up mapping for *aid* (local first, then remote)."""
    local_rid = tables.local_mappings.get(aid)
    if local_rid is not None:
        # local mapping → remote_cr_rid is self (not applicable)
        return MappingEntry(aid=aid, mapped_rid=local_rid, remote_cr_rid=RID(0, 0))
    return tables.remote_mappings.get(aid)


def cr_add_local_mapping(
    tables: CRTables, aid: AID, mapped_rid: RID, space_id: int = 0
) -> None:
    tables.local_mappings[aid] = mapped_rid


def cr_add_remote_mapping(
    tables: CRTables, aid: AID, mapped_rid: RID, remote_cr_rid: RID, space_id: int = 0
) -> None:
    tables.remote_mappings[aid] = MappingEntry(
        aid=aid, mapped_rid=mapped_rid, remote_cr_rid=remote_cr_rid, space_id=space_id
    )


def cr_update_mapping(
    tables: CRTables, aid: AID, new_rid: RID, new_cr_rid: RID
) -> None:
    """Update a (remote) mapping entry after mobility handover."""
    if aid in tables.remote_mappings:
        tables.remote_mappings[aid].mapped_rid = new_rid
        tables.remote_mappings[aid].remote_cr_rid = new_cr_rid
    else:
        cr_add_remote_mapping(tables, aid, new_rid, new_cr_rid)


def cr_remove_mapping(tables: CRTables, aid: AID) -> None:
    tables.local_mappings.pop(aid, None)
    tables.remote_mappings.pop(aid, None)


# ============================================================================
#  CS-side mapping helpers
# ============================================================================


def cs_register_mapping(
    db: CSDatabase, aid: AID, mapped_rid: RID, remote_cr_rid: RID, space_id: int = 0
) -> None:
    db.mappings[aid] = MappingRegistryEntry(
        aid=aid, mapped_rid=mapped_rid, remote_cr_rid=remote_cr_rid, space_id=space_id
    )


def cs_query_mapping(db: CSDatabase, aid: AID) -> Optional[MappingRegistryEntry]:
    return db.mappings.get(aid)
