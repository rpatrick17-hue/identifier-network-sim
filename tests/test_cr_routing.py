"""Tests for CR routing algorithms: RID 2-D prefix-product, AID lookup, mapping."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.common.addressing import RID, RIDSpace, AID
from src.common.constants import SpacePolicy
from src.routing.rid_routing import (
    rid_lookup,
    rid_lookup_next_hop,
    rid_route_add,
)
from src.routing.aid_routing import aid_lookup, aid_lookup_next_hop, aid_route_add
from src.routing.mapping import (
    cr_add_local_mapping,
    cr_add_remote_mapping,
    cr_lookup_any_mapping,
    cr_update_mapping,
)
from src.tables.cr_tables import CRTables


class TestRIDRouting:
    """Test the 2-D prefix-product routing algorithm."""

    @pytest.fixture
    def tables(self) -> CRTables:
        t = CRTables()
        # spaces
        t.rid_spaces[0] = RIDSpace(x=10028, y=36181, x_mask_bits=20, y_mask_bits=20)
        t.rid_spaces[100] = RIDSpace(x=12345, y=34267, x_mask_bits=20, y_mask_bits=24)
        # routes
        rid_route_add(t, 100, 12345, 34267, 20, 24, RID(12360, 34280))
        rid_route_add(t, 100, 10000, 30000, 8, 8, RID(10001, 36191))
        return t

    def test_exact_match(self, tables):
        """Destination exactly matches a route entry."""
        result = rid_lookup(tables, RID(12345, 34267), 100)
        assert result is not None
        assert result.next_hop_rid == RID(12360, 34280)

    def test_prefix_match(self, tables):
        """Destination shares prefix with a route entry."""
        # RID(12346, 34268) shares high bits with (12345, 34267)
        result = rid_lookup(tables, RID(12346, 34268), 100)
        assert result is not None
        # Should match (12345|20, 34267|24) since prefixes overlap
        assert result.next_hop_rid == RID(12360, 34280)

    def test_no_match(self, tables):
        """Destination in wrong space — no prefix match."""
        # RID with top-8 bits different from all route entries
        # 0xFF000000 in top 8 bits vs entries that all have 0x00 in top 8
        result = rid_lookup(tables, RID(0xFF000000, 0xFF000000), 100)
        assert result is None

    def test_wrong_space_id(self, tables):
        """Lookup in a space that doesn't match."""
        result = rid_lookup(tables, RID(12345, 34267), 999)
        assert result is None

    def test_two_routes_choose_best(self, tables):
        """When multiple routes match, choose the one with largest M1×M2 product."""
        # Route 1: (12345|20, 34267|24) → product 480 (existing)
        # Add a more specific route: (12345|22, 34267|26) → product 572
        rid_route_add(tables, 100, 12345, 34267, 22, 26, RID(12370, 34290))
        # Target exactly matches both
        result = rid_lookup(tables, RID(12345, 34267), 100)
        assert result is not None
        # More specific (22×26=572) > (20×24=480)
        assert result.next_hop_rid == RID(12370, 34290)

    def test_next_hop_helper(self, tables):
        hop = rid_lookup_next_hop(tables, RID(12345, 34267), 100)
        assert hop == RID(12360, 34280)

    def test_prefix_product_tiebreaker(self, tables):
        """Tie-breaking: larger X-mask wins on equal product."""
        # Build a clean table for this test
        t = CRTables()
        # Two routes with same product (20×20=400)
        rid_route_add(t, 100, 10000, 30000, 20, 20, RID(99999, 99999))
        rid_route_add(t, 100, 10000, 30000, 25, 16, RID(88888, 88888))  # 25×16=400
        # Target must match both (top 25 X bits and top 20 Y bits)
        target_x = 10000  # same top 25 bits
        target_y = 30000  # same top 20 bits
        result = rid_lookup(t, RID(target_x, target_y), 100)
        assert result is not None
        # 25×16 product = 400, but X-mask 25 > 20 → should win
        assert result.next_hop_rid == RID(88888, 88888)


class TestAIDRouting:
    def test_exact_match(self):
        t = CRTables()
        aid_route_add(t, AID(0xABCD), AID(0x1234))
        entry = aid_lookup(t, AID(0xABCD))
        assert entry is not None
        assert entry.next_hop_aid == AID(0x1234)

    def test_no_match(self):
        t = CRTables()
        assert aid_lookup(t, AID(0xDEAD)) is None


class TestMapping:
    def test_local_mapping(self):
        t = CRTables()
        cr_add_local_mapping(t, AID(0xAAAA), RID(100, 200))
        result = cr_lookup_any_mapping(t, AID(0xAAAA))
        assert result is not None
        assert result.mapped_rid == RID(100, 200)

    def test_remote_mapping(self):
        t = CRTables()
        cr_add_remote_mapping(t, AID(0xBBBB), RID(300, 400), RID(500, 600), space_id=100)
        result = cr_lookup_any_mapping(t, AID(0xBBBB))
        assert result is not None
        assert result.mapped_rid == RID(300, 400)
        assert result.remote_cr_rid == RID(500, 600)
        assert result.space_id == 100

    def test_update_mapping(self):
        t = CRTables()
        cr_add_remote_mapping(t, AID(0xBBBB), RID(300, 400), RID(500, 600))
        # After mobility: update mapping
        cr_update_mapping(t, AID(0xBBBB), RID(700, 800), RID(900, 1000))
        result = cr_lookup_any_mapping(t, AID(0xBBBB))
        assert result.mapped_rid == RID(700, 800)
        assert result.remote_cr_rid == RID(900, 1000)

    def test_mapping_not_found(self):
        t = CRTables()
        assert cr_lookup_any_mapping(t, AID(0xCCCC)) is None


class TestCRTables:
    def test_is_local_aid(self):
        t = CRTables()
        from src.common.constants import UserStatus
        from src.tables.cr_tables import UserStatusEntry
        t.user_statuses[AID(0x1111)] = UserStatusEntry(
            user_aid=AID(0x1111), ap_aid=AID(0x2222), status=UserStatus.ONLINE)
        assert t.is_local_aid(AID(0x1111))

    def test_not_local_if_moved(self):
        t = CRTables()
        from src.common.constants import UserStatus
        from src.tables.cr_tables import UserStatusEntry
        t.user_statuses[AID(0x1111)] = UserStatusEntry(
            user_aid=AID(0x1111), ap_aid=AID(0x2222), status=UserStatus.MOVED_AWAY)
        assert not t.is_local_aid(AID(0x1111))
