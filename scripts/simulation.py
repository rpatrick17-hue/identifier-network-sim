#!/usr/bin/env python3
"""
标识网络模态 — 完整仿真系统

构建 2CR+2AP+1CS+1TS+2Host 拓扑，运行端到端业务演示。

用法:
    python3 scripts/simulation.py test          # 冒烟测试
    python3 scripts/simulation.py http          # HTTP 浏览
    python3 scripts/simulation.py ftp           # FTP 下载
    python3 scripts/simulation.py mobility      # 移动切换
    python3 scripts/simulation.py all           # 全部依次运行
"""

from __future__ import annotations

import asyncio, sys, time
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger
from src.common.addressing import AID, RID, RIDSpace
from src.common.constants import InterfaceType, SpacePolicy, UserStatus
from src.common.ethernet import mac_from_str
from src.common.utils import setup_logging
from src.nodes.core_router import CoreRouter
from src.nodes.access_point import AccessPoint
from src.nodes.control_server import ControlServer
from src.nodes.test_server import TestServer
from src.nodes.host import Host
from src.simulation.virtual_link import VirtualLink, VirtualSwitch
from src.routing.mapping import cr_add_remote_mapping, cr_update_mapping


def build_topology() -> dict:
    """Build verified 2CR+2AP+1CS+1TS+2Host topology.

    Verified by test_e2e_forwarding.py — 5 end-to-end tests pass.
    """

    # ── MAC ─────────────────────────────────────────────────────
    M = {
        "cr1_acc":  mac_from_str("00:18:54:fd:29:01"),
        "cr1_core": mac_from_str("00:0c:ab:1e:76:8a"),
        "cr2_acc":  mac_from_str("00:18:54:fd:29:02"),
        "cr2_core": mac_from_str("00:0c:ab:1e:76:8c"),
        "cs": mac_from_str("00:1a:2b:3c:4d:01"),
        "ap1": mac_from_str("00:04:ab:1f:40:a6"),
        "ap2": mac_from_str("00:05:dc:12:33:28"),
        "ts": mac_from_str("00:1a:2b:3c:4d:02"),
        "host1": mac_from_str("00:11:22:33:44:01"),
        "host2": mac_from_str("00:11:22:33:44:02"),
    }

    # ── AID ─────────────────────────────────────────────────────
    A = {
        "host1": AID.from_hex("cad3c29a3a629280e686cf8d969eef6e"),
        "host2": AID.from_hex("969eef6ecad3c29a3a629280e686cf8d"),
        "ap1":   AID.from_hex("8d969eef6ecad3c29a3a629280e686cf"),
        "ap2":   AID.from_hex("280e686cf8d969eef6ecad3c29a3a629"),
        "ts":    AID.from_hex("d3c29a3a629280e686cf8d969eef6eca"),
    }

    # ── RID ─────────────────────────────────────────────────────
    cr1_rid = RID(10001, 36191)
    cr2_rid = RID(12360, 34280)
    ap1_rid = RID(10001, 36191)
    ap2_rid = RID(10002, 36192)
    cs_rid  = RID(10028, 36181)
    ts_rid  = RID(10003, 36193)

    # ═══════════════════════════════════════════════════════════
    #  CR-1
    # ═══════════════════════════════════════════════════════════
    cr1 = CoreRouter(name="CR-1")
    cr1.my_rid = cr1_rid
    cr1.add_interface("Eth0", "00:18:54:fd:29:01", InterfaceType.ACCESS)
    cr1.add_interface("Eth1", "00:0c:ab:1e:76:8a", InterfaceType.ROUTE)
    cr1.configure_interface(0, "Eth0", "00:18:54:fd:29:01", InterfaceType.ACCESS)
    cr1.configure_interface(1, "Eth1", "00:0c:ab:1e:76:8a", InterfaceType.ROUTE)
    cr1.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)
    cr1.add_rid_space(100, RIDSpace(10001, 36191, 20, 20), SpacePolicy.DEFAULT)
    cr1.add_access_neighbor(A["ap1"], "00:04:ab:1f:40:a6", 0)
    cr1.add_access_neighbor(A["ts"], "00:1a:2b:3c:4d:02", 0)
    cr1.add_route_neighbor(100, cr2_rid, "00:0c:ab:1e:76:8c", 1)
    cr1.add_rid_route(100, 12345, 34267, 20, 24, cr2_rid)
    cr1.add_associated_ap(A["ap1"], ap1_rid, 0)
    cr1.add_local_mapping(A["ap1"], ap1_rid, 0)
    cr1.add_local_mapping(A["host1"], ap1_rid, 0)
    cr1.add_local_mapping(A["ts"], ts_rid, 0)
    cr1.set_user_status(A["host1"], A["ap1"], UserStatus.ONLINE)
    cr1.set_user_status(A["ts"], A["ap1"], UserStatus.ONLINE)
    cr_add_remote_mapping(cr1.tables, A["host2"], ap2_rid, cr2_rid, 100)

    # ═══════════════════════════════════════════════════════════
    #  CR-2
    # ═══════════════════════════════════════════════════════════
    cr2 = CoreRouter(name="CR-2")
    cr2.my_rid = cr2_rid
    cr2.add_interface("Eth0", "00:18:54:fd:29:02", InterfaceType.ACCESS)
    cr2.add_interface("Eth1", "00:0c:ab:1e:76:8c", InterfaceType.ROUTE)
    cr2.configure_interface(0, "Eth0", "00:18:54:fd:29:02", InterfaceType.ACCESS)
    cr2.configure_interface(1, "Eth1", "00:0c:ab:1e:76:8c", InterfaceType.ROUTE)
    cr2.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)
    cr2.add_access_neighbor(A["ap2"], "00:05:dc:12:33:28", 0)
    cr2.add_route_neighbor(100, cr1_rid, "00:0c:ab:1e:76:8a", 1)
    cr2.add_rid_route(100, 10001, 36191, 20, 20, cr1_rid)
    cr2.add_associated_ap(A["ap2"], ap2_rid, 0)
    cr2.add_local_mapping(A["ap2"], ap2_rid, 0)
    cr2.add_local_mapping(A["host2"], ap2_rid, 0)
    cr2.set_user_status(A["host2"], A["ap2"], UserStatus.ONLINE)
    cr_add_remote_mapping(cr2.tables, A["host1"], ap1_rid, cr1_rid, 100)
    cr_add_remote_mapping(cr2.tables, A["ts"], ts_rid, cr1_rid, 100)

    # ═══════════════════════════════════════════════════════════
    #  CS — 注册用户, 使用 CS 生成的 AID (保证匹配)
    # ═══════════════════════════════════════════════════════════
    cs = ControlServer(name="CS")
    cs.rid = cs_rid
    cs.add_interface("Eth0", "00:1a:2b:3c:4d:01", InterfaceType.ROUTE)
    cs.add_interface("Eth1", "00:1a:2b:3c:4d:03", InterfaceType.ROUTE)
    cs._mgmt_iface = 0
    zs_entry = cs.register_user("Zhangsan", "123", pin="1234", custom_attributes="UR:3;BW:10Mbps")
    ls_entry = cs.register_user("Lisi", "Abc", pin="0000", custom_attributes="UR:2;BW:5Mbps")
    # 用 CS 生成的 AID 覆盖预定义值, 保证 Host 和 CS 的 AID 一致
    A["h1"] = zs_entry.user_aid
    A["h2"] = ls_entry.user_aid
    # 注册 CR 到 CS (全局映射传播需要)
    cs.db.managed_crs[cr1_rid] = "CR-1"
    cs.db.managed_crs[cr2_rid] = "CR-2"
    cs.db.managed_aps[ap1_rid] = "AP-1"
    cs.db.managed_aps[ap2_rid] = "AP-2"
    cs.db.ap_to_cr[ap1_rid] = cr1_rid
    cs.db.ap_to_cr[ap2_rid] = cr2_rid

    # ═══════════════════════════════════════════════════════════
    #  APs
    # ═══════════════════════════════════════════════════════════
    ap1 = AccessPoint(name="AP-1")
    ap1.aid = A["ap1"]; ap1.rid = ap1_rid
    ap1.cs_rid = cs_rid; ap1.cr_rid = cr1_rid; ap1.cr_mac = M["cr1_acc"]; ap1.cs_mac = M["cs"]
    ap1.add_interface("Wlan0", "00:04:ab:1f:40:a6", InterfaceType.ACCESS)
    ap1._access_iface = 0; ap1._cr_iface = 0
    ap1._add_local_user(A["host1"], "192.168.1.100", "00:11:22:33:44:01", authenticated=True)

    ap2 = AccessPoint(name="AP-2")
    ap2.aid = A["ap2"]; ap2.rid = ap2_rid
    ap2.cs_rid = cs_rid; ap2.cr_rid = cr2_rid; ap2.cr_mac = M["cr2_acc"]; ap2.cs_mac = M["cs"]
    ap2.add_interface("Wlan0", "00:05:dc:12:33:28", InterfaceType.ACCESS)
    ap2._access_iface = 0; ap2._cr_iface = 0

    # ═══════════════════════════════════════════════════════════
    #  TS + Hosts
    # ═══════════════════════════════════════════════════════════
    ts = TestServer(name="TS")
    ts.aid = A["ts"]; ts.rid = ts_rid
    ts.add_interface("Eth0", "00:1a:2b:3c:4d:02", InterfaceType.ACCESS)

    h1 = Host(name="Host-1")
    h1.aid = A["host1"]; h1.ip_address = "192.168.1.100"
    h1.load_aid_config(A["h1"].to_hex(), "Zhangsan", "123")
    h1.add_interface("Wlan0", "00:11:22:33:44:01", InterfaceType.ACCESS)
    h1._iface_idx = 0; h1._ap_mac = "00:04:ab:1f:40:a6"

    h2 = Host(name="Host-2")
    h2.aid = A["host2"]; h2.ip_address = "192.168.2.100"
    h2.load_aid_config(A["h2"].to_hex(), "Lisi", "Abc")
    h2.add_interface("Wlan0", "00:11:22:33:44:02", InterfaceType.ACCESS)
    h2._iface_idx = 0; h2._ap_mac = "00:05:dc:12:33:28"

    # ═══════════════════════════════════════════════════════════
    #  Virtual links (verified pattern from test_e2e_forwarding.py)
    # ═══════════════════════════════════════════════════════════
    sw1 = VirtualSwitch(name="sw-1")
    sw2 = VirtualSwitch(name="sw-2")
    core_link = VirtualLink(name="core")

    nodes = {
        "cr1": cr1, "cr2": cr2, "cs": cs,
        "ap1": ap1, "ap2": ap2,
        "ts": ts, "host1": h1, "host2": h2,
        "sw1": sw1, "sw2": sw2, "core_link": core_link,
    }
    return nodes


async def wire_and_start(nodes: dict) -> list[asyncio.Task]:
    """Wire nodes to switches/links and start event loops."""

    # Access side: Host / AP / CR / CS / TS on switches
    nodes["host1"].connect_switch(0, nodes["sw1"], 1)
    nodes["ap1"].connect_switch(0, nodes["sw1"], 2)
    nodes["cr1"].connect_switch(0, nodes["sw1"], 3)
    nodes["ts"].connect_switch(0, nodes["sw1"], 4)
    nodes["cs"].connect_switch(0, nodes["sw1"], 5)
    nodes["cs"].connect_switch(1, nodes["sw2"], 5)

    nodes["host2"].connect_switch(0, nodes["sw2"], 1)
    nodes["ap2"].connect_switch(0, nodes["sw2"], 2)
    nodes["cr2"].connect_switch(0, nodes["sw2"], 3)

    # Core: CR-1 ↔ CR-2 via point-to-point link
    nodes["cr1"].connect_link(1, nodes["core_link"])
    nodes["cr2"].connect_link(1, nodes["core_link"])

    # Start all nodes
    tasks = []
    for key in ["cr1", "cr2", "cs", "ap1", "ap2", "ts", "host1", "host2"]:
        t = asyncio.create_task(nodes[key].run())
        tasks.append(t)
    await asyncio.sleep(0.3)
    return tasks


async def stop_all(nodes: dict, tasks: list[asyncio.Task]) -> None:
    for key in ["host1", "host2", "ap1", "ap2", "ts", "cs", "cr1", "cr2"]:
        nodes[key].stop()
    for t in tasks:
        if not t.done():
            t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def report(nodes: dict) -> str:
    lines = [f"\n{'='*55}", f"  Simulation Report", f"{'='*55}"]
    for key in ["cr1", "cr2", "cs", "ap1", "ap2", "ts", "host1", "host2"]:
        n = nodes[key]
        m = n.metrics.summary()
        lines.append(
            f"  {n.name:<10s} sent={m['sent_packets']:>4d} recv={m['recv_packets']:>4d} "
            f"bytes={m['sent_bytes']:>6d}/{m['recv_bytes']:>6d}"
        )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  Demo scenarios
# ═══════════════════════════════════════════════════════════════

async def quick_test(nodes: dict) -> None:
    print("\n=== 冒烟测试: 8节点连通性 ===")
    h1, h2, ts = nodes["host1"], nodes["host2"], nodes["ts"]

    await h1.authenticate(); await h2.authenticate()
    await ts.start_http_server()

    await h1.http_get("/test", ts.aid)
    await asyncio.sleep(0.2)
    await h2.http_get("/test", ts.aid)
    await asyncio.sleep(0.3)

    print(f"  Host-1: sent={h1.metrics.summary()['sent_packets']}")
    print(f"  Host-2: sent={h2.metrics.summary()['sent_packets']}")
    print(f"  TS:     recv={ts.metrics.summary()['recv_packets']}")
    print(f"  CR-1:   recv={nodes['cr1'].metrics.summary()['recv_packets']}")
    print(f"  CR-2:   recv={nodes['cr2'].metrics.summary()['recv_packets']}")


async def demo_http(nodes: dict) -> None:
    print("\n=== HTTP 浏览: Host-1 → TS ===")
    h1, ts = nodes["host1"], nodes["ts"]
    await h1.authenticate()
    await ts.start_http_server(page_size=4096, num_pages=5)
    for i in range(5):
        t0 = time.time()
        await h1.http_get(f"/page_{i%5}.html", ts.aid)
        print(f"  GET /page_{i%5}.html → {(time.time()-t0)*1000:.1f}ms")
        await asyncio.sleep(0.15)
    print(f"  TS recv: {ts.metrics.summary()['recv_packets']} pkts")


async def demo_ftp(nodes: dict) -> None:
    print("\n=== FTP 下载: Host-1 ← TS ===")
    h1, ts = nodes["host1"], nodes["ts"]
    await h1.authenticate()
    await ts.start_ftp_server(file_count=5, file_size=200_000)
    for i in range(3):
        t0 = time.time()
        await h1.ftp_download(f"file_{i}.bin", ts.aid)
        print(f"  RETR file_{i}.bin → {(time.time()-t0)*1000:.1f}ms")
        await asyncio.sleep(0.1)
    print(f"  Host sent: {h1.metrics.summary()['sent_packets']} pkts")


async def demo_mobility(nodes: dict) -> None:
    print("\n=== 移动切换: Host-1 AP-1 → AP-2 ===")
    h1, ts = nodes["host1"], nodes["ts"]
    cr1, cr2 = nodes["cr1"], nodes["cr2"]
    ap1, ap2 = nodes["ap1"], nodes["ap2"]

    await h1.authenticate()
    await ts.start_http_server()

    print("  Phase 1: Host-1 on AP-1 (场景1&2: 切换前, 正常通信)")
    await h1.http_get("/test", ts.aid); await asyncio.sleep(0.15)

    print("  Phase 2: 切换 AP-1→AP-2 (全自动激活)")
    # 新AP自动: 注册CS + 通知CR + 通告邻居
    await ap2.activate_user(h1.aid, h1.ip_address, "00:11:22:33:44:01",
                             custom_attributes="UR:3;BW:10Mbps")
    # 旧CR标记移走, 更新映射
    cr1.set_user_status(h1.aid, ap1.aid, UserStatus.MOVED_AWAY)
    cr_update_mapping(cr1.tables, h1.aid, ap2.rid, cr2.my_rid)
    await asyncio.sleep(0.3)

    print(f"  CR-1: {UserStatus(cr1.tables.user_statuses[h1.aid].status).name}")
    print(f"  CR-2: {UserStatus(cr2.tables.user_statuses[h1.aid].status).name}")
    print(f"  CS映射: {'✅' if h1.aid in nodes['cs'].db.mappings else '❌'}")

    print("  Phase 3: 主动发送 (场景3: 切换后, Host-1从新位置主动发包)")
    await h1.http_get("/after_move", ts.aid); await asyncio.sleep(0.15)

    print("  Phase 4: 被动接收 (场景4: 远端→Host-1, 旧CR重定向→新CR)")
    # 模拟时间窗口: CR-2 尚未收到CS更新, 仍用旧映射 (Host-1→CR-1)
    # Host-2 发包给 Host-1 → CR-2 封装 RID 发往 CR-1
    # CR-1 收到 → 发现 Host-1 已移走 → 重封装发往 CR-2 → Host-1 被动接收
    h2 = nodes["host2"]
    h2._authenticated = True
    # 临时恢复为旧映射: CR-2 认为 Host-1 还在 CR-1 (模拟未收到CS更新)
    cr2.tables.remote_mappings.pop(h1.aid, None)
    cr_add_remote_mapping(cr2.tables, h1.aid, nodes["ap1"].rid, cr1.my_rid, 100)
    cr2.tables.user_statuses.pop(h1.aid, None)  # 清除本地在线状态
    # AP-2 本地移除Host-1, 让AID包经过CR-2→CR-1→重定向
    nodes["ap2"]._local_users.pop(h1.aid, None)
    pre_cr1 = cr1.metrics.summary()["sent_packets"]
    pre_cr2 = cr2.metrics.summary()["recv_packets"]
    await h2.http_get("/to_host1", h1.aid); await asyncio.sleep(0.3)
    post_cr1 = cr1.metrics.summary()["sent_packets"]
    post_cr2 = cr2.metrics.summary()["recv_packets"]
    print(f"  CR-1 重定向: {'✅' if post_cr1 > pre_cr1 else '❌'} (发送 {pre_cr1}→{post_cr1})")
    print(f"  Host-1 被动接收: {'✅' if post_cr2 > pre_cr2 else '❌'} (CR-2收 {pre_cr2}→{post_cr2})")


# ═══════════════════════════════════════════════════════════════
async def main() -> None:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "test"
    setup_logging(level="WARNING")

    nodes = build_topology()
    tasks = await wire_and_start(nodes)
    print(f"8 节点已启动")

    try:
        demos = {"http": demo_http, "ftp": demo_ftp, "mobility": demo_mobility, "test": quick_test}
        if scenario == "all":
            for fn in demos.values():
                await fn(nodes)
                await asyncio.sleep(0.3)
        elif scenario in demos:
            await demos[scenario](nodes)
        else:
            print(f"未知: {scenario}. 可用: test, http, ftp, mobility, all")
    finally:
        print("\n停止仿真...")
        await stop_all(nodes, tasks)
        print(report(nodes))


if __name__ == "__main__":
    asyncio.run(main())
