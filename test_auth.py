#!/usr/bin/env python3
"""
用户注册 & 登录验证脚本 (稳健版)

验证 1: CS 数据库层 (无需网络)
验证 2: 端到端认证 — 每次认证独立新建网络, 无残留干扰
"""

from __future__ import annotations
import asyncio, sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.common.addressing import AID, RID
from src.common.utils import setup_logging, generate_aid
from src.control_plane.signaling import AuthRequest, AuthResponse
from src.nodes.control_server import ControlServer
from src.nodes.access_point import AccessPoint
from src.nodes.host import Host
from src.simulation.virtual_link import VirtualSwitch


async def _run_auth_test(host_aid, host_password, ap_cache=None, timeout=5):
    """Run ONE auth test in a fresh isolated network. Returns True/False."""
    sw = VirtualSwitch("sw")

    cs = ControlServer("CS")
    cs.rid = RID(10028, 36181)
    cs.add_interface("eth", "00:1a:2b:3c:4d:01")
    cs._mgmt_iface = 0
    cs.register_user("Zhangsan", "123", pin="1234", custom_attributes="UR:3;BW:10Mbps")

    ap = AccessPoint("AP")
    ap.aid = AID.from_hex("8d969eef6ecad3c29a3a629280e686cf")
    ap.rid = RID(10001, 36191)
    ap.cs_rid = RID(10028, 36181)
    ap.cr_rid = RID(10001, 36191)
    ap.cs_mac = bytes.fromhex("001a2b3c4d01")
    ap.add_interface("eth", "00:04:ab:1f:40:a6")
    ap._access_iface = 0
    ap._cr_iface = 0
    if ap_cache:
        ap._neighbor_cache[host_aid] = ap_cache

    host = Host("Host")
    host.aid = host_aid
    host.ip_address = "192.168.1.100"
    host.username = "Zhangsan"
    host.password = host_password
    host.add_interface("wlan", "00:11:22:33:44:01")
    host._iface_idx = 0
    host._ap_mac = "00:04:ab:1f:40:a6"

    host.connect_switch(0, sw, 1)
    ap.connect_switch(0, sw, 2)
    cs.connect_switch(0, sw, 3)

    tasks = [asyncio.create_task(n.run()) for n in [host, ap, cs]]
    await asyncio.sleep(0.3)

    result = await host.authenticate()

    for n in [host, ap, cs]:
        n.stop()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    return result


def test_cs_database():
    """验证 1: CS 注册和数据库校验 (纯逻辑, 无网络)"""
    print("=" * 55)
    print("  验证 1: CS 用户注册 & 数据库校验")
    print("=" * 55)

    from src.tables.cs_tables import CSDatabase, UserRegistryEntry
    db = CSDatabase()
    aid1 = AID.from_hash(b"Zhangsan:1234:device01")
    aid2 = AID.from_hash(b"Lisi:0000:device02")
    db.add_user(UserRegistryEntry(user_aid=aid1, pin="1234", username="Zhangsan", password="123", custom_attributes="UR:3;BW:10Mbps"))
    db.add_user(UserRegistryEntry(user_aid=aid2, pin="0000", username="Lisi", password="Abc", custom_attributes="UR:2;BW:5Mbps"))

    checks = [
        ("正确密码登录", db.authenticate("Zhangsan", "123") is not None),
        ("错误密码登录", db.authenticate("Zhangsan", "wrong") is None),
        ("不存在用户",   db.authenticate("Nobody", "123") is None),
        ("PIN 码存储",   db.users.get("Zhangsan").pin == "1234"),
        ("定制属性解析", db.users.get("Zhangsan").parse_attributes() == {"UR": "3", "BW": "10Mbps"}),
    ]
    for name, ok in checks:
        print(f"  {name}: {'✅' if ok else '❌'}")
    return all(v for _, v in checks)


async def test_e2e_auth():
    """验证 2: 端到端 — 每次认证独立网络"""
    print("\n" + "=" * 55)
    print("  验证 2: 端到端 (每次独立网络)")
    print("=" * 55)

    host_aid = AID.from_hex("cad3c29a3a629280e686cf8d969eef6e")

    # 正确密码 → 应通过
    r = await _run_auth_test(host_aid, "123")
    print(f"  正确密码: {'✅ 通过' if r else '❌ 失败'}")

    # 错误密码 → 应拒绝
    r = await _run_auth_test(host_aid, "wrong")
    print(f"  错误密码: {'✅ 正确拒绝' if not r else '❌ 错误通过'}")

    # 快速认证 → 应通过 (AP 有缓存)
    ap_aid = AID.from_hex("8d969eef6ecad3c29a3a629280e686cf")
    ap_rid = RID(10001, 36191)
    r = await _run_auth_test(host_aid, "123", ap_cache=(ap_aid, ap_rid))
    print(f"  快速认证(缓存): {'✅ 通过' if r else '❌ 失败'}")


def main():
    setup_logging(level="WARNING")
    ok1 = test_cs_database()
    asyncio.run(test_e2e_auth())
    print("\n✅ 认证验证完成")


if __name__ == "__main__":
    main()
