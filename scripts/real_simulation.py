#!/usr/bin/env python3
"""
标识网络 — 真实 veth 仿真

软件转发 (asyncio.Queue, 已验证) + veth 镜像 (tcpdump 抓包)
每个设备有真实 veth 接口在命名空间中, Python 通过 raw socket 镜像流量.

架构:
  软件路径: Host-1 → Queue → AP-1 → Queue → CR-1 → ...
  镜像路径: 每帧同时写入 sender 的 veth → ns 侧 tcpdump 可见

用法:
    sudo python3 scripts/real_simulation.py test
    sudo python3 scripts/real_simulation.py http
    sudo python3 scripts/real_simulation.py mobility

抓包:
    sudo ip netns exec ns-host1 tcpdump -i veth-host1-ns -XX
"""

from __future__ import annotations
import asyncio, os, socket, struct, sys, time
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger
from src.common.utils import setup_logging
# 直接复用纯软件仿真的全部逻辑
from scripts.simulation import (
    build_topology, wire_and_start, stop_all, report,
    quick_test, demo_http, demo_mobility,
)

ETH_P_ALL = 0x0003
MTU = 2048

# veth host 侧接口名 (setup_netns.sh 创建)
VETH_MAP = {
    "host1": "veth-host1", "host2": "veth-host2",
    "ap1": "veth-ap1", "ap2": "veth-ap2",
    "ts": "veth-ts", "cs": "veth-cs",
    "cr1": "veth-cr1", "cr2": "veth-cr2",
}

class VethMirror:
    """将帧镜像写入 veth 的 raw socket (tcpdump 可见)."""
    def __init__(self, name: str, ifname: str):
        self.name = name; self.ifname = ifname
        self.sock: socket.socket | None = None; self.count = 0

    def open(self) -> None:
        self.sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
        self.sock.bind((self.ifname, 0)); self.sock.setblocking(False)

    def mirror(self, data: bytes) -> None:
        try: self.sock.send(data); self.count += 1
        except OSError: pass

    def close(self) -> None:
        if self.sock: self.sock.close(); self.sock = None

# ═══════════════════════════════════════════════════════════
def attach_mirrors(nodes: dict, mirrors: dict) -> None:
    """Monkey-patch 每个节点的 send_frame: 同时写 veth mirror."""
    for nk, node in nodes.items():
        if nk in mirrors:
            m = mirrors[nk]
            orig = node.send_frame
            def _factory(_node, _orig, _m):
                async def _send(iface_idx: int, frame) -> bool:
                    data = frame.serialize()
                    _m.mirror(data)  # 镜像到 veth
                    return await _orig(iface_idx, frame)
                return _send
            node.send_frame = _factory(node, orig, m)

# ═══════════════════════════════════════════════════════════
async def main() -> None:
    if os.geteuid() != 0:
        print("需要 sudo! sudo python3 scripts/real_simulation.py test"); sys.exit(1)

    sc = sys.argv[1] if len(sys.argv) > 1 else "test"
    setup_logging(level="WARNING")

    # 1. 打开所有 veth mirror sockets
    mirrors: dict[str, VethMirror] = {}
    for nk, ifname in VETH_MAP.items():
        m = VethMirror(nk, ifname)
        m.open()
        mirrors[nk] = m
        print(f"  mirror {nk} → {ifname}")

    # 2. 软件仿真 (已验证的 asyncio.Queue 路径)
    nodes = build_topology()
    tasks = await wire_and_start(nodes)
    attach_mirrors(nodes, mirrors)
    print(f"8 节点已启动, {len(mirrors)} veth mirrors 活跃")

    # 3. 运行场景
    try:
        dm = {"test": quick_test, "http": demo_http, "mobility": demo_mobility}
        if sc == "all":
            for f in dm.values(): await f(nodes); await asyncio.sleep(0.3)
        elif sc in dm: await dm[sc](nodes)
        else: print(f"未知: {sc}. 可用: test, http, mobility, all")
    finally:
        print("\n停止...")
        await stop_all(nodes, tasks)

        # veth mirror 统计
        total = 0
        for nk, m in mirrors.items():
            print(f"  veth {nk}: {m.count} frames mirrored")
            total += m.count; m.close()
        print(f"  总计 {total} 帧已写入 veth (tcpdump 可见)")
        print(report(nodes))

if __name__ == "__main__":
    asyncio.run(main())
