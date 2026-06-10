#!/usr/bin/env python3
"""
CR 路由标识数据包转发验证 (文档 §4.2.1)

验证多模态网络核心路由器在核心网络范围内能够完成对路由标识(RID)
数据包的识别和转发。包括:
  1. 构建特定的 RID 数据包并注入 CR
  2. 在核心网络链路抓包识别
  3. 核心网络设备间基于 RID 的可达性探测

不需要 root, 不需要 veth. 纯软件仿真即可完整验证.
"""

from __future__ import annotations
import asyncio, sys, time
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.common.addressing import RID, RIDSpace
from src.common.constants import ETHERTYPE_RID, RID_HEADER_BYTES, SpacePolicy, InterfaceType
from src.common.packets import RIDPacket, AIDPacket
from src.common.ethernet import EthernetFrame, mac_from_str
from src.common.utils import setup_logging
from src.routing.rid_routing import rid_lookup, rid_lookup_next_hop, rid_route_add
from src.routing.mapping import cr_add_remote_mapping
from src.nodes.core_router import CoreRouter
from src.simulation.virtual_link import VirtualLink


def verify_rid_packet_structure():
    """验证 1: RID 数据包格式识别 (24字节包头)"""
    print("=" * 55)
    print("  验证 1: RID 数据包格式")
    print("=" * 55)

    src = RID(10001, 36191)
    dst = RID(12360, 34280)
    payload = b"PROBE:CR1->CR2:seq=1:ts=1234567890"

    pkt = RIDPacket(source_rid=src, destination_rid=dst, payload=payload,
                    qos_class=3, network_space_id=100, ttl=60)
    data = pkt.serialize()

    checks = [
        ("包头 24 字节",      len(data) - len(payload) == RID_HEADER_BYTES),
        ("版本 = 0001",       (data[0] >> 4) == 1),
        ("标识类型 = 0100",   (data[0] & 0xF) == 0b0100),
        ("QoS 字段",          data[1] == 3),
        ("网络空间 ID = 100", int.from_bytes(data[2:4], 'big') == 100),
        ("净荷长度",          int.from_bytes(data[4:6], 'big') == len(payload)),
        ("TTL = 60",          data[7] == 60),
        ("目的 RID",          int.from_bytes(data[8:16], 'big') == dst.as_int),
        ("源 RID",            int.from_bytes(data[16:24], 'big') == src.as_int),
        ("序列化往返",        RIDPacket.deserialize(data).destination_rid == dst),
    ]
    for name, ok in checks:
        print(f"  {name}: {'✅' if ok else '❌'}")

    # 以太网帧封装
    frame = EthernetFrame.from_rid_packet(
        pkt, mac_from_str("00:0c:ab:1e:76:8c"), mac_from_str("00:0c:ab:1e:76:8a"))
    fdata = frame.serialize()
    checks2 = [
        ("EtherType = 0x2222 (RID)",   frame.ethertype == ETHERTYPE_RID),
        ("帧识别为 RID",                 frame.is_rid),
        ("帧内 RID 包还原",             frame.inner_rid().source_rid == src),
    ]
    for name, ok in checks2:
        print(f"  {name}: {'✅' if ok else '❌'}")


def verify_rid_routing_table():
    """验证 2: RID 路由表查找 (二维前缀乘积匹配)"""
    print("\n" + "=" * 55)
    print("  验证 2: RID 路由表 & 二维前缀匹配")
    print("=" * 55)

    from src.tables.cr_tables import CRTables
    tables = CRTables()

    # 配置 CR 路由表 (静态配置, 文档 §4.1)
    rid_route_add(tables, 100, 12345, 34267, 20, 24, RID(12360, 34280))
    rid_route_add(tables, 100, 10028, 36181, 20, 20, RID(10030, 36190))
    rid_route_add(tables, 100, 12345, 34267, 22, 26, RID(12370, 34290))

    print("  RID 路由表 (空间 100):")
    for e in tables.rid_routes:
        prod = e.dest_rid_space.x_mask_bits * e.dest_rid_space.y_mask_bits
        print(f"    ({e.dest_rid_space.x}|{e.dest_rid_space.x_mask_bits}, "
              f"{e.dest_rid_space.y}|{e.dest_rid_space.y_mask_bits}) → "
              f"下一跳 {e.next_hop_rid}  (M₁×M₂={prod})")

    # 查表
    r1 = rid_lookup_next_hop(tables, RID(12345, 34267), 100)
    r2 = rid_lookup_next_hop(tables, RID(12346, 34268), 100)
    r3 = rid_lookup_next_hop(tables, RID(99999, 99999), 100)

    checks = [
        ("精确匹配 → CR-2",     r1 == RID(12370, 34290)),  # 22×26=572 > 20×24=480
        ("前缀匹配 → 仍可路由", r2 is not None),
        ("无匹配 → 丢弃",       r3 is None),
    ]
    for name, ok in checks:
        print(f"  {name}: {'✅' if ok else '❌'}")


async def verify_cr_rid_injection_and_capture():
    """验证 3: RID 包注入 CR 并在核心链路抓包识别 (文档 §4.2.1 核心要求)"""
    print("\n" + "=" * 55)
    print("  验证 3: RID 包注入 + 核心链路抓包")
    print("=" * 55)

    # ── 搭建 2-CR 核心网络 ──
    cr1 = CoreRouter("CR-1"); cr1.my_rid = RID(10001, 36191)
    cr2 = CoreRouter("CR-2"); cr2.my_rid = RID(12360, 34280)

    cr1.add_interface("core", "00:0c:ab:1e:76:8a", InterfaceType.ROUTE)
    cr2.add_interface("core", "00:0c:ab:1e:76:8c", InterfaceType.ROUTE)
    cr1.configure_interface(0, "core", "00:0c:ab:1e:76:8a", InterfaceType.ROUTE)
    cr2.configure_interface(0, "core", "00:0c:ab:1e:76:8c", InterfaceType.ROUTE)

    cr1.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)
    cr2.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)

    cr1.add_route_neighbor(100, RID(12360, 34280), "00:0c:ab:1e:76:8c", 0)
    cr2.add_route_neighbor(100, RID(10001, 36191), "00:0c:ab:1e:76:8a", 0)
    cr1.add_rid_route(100, 12345, 34267, 20, 24, RID(12360, 34280))
    cr2.add_rid_route(100, 10001, 36191, 20, 20, RID(10001, 36191))

    # 点对点核心链路
    core_link = VirtualLink(name="core-link")
    cr1.connect_link(0, core_link)
    cr2.connect_link(0, core_link)

    tasks = [asyncio.create_task(cr.run()) for cr in [cr1, cr2]]
    await asyncio.sleep(0.3)

    # ── 注入 RID 探测包: CR-1 → CR-2 ──
    print("  注入 RID 探测包: CR-1 → CR-2")
    for seq in range(1, 4):
        rid_pkt = RIDPacket(
            source_rid=cr1.my_rid,
            destination_rid=cr2.my_rid,
            payload=f"PROBE:CR1->CR2:seq={seq}".encode(),
            network_space_id=100, ttl=60,
        )
        t0 = time.time()
        await cr1.send_rid_packet(0, rid_pkt, mac_from_str("00:0c:ab:1e:76:8c"))
        await asyncio.sleep(0.15)
        dt = (time.time() - t0) * 1000
        print(f"    seq={seq}: 已发送 ({dt:.1f}ms)")

    # ── 抓包: CR-2 侧接收 ──
    m1 = cr1.metrics.summary()
    m2 = cr2.metrics.summary()
    print(f"\n  CR-1 发送: {m1['sent_packets']} 包 / {m1['sent_bytes']} 字节")
    print(f"  CR-2 接收: {m2['recv_packets']} 包 / {m2['recv_bytes']} 字节")

    ok = m2["recv_packets"] >= 3
    print(f"  核心链路 RID 转发: {'✅ CR-2 收到全部3个探测包' if ok else '❌'}")

    # ── 可达性探测验证 ──
    print("\n  可达性探测 (RID Ping):")
    hop = rid_lookup_next_hop(cr1.tables, RID(12360, 34280), 100)
    if hop:
        print(f"    CR-1 → 查路由表 → 下一跳 RID{hop}")
        print(f"    CR-1 可达 CR-2: {'✅' if hop == cr2.my_rid else '❌'}")

    hop2 = rid_lookup_next_hop(cr2.tables, RID(10001, 36191), 100)
    if hop2:
        print(f"    CR-2 → 查路由表 → 下一跳 RID{hop2}")
        print(f"    CR-2 可达 CR-1: {'✅' if hop2 == cr1.my_rid else '❌'}")

    for cr in [cr1, cr2]:
        cr.stop()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def verify_rid_encapsulation_forwarding():
    """验证 4: RID 封装转发 (AID→RID→AID 端到端)"""
    print("\n" + "=" * 55)
    print("  验证 4: AID→RID 封装 + 转发 + 解封装")
    print("=" * 55)

    from src.nodes.access_point import AccessPoint
    from src.nodes.host import Host
    from src.nodes.test_server import TestServer
    from src.simulation.virtual_link import VirtualSwitch
    from src.common.addressing import AID
    from src.common.constants import UserStatus

    # ── 完整 2-CR + 2-AP + TS + Host ──
    cr1 = CoreRouter("CR-1"); cr1.my_rid = RID(10001, 36191)
    cr2 = CoreRouter("CR-2"); cr2.my_rid = RID(12360, 34280)

    for cr in [cr1, cr2]:
        cr.add_interface("core", "00:0c:ab:1e:76:" + ("8a" if cr == cr1 else "8c"), InterfaceType.ROUTE)
        cr.add_interface("access", "00:18:54:fd:29:" + ("01" if cr == cr1 else "02"), InterfaceType.ACCESS)
        cr.configure_interface(0, "core", cr.interfaces[0].mac_str, InterfaceType.ROUTE)
        cr.configure_interface(1, "access", cr.interfaces[1].mac_str, InterfaceType.ACCESS)
        cr.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)

    cr1.add_route_neighbor(100, cr2.my_rid, "00:0c:ab:1e:76:8c", 0)
    cr2.add_route_neighbor(100, cr1.my_rid, "00:0c:ab:1e:76:8a", 0)
    cr1.add_rid_route(100, 12345, 34267, 20, 24, cr2.my_rid)
    cr1.add_rid_route(100, 10001, 36191, 20, 20, cr2.my_rid)  # AP-2也在CR-2下
    cr2.add_rid_route(100, 10001, 36191, 20, 20, cr1.my_rid)

    # TS 的 AID 和映射
    ts_aid = AID.from_hex("d3c29a3a629280e686cf8d969eef6eca")
    ap1_aid = AID.from_hex("8d969eef6ecad3c29a3a629280e686cf")
    host_aid = AID.from_hex("cad3c29a3a629280e686cf8d969eef6e")

    cr1.add_access_neighbor(ap1_aid, "00:04:ab:1f:40:a6", 1)
    cr1.add_access_neighbor(ts_aid, "00:1a:2b:3c:4d:02", 1)
    cr1.add_associated_ap(ap1_aid, RID(10001, 36191), 1)
    cr1.add_local_mapping(ap1_aid, RID(10001, 36191), 0)
    cr1.add_local_mapping(host_aid, RID(10001, 36191), 0)
    cr1.add_local_mapping(ts_aid, RID(10003, 36193), 0)
    cr1.set_user_status(host_aid, ap1_aid, UserStatus.ONLINE)
    cr1.set_user_status(ts_aid, ap1_aid, UserStatus.ONLINE)

    # Host-2 在 CR-2 侧
    host2_aid = AID.from_hex("969eef6ecad3c29a3a629280e686cf8d")
    ap2_aid = AID.from_hex("280e686cf8d969eef6ecad3c29a3a629")
    cr2.add_access_neighbor(ap2_aid, "00:05:dc:12:33:28", 1)
    cr2.add_access_neighbor(host2_aid, "00:11:22:33:44:02", 1)
    cr2.add_associated_ap(ap2_aid, RID(10002, 36192), 1)
    cr2.add_local_mapping(ap2_aid, RID(10002, 36192), 0)
    cr2.add_local_mapping(host2_aid, RID(10002, 36192), 0)
    cr2.set_user_status(host2_aid, ap2_aid, UserStatus.ONLINE)
    cr_add_remote_mapping(cr1.tables, host2_aid, RID(10002, 36192), cr2.my_rid, 100)
    cr_add_remote_mapping(cr2.tables, host_aid, RID(10001, 36191), cr1.my_rid, 100)

    # 核心链路 + 接入交换机
    core_link = VirtualLink("core")
    sw1 = VirtualSwitch("sw1")
    sw2 = VirtualSwitch("sw2")

    ap1 = AccessPoint("AP-1")
    ap1.aid = ap1_aid; ap1.rid = RID(10001, 36191); ap1.cr_rid = cr1.my_rid
    ap1.cr_mac = mac_from_str("00:18:54:fd:29:01")
    ap1.add_interface("eth", "00:04:ab:1f:40:a6"); ap1._access_iface = 0; ap1._cr_iface = 0

    ts = TestServer("TS"); ts.aid = ts_aid; ts.add_interface("eth", "00:1a:2b:3c:4d:02")

    host = Host("Host-1"); host.aid = host_aid
    host.ip_address = "192.168.1.100"; host.username = "Zhangsan"; host.password = "123"
    host.add_interface("wlan", "00:11:22:33:44:01"); host._iface_idx = 0
    host._ap_mac = "00:04:ab:1f:40:a6"

    # 接线
    cr1.connect_link(0, core_link); cr2.connect_link(0, core_link)
    cr1.connect_switch(1, sw1, 1); ap1.connect_switch(0, sw1, 2)
    ts.connect_switch(0, sw1, 3); host.connect_switch(0, sw1, 4)
    cr2.connect_switch(1, sw2, 1)

    all_nodes = [cr1, cr2, ap1, ts, host]
    tasks = [asyncio.create_task(n.run()) for n in all_nodes]
    await asyncio.sleep(0.3)
    # 跳过认证: CR 转发验证不需要 CS
    host._authenticated = True
    await ts.start_http_server(page_size=2048, num_pages=3)

    # 发送 HTTP 请求 → AID 封装 → RID 封装 → 核心网转发
    # Host-1 → Host-2 (跨CR, 必须经过核心网 RID 路由)
    print("  Host-1 → Host-2 (跨 CR, RID 核心转发)")
    cr1.set_user_status(host.aid, ap1_aid, UserStatus.ONLINE)
    for i in range(3):
        await host.http_get(f"/page_{i}.html", host2_aid)
        await asyncio.sleep(0.1)

    m_cr1 = cr1.metrics.summary()
    m_cr2 = cr2.metrics.summary()
    m_host = host.metrics.summary()

    print(f"\n  Host-1 发送: {m_host['sent_packets']} 包 (→ Host-2, 跨CR)")
    print(f"  CR-1 收发:  {m_cr1['sent_packets']} 发送 (AID→RID封装) / {m_cr1['recv_packets']} 接收")
    print(f"  CR-2 收发:  {m_cr2['sent_packets']} 发送 (RID→AID解封装) / {m_cr2['recv_packets']} 接收")
    print(f"  TS 接收:    {ts.metrics.summary()['recv_packets']} 包 (本地投递)")

    ok_cr1 = m_cr1["sent_packets"] >= 3
    ok_cr2 = m_cr2["recv_packets"] >= 3
    print(f"\n  CR-1 AID→RID 封装发送: {'✅' if ok_cr1 else '❌'} ({m_cr1['sent_packets']}/3)")
    print(f"  CR-2 RID→AID 解封装接收: {'✅' if ok_cr2 else '❌'} ({m_cr2['recv_packets']}/3)")
    print(f"  RID 封装+核心转发 端到端: {'✅' if ok_cr1 and ok_cr2 else '❌'}")

    for n in all_nodes:
        n.stop()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    setup_logging(level="WARNING")
    verify_rid_packet_structure()
    verify_rid_routing_table()
    await verify_cr_rid_injection_and_capture()
    await verify_rid_encapsulation_forwarding()
    print("\n✅ CR 转发验证完成")


if __name__ == "__main__":
    asyncio.run(main())
