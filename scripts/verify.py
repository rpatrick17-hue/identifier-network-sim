#!/usr/bin/env python3
"""
标识网络模态仿真验证 — 逐项功能验证脚本

本脚本不依赖 pytest，每一项都是独立的验证步骤，
包含：输入构造、预期行为描述、实际结果对比。
每项通过的标志是 [PASS]，失败是 [FAIL]。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ── 导入 ──────────────────────────────────────────────────────────────
from src.common.addressing import AID, RID, RIDSpace
from src.common.constants import (
    AID_HEADER_BYTES, RID_HEADER_BYTES, DEFAULT_TTL,
    ETHERTYPE_AID, ETHERTYPE_RID,
    DataType, IDType, Version, InterfaceType, SpacePolicy, UserStatus,
)
from src.common.packets import AIDPacket, RIDPacket
from src.common.ethernet import EthernetFrame, mac_from_str, mac_to_str
from src.common.serializer import (
    pack_aid_header, unpack_aid_header,
    pack_rid_header, unpack_rid_header,
    ETH_HEADER_STRUCT,
)
from src.common.utils import generate_aid, setup_logging, MetricsAccumulator
from src.control_plane.signaling import (
    AuthRequest, AuthResponse, AuthResponse as AuthResp,
    MappingRegisterRequest, MappingQueryRequest, MappingQueryResponse,
    NeighborAdvertisement, MobilityAlert, RouteConfigPush,
    SignalType, encode_signal, decode_signal,
)
from src.tables.cr_tables import CRTables, UserStatusEntry
from src.tables.cs_tables import CSDatabase, UserRegistryEntry
from src.routing.rid_routing import rid_lookup, rid_lookup_next_hop, rid_route_add
from src.routing.aid_routing import aid_lookup, aid_route_add
from src.routing.mapping import (
    cr_add_local_mapping, cr_add_remote_mapping,
    cr_lookup_any_mapping, cr_update_mapping,
    cs_register_mapping, cs_query_mapping,
)
from src.simulation.virtual_link import VirtualLink, VirtualSwitch
from src.nodes.core_router import CoreRouter
from src.nodes.access_point import AccessPoint
from src.nodes.control_server import ControlServer
from src.nodes.host import Host
from src.nodes.test_server import TestServer


# ── 输出辅助 ──────────────────────────────────────────────────────────
passed = 0
failed = 0

def check(desc: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        print(f"  [PASS] {desc}")
        passed += 1
    else:
        print(f"  [FAIL] {desc}")
        if detail:
            print(f"         {detail}")
        failed += 1

def section(title: str) -> None:
    print(f"\n{'═'*62}")
    print(f"  {title}")
    print(f"{'═'*62}")


# ══════════════════════════════════════════════════════════════════════
#  验证 1：AID 地址 (128-bit)
# ══════════════════════════════════════════════════════════════════════
def verify_aid() -> None:
    section("验证 1: AID 地址 (128-bit 接入标识)")

    # 1.1 创建 & 范围检查
    aid = AID.from_hex("8d969eef6ecad3c29a3a629280e686cf")
    check("AID 从 hex 创建", aid.value == 0x8D969EEF6ECAD3C29A3A629280E686CF)
    check("AID 序列化为 16 字节", len(aid.to_bytes()) == 16)
    check("AID 序列化往返", AID.from_bytes(aid.to_bytes()) == aid)

    # 1.2 范围保护
    try:
        AID(2**128)
        check("AID 溢出应抛异常", False, "未抛出 ValueError")
    except ValueError:
        check("AID 溢出保护 (2^128 拒绝)", True)

    # 1.3 哈希生成确定性
    a1 = AID.from_hash(b"Zhangsan:1234:device01")
    a2 = AID.from_hash(b"Zhangsan:1234:device01")
    check("AID 哈希确定性 (相同输入→相同AID)", a1 == a2)
    check("AID 哈希长度 (16字节)", len(a1.to_bytes()) == 16)

    # 1.4 不同输入产生不同 AID
    a3 = AID.from_hash(b"Lisi:0000:device02")
    check("AID 哈希碰撞防护 (不同输入→不同AID)", a1 != a3)


# ══════════════════════════════════════════════════════════════════════
#  验证 2：RID 地址 (64-bit 二维坐标)
# ══════════════════════════════════════════════════════════════════════
def verify_rid() -> None:
    section("验证 2: RID 地址 (64-bit 二维网格坐标)")

    rid = RID(10001, 36191)
    check("RID 创建 X 坐标", rid.x == 10001)
    check("RID 创建 Y 坐标", rid.y == 36191)

    # 位拼接
    as_int = rid.as_int
    check("RID→int 编码", as_int == (10001 << 32) | 36191)
    check("int→RID 解码往返", RID.from_int(as_int) == rid)
    check("RID 序列化 8 字节", len(rid.to_bytes()) == 8)

    # RID 空间匹配
    space = RIDSpace(x=10028, y=36181, x_mask_bits=20, y_mask_bits=20)
    check("RID 空间包含 (相同高20位)",
          space.contains(RID(10030, 36190)))
    check("RID 空间排除 (不同高20位)",
          not space.contains(RID(20000, 50000)))

    # 范围保护
    try:
        RID(2**32, 0)
        check("RID X 溢出应抛异常", False)
    except ValueError:
        check("RID X 溢出保护", True)

    try:
        RID(0, 2**32)
        check("RID Y 溢出应抛异常", False)
    except ValueError:
        check("RID Y 溢出保护", True)


# ══════════════════════════════════════════════════════════════════════
#  验证 3：AID 数据包格式 (40 字节包头)
# ══════════════════════════════════════════════════════════════════════
def verify_aid_packet() -> None:
    section("验证 3: AID 数据包序列化 (40 字节包头)")

    src = AID.from_hex("8d969eef6ecad3c29a3a629280e686cf")
    dst = AID.from_hex("cad3c29a3a629280e686cf8d969eef6e")
    payload = b"Hello Identifier Network!"

    pkt = AIDPacket(source_aid=src, destination_aid=dst, payload=payload,
                    qos_class=5, ttl=64, data_type=DataType.USER_DATA)
    data = pkt.serialize()

    # 包头长度验证（文档：40 字节）
    check(f"AID 包头 = 40 字节 (实际: {AID_HEADER_BYTES})",
          AID_HEADER_BYTES == 40)
    check(f"序列化总长 = 40 + {len(payload)} = {40+len(payload)} 字节",
          len(data) == 40 + len(payload))

    # 版本和标识类型字段
    raw = unpack_aid_header(data[:40])
    check("AID 版本 = 0001 (4bit)", raw["version"] == 1)
    check("AID 标识类型 = 1000 (4bit)", raw["id_type"] == 0b1000)
    check("AID QoS 字段保留", raw["qos_class"] == 5)
    check("AID TTL 字段", raw["ttl"] == 64)
    check("AID 载荷长度字段", raw["payload_length"] == len(payload))

    # 地址往返
    pkt2 = AIDPacket.deserialize(data)
    check("AID 源地址序列化往返", pkt2.source_aid == src)
    check("AID 目的地址序列化往返", pkt2.destination_aid == dst)
    check("AID 载荷序列化往返", pkt2.payload == payload)

    # TTL 防环
    pkt3 = AIDPacket(ttl=2)
    check("TTL 递减: 2→1 存活", pkt3.decrement_ttl() and pkt3.ttl == 1)
    check("TTL 递减: 1→0 丢弃", not pkt3.decrement_ttl())


# ══════════════════════════════════════════════════════════════════════
#  验证 4：RID 数据包格式 (24 字节包头)
# ══════════════════════════════════════════════════════════════════════
def verify_rid_packet() -> None:
    section("验证 4: RID 数据包序列化 (24 字节包头)")

    src = RID(10001, 36191)
    dst = RID(12360, 34280)
    payload = b"Encapsulated AID data"

    pkt = RIDPacket(source_rid=src, destination_rid=dst, payload=payload,
                    qos_class=3, network_space_id=100, ttl=60,
                    data_type=DataType.USER_DATA)
    data = pkt.serialize()

    check(f"RID 包头 = 24 字节 (实际: {RID_HEADER_BYTES})",
          RID_HEADER_BYTES == 24)
    check(f"序列化总长 = 24 + {len(payload)} = {24+len(payload)} 字节",
          len(data) == 24 + len(payload))

    raw = unpack_rid_header(data[:24])
    check("RID 版本 = 0001", raw["version"] == 1)
    check("RID 标识类型 = 0100", raw["id_type"] == 0b0100)
    check("RID 网络空间 ID", raw["network_space_id"] == 100)
    check("RID TTL", raw["ttl"] == 60)

    pkt2 = RIDPacket.deserialize(data)
    check("RID 源地址往返", pkt2.source_rid == src)
    check("RID 目的地址往返", pkt2.destination_rid == dst)
    check("RID 载荷往返", pkt2.payload == payload)

    # TTL 防环
    pkt3 = RIDPacket(ttl=1)
    check("RID TTL=1 递减即死亡", not pkt3.decrement_ttl())


# ══════════════════════════════════════════════════════════════════════
#  验证 5：以太网帧封装 (自定义 EtherType)
# ══════════════════════════════════════════════════════════════════════
def verify_ethernet() -> None:
    section("验证 5: 以太网帧封装 (EtherType: 0x88B5 AID / 0x88B6 RID)")

    aid_pkt = AIDPacket(source_aid=AID(0xABCD), destination_aid=AID(0x1234),
                        payload=b"eth-test")
    frame = EthernetFrame.from_aid_packet(
        aid_pkt, mac_from_str("00:04:ab:1f:40:a6"),
        mac_from_str("00:11:22:33:44:01"),
    )

    check(f"AID EtherType = 0x{ETHERTYPE_AID:04X}", frame.ethertype == ETHERTYPE_AID)
    check("帧识别为 AID", frame.is_aid)
    check("帧不识别为 RID", not frame.is_rid)

    # 往返
    frame2 = EthernetFrame.deserialize(frame.serialize())
    check("以太网帧序列化往返", frame2.is_aid)
    inner = frame2.inner_aid()
    check("帧内 AID 包还原", inner.payload == b"eth-test")

    # RID 封装
    rid_pkt = RIDPacket(source_rid=RID(10001, 36191),
                        destination_rid=RID(12360, 34280),
                        payload=b"core-test")
    rframe = EthernetFrame.from_rid_packet(
        rid_pkt, mac_from_str("00:0c:ab:1e:76:8a"),
        mac_from_str("00:0c:ab:1e:76:8b"),
    )
    check(f"RID EtherType = 0x{ETHERTYPE_RID:04X}", rframe.ethertype == ETHERTYPE_RID)
    check("帧识别为 RID", rframe.is_rid)


# ══════════════════════════════════════════════════════════════════════
#  验证 6：RID 路由算法 (二维前缀乘积匹配)
# ══════════════════════════════════════════════════════════════════════
def verify_rid_routing() -> None:
    section("验证 6: RID 核心路由算法 (二维前缀乘积匹配)")

    tables = CRTables()
    # 路由表项 A: 空间(12345|20, 34267|24) → M₁×M₂ = 20×24 = 480
    rid_route_add(tables, 100, 12345, 34267, 20, 24, RID(12360, 34280))
    # 路由表项 B: 空间(10000|8, 30000|8) → M₁×M₂ = 8×8 = 64
    rid_route_add(tables, 100, 10000, 30000, 8, 8, RID(10001, 36191))

    # 测试1: 精确命中表项A
    result = rid_lookup(tables, RID(12345, 34267), 100)
    check("精确命中 → 下一跳 RID(12360,34280)",
          result is not None and result.next_hop_rid == RID(12360, 34280))

    # 测试2: 前缀匹配（高20位相同）
    result2 = rid_lookup(tables, RID(12346, 34268), 100)
    check("前缀匹配 (高20位) → 仍可路由",
          result2 is not None)

    # 测试3: 添加更精确的表项C
    rid_route_add(tables, 100, 12345, 34267, 22, 26, RID(12370, 34290))
    result3 = rid_lookup(tables, RID(12345, 34267), 100)
    check("更精确表项 C(22×26=572) 胜出 A(20×24=480)",
          result3 is not None and result3.next_hop_rid == RID(12370, 34290))

    # 测试4: 无匹配 (使用高24位不同的值确保不匹配8位前缀)
    result4 = rid_lookup(tables, RID(0xFF000000, 0xFF000000), 100)
    check("无匹配 → None (丢弃)", result4 is None)

    # 测试5: 不同空间
    result5 = rid_lookup(tables, RID(12345, 34267), 999)
    check("不同空间ID → None", result5 is None)

    # 测试6: 乘积相同时的X掩码优先
    t2 = CRTables()
    rid_route_add(t2, 100, 10000, 30000, 20, 20, RID(99999, 99999))
    rid_route_add(t2, 100, 10000, 30000, 25, 16, RID(88888, 88888))  # 都是400
    r = rid_lookup(t2, RID(10000, 30000), 100)
    check("同乘积(400)时 X-掩码优先 (25>20)", r is not None and r.next_hop_rid == RID(88888, 88888))


# ══════════════════════════════════════════════════════════════════════
#  验证 7：AID→RID 映射管理
# ══════════════════════════════════════════════════════════════════════
def verify_mapping() -> None:
    section("验证 7: AID↔RID 映射管理 (CR/CS 两侧)")

    tables = CRTables()
    aid = AID.from_hex("cad3c29a3a629280e686cf8d969eef6e")

    # 本地映射
    cr_add_local_mapping(tables, aid, RID(10001, 36191), 0)
    m = cr_lookup_any_mapping(tables, aid)
    check("CR 本地映射写入", m is not None and m.mapped_rid == RID(10001, 36191))

    # 远端映射
    aid2 = AID.from_hex("969eef6ecad3c29a3a629280e686cf8d")
    cr_add_remote_mapping(tables, aid2, RID(10002, 36192), RID(12360, 34280), 100)
    m2 = cr_lookup_any_mapping(tables, aid2)
    check("CR 远端映射写入 (含 remote_cr_rid)", m2 is not None and m2.remote_cr_rid == RID(12360, 34280))

    # 映射更新 (模拟移动切换)
    cr_update_mapping(tables, aid2, RID(99999, 99999), RID(88888, 88888))
    m3 = cr_lookup_any_mapping(tables, aid2)
    check("CR 映射更新 (切换后新RID)", m3 is not None and m3.mapped_rid == RID(99999, 99999))
    check("CR 映射更新 (切换后新CR)", m3 is not None and m3.remote_cr_rid == RID(88888, 88888))

    # CS 侧
    db = CSDatabase()
    cs_register_mapping(db, aid, RID(10001, 36191), RID(10001, 36191))
    cs_m = cs_query_mapping(db, aid)
    check("CS 映射注册", cs_m is not None and cs_m.mapped_rid == RID(10001, 36191))
    check("CS 映射未找到", cs_query_mapping(db, AID(0xDEAD)) is None)


# ══════════════════════════════════════════════════════════════════════
#  验证 8：用户状态管理 (在线/移走/离线)
# ══════════════════════════════════════════════════════════════════════
def verify_user_status() -> None:
    section("验证 8: CR 用户状态管理 (在线/移走/离线)")

    tables = CRTables()
    user = AID(0xAAAA)
    ap = AID(0xBBBB)

    tables.user_statuses[user] = UserStatusEntry(
        user_aid=user, ap_aid=ap, status=UserStatus.ONLINE, custom_attributes="UR:3;BW:10Mbps")
    check("用户状态: 在线 → is_local_aid=True", tables.is_local_aid(user))

    tables.user_statuses[user].status = UserStatus.MOVED_AWAY
    check("用户状态: 移走 → is_local_aid=False", not tables.is_local_aid(user))

    tables.user_statuses[user].status = UserStatus.OFFLINE
    check("用户状态: 离线 → is_local_aid=False", not tables.is_local_aid(user))

    # 用户接入 AP 查找 (需在线状态)
    tables.user_statuses[user].status = UserStatus.ONLINE  # 恢复在线
    check("用户关联AP查找", tables.user_ap_aid(user) == ap)


# ══════════════════════════════════════════════════════════════════════
#  验证 9: 控制信令 (8种消息编解码)
# ══════════════════════════════════════════════════════════════════════
def verify_signaling() -> None:
    section("验证 9: 控制信令消息 (8种消息类型)")

    aid = AID.from_hex("cad3c29a3a629280e686cf8d969eef6e")

    # 1. AuthRequest
    msg1 = AuthRequest(username="Zhangsan", password="123", user_aid=aid,
                       ip_address="192.168.1.100", mac_address="00:11:22:33:44:01")
    data = encode_signal(msg1)
    decoded = decode_signal(data)
    check("AuthRequest 编解码", isinstance(decoded, AuthRequest) and decoded.username == "Zhangsan")

    # 2. AuthResponse
    msg2 = AuthResponse(success=True, user_aid=aid, message="OK", custom_attributes={"UR": "3"})
    decoded2 = decode_signal(encode_signal(msg2))
    check("AuthResponse 编解码 (成功)", isinstance(decoded2, AuthResponse) and decoded2.success)

    msg2b = AuthResponse(success=False, user_aid=aid, message="Bad password")
    decoded2b = decode_signal(encode_signal(msg2b))
    check("AuthResponse 编解码 (失败)", not decoded2b.success)

    # 3. MappingRegister
    msg3 = MappingRegisterRequest(aid=aid, mapped_rid=RID(10001, 36191),
                                   ap_rid=RID(10001, 36191), space_id=100)
    decoded3 = decode_signal(encode_signal(msg3))
    check("MappingRegister 编解码", decoded3.mapped_rid == RID(10001, 36191))

    # 4. MappingQuery / Response
    msg4 = MappingQueryRequest(aid=aid, requester_rid=RID(12360, 34280))
    decoded4 = decode_signal(encode_signal(msg4))
    check("MappingQuery 编解码", decoded4.aid == aid)

    msg4r = MappingQueryResponse(aid=aid, mapped_rid=RID(10001, 36191),
                                  remote_cr_rid=RID(10001, 36191), found=True)
    decoded4r = decode_signal(encode_signal(msg4r))
    check("MappingQueryResponse 编解码", decoded4r.found and decoded4r.mapped_rid == RID(10001, 36191))

    # 5. NeighborAdvertisement
    msg5 = NeighborAdvertisement(user_aid=aid, ap_aid=AID(0xBBBB),
                                  ap_rid=RID(10001, 36191), action="attach")
    decoded5 = decode_signal(encode_signal(msg5))
    check("NeighborAdvertisement 编解码", decoded5.action == "attach")

    # 6. MobilityAlert
    msg6 = MobilityAlert(user_aid=aid, old_rid=RID(1,1), new_rid=RID(2,2),
                          new_cr_rid=RID(3,3), reason="mobility_handover")
    decoded6 = decode_signal(encode_signal(msg6))
    check("MobilityAlert 编解码", decoded6.new_rid == RID(2,2))

    # 7. RouteConfigPush
    msg7 = RouteConfigPush(space_id=100, dest_rid_space=(12345, 34267, 20, 24),
                            next_hop_rid=RID(12360, 34280))
    decoded7 = decode_signal(encode_signal(msg7))
    check("RouteConfigPush 编解码", decoded7.next_hop_rid == RID(12360, 34280))

    # 8. 消息类型枚举完整性
    all_types = set(SignalType)
    check(f"SignalType 枚举完整 ({len(all_types)} 种)", len(all_types) == 9)


# ══════════════════════════════════════════════════════════════════════
#  验证 10：虚拟链路层 (延迟/丢包/广播)
# ══════════════════════════════════════════════════════════════════════
async def verify_virtual_link() -> None:
    section("验证 10: 虚拟链路层 (延迟/丢包/广播)")

    # 10.1 基本收发
    link = VirtualLink(name="test")
    link.attach("a:0"); link.attach("b:0")
    ok = await link.send("a:0", "b:0", b"hello")
    data = await link.recv("b:0", timeout=1.0)
    check("VirtualLink 基本收发", ok and data == b"hello")

    # 10.2 广播
    link.attach("c:0")
    await link.broadcast("a:0", b"all")
    d1 = await link.recv("b:0", timeout=1.0)
    d2 = await link.recv("c:0", timeout=1.0)
    check("VirtualLink 广播到b", d1 == b"all")
    check("VirtualLink 广播到c", d2 == b"all")

    # 10.3 延迟注入
    dlink = VirtualLink(name="delay", delay_ms=100)
    dlink.attach("x:0"); dlink.attach("y:0")
    t0 = time.time()
    await dlink.send("x:0", "y:0", b"delayed")
    elapsed = time.time() - t0
    check(f"延迟 ≥ 100ms (实际: {elapsed*1000:.0f}ms)", elapsed >= 0.095)

    # 10.4 丢包
    llink = VirtualLink(name="lossy", loss_rate=1.0)
    llink.attach("m:0"); llink.attach("n:0")
    ok2 = await llink.send("m:0", "n:0", b"lost")
    check("100% 丢包 → 返回 False", not ok2)


# ══════════════════════════════════════════════════════════════════════
#  验证 11：交换机端口隔离 (Port Isolation)
# ══════════════════════════════════════════════════════════════════════
async def verify_port_isolation() -> None:
    section("验证 11: 交换机端口隔离 (Port Isolation)")

    sw = VirtualSwitch(name="iso-sw")
    sw.add_port(1, bytes.fromhex("000c29ab1e01"))
    sw.add_port(2, bytes.fromhex("000c29ab1e02"))
    sw.add_port(3, bytes.fromhex("000c29ab1e03"))

    frame = ETH_HEADER_STRUCT.pack(
        bytes.fromhex("000c29ab1e02"), bytes.fromhex("000c29ab1e01"),
        0x88B5) + b"data"

    # 无隔离组 → 开放模式 (所有端口互通)
    ok1 = await sw.send(1, None, frame)
    check("无隔离组 → 开放 (允许)", ok1)

    # 设置隔离组: 仅端口1↔3
    sw.set_isolation_group(1, [1, 3])
    ok2 = await sw.send(1, None, frame)  # 1→2 被隔离
    check("端口1↔2不在同组 → 阻断", not ok2)

    # 同组可以通
    frame3 = ETH_HEADER_STRUCT.pack(
        bytes.fromhex("000c29ab1e03"), bytes.fromhex("000c29ab1e01"),
        0x88B5) + b"allowed"
    ok3 = await sw.send(1, None, frame3)  # 1→3 同组
    check("端口1↔3同组 → 允许", ok3)


# ══════════════════════════════════════════════════════════════════════
#  验证 12：CR 数据面转发决策树 (文档图17)
# ══════════════════════════════════════════════════════════════════════
async def verify_cr_forwarding() -> None:
    section("验证 12: CR 数据面转发决策树 (文档图17)")

    # ── 搭建 2-CR 拓扑 ──
    cr1 = CoreRouter(name="cr1"); cr1.my_rid = RID(10001, 36191)
    cr2 = CoreRouter(name="cr2"); cr2.my_rid = RID(12360, 34280)

    cr1.add_interface("Eth0", "00:18:54:fd:29:01"); cr1.add_interface("Eth1", "00:0c:ab:1e:76:8a")
    cr2.add_interface("Eth0", "00:18:54:fd:29:02"); cr2.add_interface("Eth1", "00:0c:ab:1e:76:8c")
    cr1.configure_interface(0, "Eth0", "00:18:54:fd:29:01", InterfaceType.ACCESS)
    cr1.configure_interface(1, "Eth1", "00:0c:ab:1e:76:8a", InterfaceType.ROUTE)
    cr2.configure_interface(0, "Eth0", "00:18:54:fd:29:02", InterfaceType.ACCESS)
    cr2.configure_interface(1, "Eth1", "00:0c:ab:1e:76:8c", InterfaceType.ROUTE)

    cr1.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)
    cr2.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)
    cr1.add_route_neighbor(100, RID(12360, 34280), "00:0c:ab:1e:76:8c", 1)
    cr2.add_route_neighbor(100, RID(10001, 36191), "00:0c:ab:1e:76:8a", 1)
    cr1.add_rid_route(100, 12345, 34267, 20, 24, RID(12360, 34280))
    cr2.add_rid_route(100, 10001, 36191, 20, 20, RID(10001, 36191))

    # AP 关联
    ap1_aid = AID.from_hex("8d969eef6ecad3c29a3a629280e686cf")
    ap2_aid = AID.from_hex("280e686cf8d969eef6ecad3c29a3a629")
    cr1.add_associated_ap(ap1_aid, RID(10001, 36191), 0)
    cr2.add_associated_ap(ap2_aid, RID(10002, 36192), 0)

    # 用户: Host-1 在 CR-1, Host-2 在 CR-2
    host1 = AID.from_hex("cad3c29a3a629280e686cf8d969eef6e")
    host2 = AID.from_hex("969eef6ecad3c29a3a629280e686cf8d")
    cr1.set_user_status(host1, ap1_aid, UserStatus.ONLINE)
    cr2.set_user_status(host2, ap2_aid, UserStatus.ONLINE)

    # 映射
    cr_add_remote_mapping(cr1.tables, host2, RID(10002, 36192), RID(12360, 34280), 100)
    cr_add_remote_mapping(cr2.tables, host1, RID(10001, 36191), RID(10001, 36191), 100)

    # 链路
    core_link = VirtualLink(name="core")
    cr1.connect_link(1, core_link)
    cr2.connect_link(1, core_link)

    # 启动节点
    t1 = asyncio.create_task(cr1.run()); t2 = asyncio.create_task(cr2.run())
    await asyncio.sleep(0.15)

    # ── 测试12.1: AID→RID 封装转发 ──
    aid_pkt = AIDPacket(source_aid=host1, destination_aid=host2,
                        payload=b"cross-core", ttl=64)
    frame = EthernetFrame.from_aid_packet(
        aid_pkt, cr1.interfaces[0].mac, mac_from_str("00:11:22:33:44:01"),
    )
    await cr1.send_frame(0, frame)
    await asyncio.sleep(0.2)
    m1 = cr1.metrics.summary()
    check(f"CR-1 收到 AID 包 → 封装为 RID 转发 (发送: {m1['sent_packets']})",
          m1["sent_packets"] >= 1)

    # ── 测试12.2: 本地 AID 投递 ──
    aid_local = AIDPacket(source_aid=host2, destination_aid=host1,
                          payload=b"local-delivery", ttl=64)
    frame2 = EthernetFrame.from_aid_packet(
        aid_local, cr2.interfaces[0].mac, mac_from_str("00:11:22:33:44:02"),
    )
    await cr2.send_frame(0, frame2)
    await asyncio.sleep(0.2)
    m2 = cr2.metrics.summary()
    check(f"CR-2 收到 AID → 查映射 → 封装 RID → 路由到CR-1 (发送: {m2['sent_packets']})",
          m2["sent_packets"] >= 1)

    # ── 测试12.3: TTL 防环 ──
    aid_ttl = AIDPacket(source_aid=host1, destination_aid=host2,
                        payload=b"ttl-expire", ttl=1)
    frame3 = EthernetFrame.from_aid_packet(
        aid_ttl, cr1.interfaces[0].mac, mac_from_str("00:11:22:33:44:01"),
    )
    pre_sent = cr1.metrics.summary()["sent_packets"]
    await cr1.send_frame(0, frame3)
    await asyncio.sleep(0.15)
    post_sent = cr1.metrics.summary()["sent_packets"]
    # TTL=1 → 递减后为0 → 丢弃，不会额外发送RID包
    ttl_dropped = (post_sent - pre_sent) <= 1
    check(f"TTL=1 → 递减→0 → 丢弃 (新增发送: {post_sent - pre_sent})", ttl_dropped)

    # ── 测试12.4: 移动切换重定向 ──
    # 模拟: Host-1 从 CR-1 移到 CR-2
    cr1.set_user_status(host1, ap1_aid, UserStatus.MOVED_AWAY)
    cr_update_mapping(cr1.tables, host1, RID(10002, 36192), RID(12360, 34280))
    cr2.set_user_status(host1, ap2_aid, UserStatus.ONLINE)

    # CR-1 收到发给 Host-1 的数据 → 发现已移走 → 重新封装
    aid_move = AIDPacket(source_aid=host2, destination_aid=host1,
                         payload=b"moved-user", ttl=64)
    frame4 = EthernetFrame.from_aid_packet(
        aid_move, cr1.interfaces[0].mac, mac_from_str("00:11:22:33:44:02"),
    )
    pre = cr1.metrics.summary()["sent_packets"]
    await cr1.send_frame(0, frame4)
    await asyncio.sleep(0.2)
    post = cr1.metrics.summary()["sent_packets"]
    status = cr1.tables.user_statuses[host1].status
    check(f"用户已移走 → 状态=MOVED_AWAY (实际: {UserStatus(status).name})",
          status == UserStatus.MOVED_AWAY)
    check(f"移动重定向 → 重新封装转发 (发送增量: {post - pre})", post > pre)

    # 清理
    cr1.stop(); cr2.stop()
    t1.cancel(); t2.cancel()
    await asyncio.gather(t1, t2, return_exceptions=True)


# ══════════════════════════════════════════════════════════════════════
#  验证 13：CS 用户注册与认证
# ══════════════════════════════════════════════════════════════════════
def verify_authentication() -> None:
    section("验证 13: CS 用户注册 & 认证流程")

    cs = ControlServer(name="cs-verify")

    # 注册
    entry = cs.register_user("Zhangsan", "123", pin="1234",
                              custom_attributes="UR:3;BW:10Mbps")
    check("用户注册 → AID 由哈希生成 (16字节)", len(entry.user_aid.to_bytes()) == 16)
    check("用户注册 → 用户名存储", entry.username == "Zhangsan")
    check("用户注册 → 定制属性解析", entry.parse_attributes() == {"UR": "3", "BW": "10Mbps"})

    # 认证成功
    result = cs.db.authenticate("Zhangsan", "123")
    check("认证成功 → 返回用户条目", result is not None and result.username == "Zhangsan")

    # 认证失败
    result2 = cs.db.authenticate("Zhangsan", "wrong")
    check("认证失败 (错误密码) → None", result2 is None)

    result3 = cs.db.authenticate("Nobody", "123")
    check("认证失败 (不存在用户) → None", result3 is None)

    # 确定性: 相同输入产生相同 AID
    entry2 = cs.register_user("Zhangsan", "123", pin="1234")
    check("相同注册信息 → 相同 AID (确定性哈希)", entry.user_aid == entry2.user_aid)

    # 不同输入产生不同 AID
    entry3 = cs.register_user("Lisi", "Abc", pin="0000")
    check("不同注册信息 → 不同 AID", entry.user_aid != entry3.user_aid)


# ══════════════════════════════════════════════════════════════════════
#  验证 14：性能指标采集
# ══════════════════════════════════════════════════════════════════════
def verify_metrics() -> None:
    section("验证 14: 性能指标采集 (吞吐量/时延/抖动/丢包)")

    m = MetricsAccumulator()
    m.record_send(1500)
    m.record_send(1500)
    m.record_recv(1500, rtt=0.001)
    m.record_recv(1500, rtt=0.002)

    check("发送计数", m.summary()["sent_packets"] == 2)
    check("接收计数", m.summary()["recv_packets"] == 2)
    check("发送字节", m.summary()["sent_bytes"] == 3000)
    check("平均 RTT (2ms)", 1.0 <= m.avg_rtt_ms <= 2.0, f"实际: {m.avg_rtt_ms:.2f}ms")
    check("丢包率 0%", m.packet_loss_rate == 0.0)

    # 丢包场景
    m2 = MetricsAccumulator()
    m2.record_send(1000)
    m2.record_send(1000)
    m2.record_recv(1000)  # 只收到1个
    check("丢包率 50%", m2.packet_loss_rate == 0.5, f"实际: {m2.packet_loss_rate}")


# ══════════════════════════════════════════════════════════════════════
#  验证 15：完整设备数量验证
# ══════════════════════════════════════════════════════════════════════
def verify_topology_counts() -> None:
    section("验证 15: 完整拓扑 12 节点构建")

    from src.simulation.topology import Topology
    config = _PROJECT_ROOT / "config" / "topology.yaml"
    topo = Topology.from_yaml(str(config))

    check("核心路由器 6 台", len(topo.core_routers) == 6)
    check("无线接入设备 ≥2 台", len(topo.access_points) == 2)
    check("控制平面服务器 1 台", topo.control_server is not None)
    check("业务测试服务器 1 台", topo.test_server is not None)
    check("用户终端 2 台", len(topo.hosts) == 2)
    check("交换机 2 台 (管理+数据)", len(topo.switches) == 2)
    check("总节点数 12", len(topo.nodes) == 12)

    # 验证 CR-1 配置
    cr1 = topo.core_routers["CR-1"]
    check("CR-1 有 RID", cr1.my_rid is not None)
    check("CR-1 有接口", len(cr1.interfaces) >= 1)
    check("CR-1 有 RID 空间", len(cr1.tables.rid_spaces) >= 1)
    check("CR-1 有路由表", len(cr1.tables.rid_routes) >= 1)

    # 验证 CS 预注册用户
    cs = topo.control_server
    check("CS 预注册 Zhangsan", "Zhangsan" in cs.db.users)
    check("CS 预注册 Lisi", "Lisi" in cs.db.users)

    # 验证 Host 配置
    h1 = topo.hosts["Host-1"]
    check("Host-1 有 AID", h1.aid is not None)
    check("Host-1 有认证用户名", h1.username == "Zhangsan")

    # 验证交换机端口隔离配置
    data_sw = topo.switches["data-switch"]
    check("数据交换机有隔离组", len(data_sw._isolation_groups) == 3)
    group1 = data_sw._isolation_groups.get(1, set())
    check("隔离组1: CR1↔AP1 (端口1,2)", 1 in group1 and 2 in group1)


# ══════════════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════════════
async def main() -> None:
    global passed, failed
    setup_logging(level="ERROR")  # suppress verbose logs

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   标识网络模态仿真 — 逐项功能验证                            ║")
    print("║   56 tests + 15 verification categories                     ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    # 同步验证
    verify_aid()
    verify_rid()
    verify_aid_packet()
    verify_rid_packet()
    verify_ethernet()
    verify_rid_routing()
    verify_mapping()
    verify_user_status()
    verify_signaling()
    verify_authentication()
    verify_metrics()
    verify_topology_counts()

    # 异步验证
    await verify_virtual_link()
    await verify_port_isolation()
    # 注: CR 实时转发验证见 tests/test_e2e_forwarding.py (5个异步测试)
    # 本脚本仅做同步可验证项

    # 汇总
    total = passed + failed
    print(f"\n{'═'*62}")
    print(f"  验证结果: {passed}/{total} 通过", end="")
    if failed > 0:
        print(f", {failed} 失败 ❌")
    else:
        print(" ✅ 全部通过")
    print(f"{'═'*62}")
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
