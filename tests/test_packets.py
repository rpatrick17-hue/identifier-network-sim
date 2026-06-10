"""Unit tests for packet serialisation / deserialisation."""

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.common.constants import AID_HEADER_BYTES, RID_HEADER_BYTES, DEFAULT_TTL, DataType
from src.common.addressing import AID, RID, RIDSpace
from src.common.packets import AIDPacket, RIDPacket
from src.common.ethernet import EthernetFrame, mac_from_str, mac_to_str
from src.common.serializer import (
    pack_aid_header,
    unpack_aid_header,
    pack_rid_header,
    unpack_rid_header,
)


class TestAIDAddressing:
    def test_aid_creation(self):
        aid = AID(0xDEADBEEF)
        assert aid.value == 0xDEADBEEF

    def test_aid_from_hex(self):
        aid = AID.from_hex("8d969eef6ecad3c29a3a629280e686cf")
        assert aid.value == 0x8D969EEF6ECAD3C29A3A629280E686CF

    def test_aid_from_hash(self):
        aid = AID.from_hash(b"Zhangsan:1234:device01")
        assert len(aid.to_bytes()) == 16
        # deterministic
        aid2 = AID.from_hash(b"Zhangsan:1234:device01")
        assert aid == aid2

    def test_aid_to_bytes_roundtrip(self):
        original = AID(0xABCD1234567890ABCDEF1234567890AB)
        restored = AID(int.from_bytes(original.to_bytes(), "big"))
        assert original == restored

    def test_aid_out_of_range(self):
        with pytest.raises(ValueError):
            AID(2**128)


class TestRIDAddressing:
    def test_rid_creation(self):
        rid = RID(10001, 36191)
        assert rid.x == 10001
        assert rid.y == 36191

    def test_rid_int_roundtrip(self):
        original = RID(10001, 36191)
        restored = RID.from_int(original.as_int)
        assert original == restored

    def test_rid_out_of_range(self):
        with pytest.raises(ValueError):
            RID(2**32, 0)

    def test_rid_prefix_product(self):
        a = RID(10028, 36181)  # space origin
        b = RID(10030, 36190)  # nearby neighbour
        product = a.prefix_product(b)
        assert product > 0  # should have matching prefix bits


class TestRIDSpace:
    def test_contains(self):
        space = RIDSpace(x=10028, y=36181, x_mask_bits=20, y_mask_bits=20)
        inside = RID(10030, 36190)  # shares 20-bit prefix on x
        assert space.contains(inside)

    def test_not_contains(self):
        space = RIDSpace(x=10028, y=36181, x_mask_bits=20, y_mask_bits=20)
        outside = RID(20000, 50000)  # completely different
        assert not space.contains(outside)


class TestAIDPacket:
    def test_serialize_deserialize(self):
        pkt = AIDPacket(
            source_aid=AID.from_hex("8d969eef6ecad3c29a3a629280e686cf"),
            destination_aid=AID.from_hex("cad3c29a3a629280e686cf8d969eef6e"),
            payload=b"Hello Identifier Network!",
            ttl=64,
        )
        data = pkt.serialize()
        assert len(data) == AID_HEADER_BYTES + len(pkt.payload)

        pkt2 = AIDPacket.deserialize(data)
        assert pkt2.source_aid == pkt.source_aid
        assert pkt2.destination_aid == pkt.destination_aid
        assert pkt2.payload == pkt.payload
        assert pkt2.ttl == pkt.ttl

    def test_header_size(self):
        pkt = AIDPacket(payload=b"")
        assert len(pkt.serialize()) == AID_HEADER_BYTES  # 40 bytes

    def test_decrement_ttl(self):
        pkt = AIDPacket(ttl=2)
        assert pkt.decrement_ttl()  # True, now ttl=1
        assert pkt.ttl == 1
        assert not pkt.decrement_ttl()  # False, expired
        assert pkt.ttl == 1

    def test_default_ttl(self):
        pkt = AIDPacket()
        assert pkt.ttl == DEFAULT_TTL


class TestRIDPacket:
    def test_serialize_deserialize(self):
        pkt = RIDPacket(
            source_rid=RID(10001, 36191),
            destination_rid=RID(12360, 34280),
            payload=b"Encapsulated AID data",
            network_space_id=100,
            ttl=64,
        )
        data = pkt.serialize()
        assert len(data) == RID_HEADER_BYTES + len(pkt.payload)

        pkt2 = RIDPacket.deserialize(data)
        assert pkt2.source_rid == pkt.source_rid
        assert pkt2.destination_rid == pkt.destination_rid
        assert pkt2.payload == pkt.payload
        assert pkt2.network_space_id == 100

    def test_header_size(self):
        pkt = RIDPacket(payload=b"")
        assert len(pkt.serialize()) == RID_HEADER_BYTES  # 24 bytes

    def test_decrement_ttl(self):
        pkt = RIDPacket(ttl=1)
        assert not pkt.decrement_ttl()  # expired immediately


class TestEthernetFrame:
    def test_aid_encapsulation(self):
        aid_pkt = AIDPacket(
            source_aid=AID(0xABCD),
            destination_aid=AID(0x1234),
            payload=b"test",
        )
        frame = EthernetFrame.from_aid_packet(
            aid_pkt,
            dst_mac=mac_from_str("00:04:ab:1f:40:a6"),
            src_mac=mac_from_str("00:11:22:33:44:01"),
        )
        assert frame.is_aid
        assert not frame.is_rid

        # Round-trip
        data = frame.serialize()
        frame2 = EthernetFrame.deserialize(data)
        assert frame2.is_aid
        inner = frame2.inner_aid()
        assert inner.source_aid == aid_pkt.source_aid
        assert inner.payload == b"test"

    def test_rid_encapsulation(self):
        rid_pkt = RIDPacket(
            source_rid=RID(10001, 36191),
            destination_rid=RID(12360, 34280),
            payload=b"core data",
        )
        frame = EthernetFrame.from_rid_packet(
            rid_pkt,
            dst_mac=mac_from_str("00:0c:ab:1e:76:8a"),
            src_mac=mac_from_str("00:0c:ab:1e:76:8b"),
        )
        assert frame.is_rid

        data = frame.serialize()
        frame2 = EthernetFrame.deserialize(data)
        assert frame2.is_rid
        inner = frame2.inner_rid()
        assert inner.source_rid == rid_pkt.source_rid


class TestSerializer:
    def test_pack_unpack_aid_header(self):
        src = bytes.fromhex("8d969eef6ecad3c29a3a629280e686cf")
        dst = bytes.fromhex("cad3c29a3a629280e686cf8d969eef6e")
        header = pack_aid_header(qos_class=5, payload_length=100, data_type=0, ttl=64,
                                 src_aid_bytes=src, dst_aid_bytes=dst)
        assert len(header) == 40
        fields = unpack_aid_header(header)
        assert fields["qos_class"] == 5
        assert fields["payload_length"] == 100
        assert fields["ttl"] == 64

    def test_pack_unpack_rid_header(self):
        header = pack_rid_header(qos_class=3, space_id=100, payload_length=50,
                                  data_type=0, ttl=60, dst_rid_int=0x100020003, src_rid_int=0x40005000)
        assert len(header) == 24
        fields = unpack_rid_header(header)
        assert fields["qos_class"] == 3
        assert fields["network_space_id"] == 100
        assert fields["ttl"] == 60
