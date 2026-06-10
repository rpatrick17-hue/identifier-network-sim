"""Standalone demo runner – builds a working test topology and runs scenarios.

Usage:
    python scenarios/run_demo.py                  # Run all demos
    python scenarios/run_demo.py http             # HTTP demo only
    python scenarios/run_demo.py ftp              # FTP demo
    python scenarios/run_demo.py mobility         # Mobility demo
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.common.addressing import AID, RID
from src.common.constants import UserStatus
from src.common.utils import setup_logging
from src.simulation.virtual_link import VirtualSwitch
from src.nodes.core_router import CoreRouter
from src.nodes.access_point import AccessPoint
from src.nodes.host import Host
from src.nodes.test_server import TestServer


def _build_demo_topology() -> dict:
    """Build a working mini topology for demos."""
    # Nodes
    host1 = Host(name="Host-1")
    host1.aid = AID.from_hex("cad3c29a3a629280e686cf8d969eef6e")
    host1.ip_address = "192.168.1.100"
    host1.load_aid_config("cad3c29a3a629280e686cf8d969eef6e", "Zhangsan", "123")
    host1.add_interface("Wlan0", "00:11:22:33:44:01")

    host2 = Host(name="Host-2")
    host2.aid = AID.from_hex("969eef6ecad3c29a3a629280e686cf8d")
    host2.ip_address = "192.168.2.100"
    host2.load_aid_config("969eef6ecad3c29a3a629280e686cf8d", "Lisi", "Abc")
    host2.add_interface("Wlan0", "00:11:22:33:44:02")

    ts = TestServer(name="TS")
    ts.aid = AID.from_hex("d3c29a3a629280e686cf8d969eef6eca")
    ts.rid = RID(10003, 36193)
    ts.add_interface("Eth0", "00:1a:2b:3c:4d:02")

    ap1 = AccessPoint(name="AP-1")
    ap1.aid = AID.from_hex("8d969eef6ecad3c29a3a629280e686cf")
    ap1.rid = RID(10001, 36191)
    ap1.cr_rid = RID(10001, 36191)
    ap1.cs_rid = RID(10028, 36181)
    ap1.add_interface("Wlan0", "00:04:ab:1f:40:a6")
    ap1._access_iface = 0; ap1._cr_iface = 0

    ap2 = AccessPoint(name="AP-2")
    ap2.aid = AID.from_hex("280e686cf8d969eef6ecad3c29a3a629")
    ap2.rid = RID(10002, 36192)
    ap2.cr_rid = RID(12360, 34280)
    ap2.cs_rid = RID(10028, 36181)
    ap2.add_interface("Wlan0", "00:05:dc:12:33:28")
    ap2._access_iface = 0; ap2._cr_iface = 0

    cr1 = CoreRouter(name="CR-1")
    cr1.my_rid = RID(10001, 36191)
    cr1.add_interface("Eth0", "00:18:54:fd:29:01"); cr1.add_interface("Eth1", "00:0c:ab:1e:76:8a")
    from src.common.constants import InterfaceType as IT
    cr1.configure_interface(0, "Eth0", "00:18:54:fd:29:01", IT.ACCESS)
    cr1.configure_interface(1, "Eth1", "00:0c:ab:1e:76:8a", IT.ROUTE)
    from src.common.addressing import RIDSpace
    from src.common.constants import SpacePolicy
    cr1.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)
    cr1.add_route_neighbor(100, RID(12360, 34280), "00:0c:ab:1e:76:8c", 1)
    cr1.add_rid_route(100, 12345, 34267, 20, 24, RID(12360, 34280))
    cr1.add_associated_ap(ap1.aid, ap1.rid, 0)
    cr1.add_local_mapping(ap1.aid, ap1.rid, 0)
    cr1.set_user_status(host1.aid, ap1.aid, UserStatus.ONLINE)
    cr1.set_user_status(ts.aid, ap1.aid, UserStatus.ONLINE)
    from src.routing.mapping import cr_add_remote_mapping
    cr_add_remote_mapping(cr1.tables, host2.aid, RID(10002, 36192), RID(12360, 34280), 100)
    cr_add_remote_mapping(cr1.tables, ts.aid, RID(10003, 36193), RID(10001, 36191), 100)
    cr1.add_local_mapping(host1.aid, RID(10001, 36191), 100)

    cr2 = CoreRouter(name="CR-2")
    cr2.my_rid = RID(12360, 34280)
    cr2.add_interface("Eth0", "00:18:54:fd:29:02"); cr2.add_interface("Eth1", "00:0c:ab:1e:76:8c")
    cr2.configure_interface(0, "Eth0", "00:18:54:fd:29:02", IT.ACCESS)
    cr2.configure_interface(1, "Eth1", "00:0c:ab:1e:76:8c", IT.ROUTE)
    cr2.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)
    cr2.add_route_neighbor(100, RID(10001, 36191), "00:0c:ab:1e:76:8a", 1)
    cr2.add_rid_route(100, 10001, 36191, 20, 20, RID(10001, 36191))
    cr2.add_associated_ap(ap2.aid, ap2.rid, 0)
    cr2.add_local_mapping(ap2.aid, ap2.rid, 0)
    cr2.set_user_status(host2.aid, ap2.aid, UserStatus.ONLINE)
    cr_add_remote_mapping(cr2.tables, host1.aid, RID(10001, 36191), RID(10001, 36191), 100)

    # Switches
    sw1 = VirtualSwitch(name="sw-1")
    sw2 = VirtualSwitch(name="sw-2")
    from src.simulation.virtual_link import VirtualLink
    core_link = VirtualLink(name="core")

    return {
        "host1": host1, "host2": host2, "ts": ts,
        "ap1": ap1, "ap2": ap2,
        "cr1": cr1, "cr2": cr2,
        "sw1": sw1, "sw2": sw2, "core_link": core_link,
    }


async def _wire_and_start(nodes: dict) -> list[asyncio.Task]:
    nodes["host1"].connect_switch(0, nodes["sw1"], 1)
    nodes["ap1"].connect_switch(0, nodes["sw1"], 2)
    nodes["cr1"].connect_switch(0, nodes["sw1"], 3)
    nodes["ts"].connect_switch(0, nodes["sw1"], 4)

    nodes["host2"].connect_switch(0, nodes["sw2"], 1)
    nodes["ap2"].connect_switch(0, nodes["sw2"], 2)
    nodes["cr2"].connect_switch(0, nodes["sw2"], 3)

    nodes["cr1"].connect_link(1, nodes["core_link"])
    nodes["cr2"].connect_link(1, nodes["core_link"])

    tasks = []
    for k in ["host1", "host2", "ts", "ap1", "ap2", "cr1", "cr2"]:
        t = asyncio.create_task(nodes[k].run())
        tasks.append(t)
    await asyncio.sleep(0.3)
    return tasks


async def _stop_all(nodes: dict, tasks: list) -> None:
    for k in ["host1", "host2", "ts", "ap1", "ap2", "cr1", "cr2"]:
        nodes[k].stop()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


# ======================================================================
#  Demo scenarios
# ======================================================================

async def demo_http(nodes: dict) -> None:
    print("\n" + "=" * 60)
    print("  HTTP Browsing Demo: Host-1 → Test Server")
    print("=" * 60)

    host, ts = nodes["host1"], nodes["ts"]
    await host.authenticate()
    await ts.start_http_server(page_size=4096, num_pages=5)
    print(f"  Host-1 authenticated | TS ready: 5 pages × 4KB")

    for i in range(5):
        t0 = time.time()
        await host.http_get(f"/page_{i % 5}.html", ts.aid)
        print(f"  GET /page_{i%5}.html → {(time.time()-t0)*1000:.1f}ms")
        await asyncio.sleep(0.2)

    m = ts.metrics.summary()
    print(f"\n  TS  recv: {m['recv_packets']} pkts / {m['recv_bytes']}B")
    print(f"  Host sent: {host.metrics.summary()['sent_packets']} pkts")


async def demo_ftp(nodes: dict) -> None:
    print("\n" + "=" * 60)
    print("  FTP Download Demo: Host-1 downloads from TS")
    print("=" * 60)

    host, ts = nodes["host1"], nodes["ts"]
    await host.authenticate()
    await ts.start_ftp_server(file_count=5, file_size=200_000)
    print(f"  TS ready: 5 files × 200KB")

    for i in range(3):
        t0 = time.time()
        await host.ftp_download(f"file_{i}.bin", ts.aid)
        print(f"  RETR file_{i}.bin → {(time.time()-t0)*1000:.1f}ms")
        await asyncio.sleep(0.2)

    print(f"  Host sent: {host.metrics.summary()['sent_packets']} pkts")


async def demo_video(nodes: dict) -> None:
    print("\n" + "=" * 60)
    print("  Video Streaming Demo: Host-2 streams from TS")
    print("=" * 60)

    host, ts = nodes["host2"], nodes["ts"]
    await host.authenticate()
    await ts.start_video_server(chunk_count=20, chunk_size=50_000)
    print(f"  TS ready: 20 chunks × 50KB")

    t0 = time.time()
    await host.video_stream(ts.aid, duration_s=3.0)
    await asyncio.sleep(1.0)
    elapsed = time.time() - t0
    m = ts.metrics.summary()
    tp = (m["recv_bytes"] * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
    print(f"  {m['recv_bytes']}B in {elapsed:.1f}s → {tp:.1f}Mbps")


async def demo_mobility(nodes: dict) -> None:
    print("\n" + "=" * 60)
    print("  Mobility Handover Demo: Host-1 AP-1 → AP-2")
    print("=" * 60)

    host, ts = nodes["host1"], nodes["ts"]
    cr1, cr2 = nodes["cr1"], nodes["cr2"]
    ap1, ap2 = nodes["ap1"], nodes["ap2"]

    await host.authenticate()
    await ts.start_http_server()

    print("  Phase 1: Host-1 on AP-1 (CR-1)")
    await host.http_get("/test", ts.aid)
    await asyncio.sleep(0.3)

    print("  Phase 2: Host-1 moves AP-1 → AP-2 (CR-2)")
    cr1.set_user_status(host.aid, ap1.aid, UserStatus.MOVED_AWAY)
    cr2.set_user_status(host.aid, ap2.aid, UserStatus.ONLINE)
    from src.routing.mapping import cr_update_mapping
    cr_update_mapping(cr1.tables, host.aid, RID(10002, 36192), RID(12360, 34280))

    print("  Phase 3: Host-1 sends from new location")
    await host.http_get("/after_move", ts.aid)
    await asyncio.sleep(0.3)

    print(f"  CR-1: Host={UserStatus(cr1.tables.user_statuses[host.aid].status).name}")
    print(f"  CR-2: Host={UserStatus(cr2.tables.user_statuses[host.aid].status).name}")


# ======================================================================
#  Main
# ======================================================================

async def main() -> None:
    demo = sys.argv[1] if len(sys.argv) > 1 else "all"
    setup_logging(level="WARNING")

    nodes = _build_demo_topology()
    tasks = await _wire_and_start(nodes)
    print(f"\nTopology: {', '.join(n.name for n in nodes.values() if hasattr(n, 'name'))}")

    try:
        demos = {"http": demo_http, "ftp": demo_ftp, "video": demo_video, "mobility": demo_mobility}
        if demo == "all":
            for fn in demos.values():
                await fn(nodes)
                await asyncio.sleep(0.5)
        elif demo in demos:
            await demos[demo](nodes)
        else:
            print(f"Unknown: {demo}. Available: {', '.join(demos)} | all")
    finally:
        print("\nShutting down...")
        await _stop_all(nodes, tasks)
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
