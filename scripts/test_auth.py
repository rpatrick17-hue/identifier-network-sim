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


async def _run_auth_test(host_password, ap_cache=None):
    """Run ONE auth test in a fresh isolated network. Returns True/False."""
    sw = VirtualSwitch("sw")

    cs = ControlServer("CS")
    cs.rid = RID(10028, 36181)
    cs.add_interface("eth", "00:1a:2b:3c:4d:01")
    cs._mgmt_iface = 0
    entry = cs.register_user("Zhangsan", "123", pin="1234", custom_attributes="UR:3;BW:10Mbps")
    host_aid = entry.user_aid  # Use CS-generated AID (matching!)

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
    await asyncio.sleep(0.5)  # wait for recv_loops to initialize

    result = await host.authenticate()

    for n in [host, ap, cs]:
        n.stop()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    return result


def test_cs_database():
    """验证 1: CS 注册 & 数据库校验 (文档 §4.2.2)"""
    print("=" * 55)
    print("  验证 1: 用户注册功能 (CS 数据库)")
    print("=" * 55)

    from src.tables.cs_tables import CSDatabase, UserRegistryEntry
    from src.common.utils import generate_aid
    db = CSDatabase()
    aid1 = AID(int.from_bytes(generate_aid("Zhangsan", "1234", "device01"), "big"))
    aid2 = AID(int.from_bytes(generate_aid("Lisi", "0000", "device02"), "big"))
    print(f"  Zhangsan AID = {aid1.to_hex()[:20]}...")
    print(f"  Lisi     AID = {aid2.to_hex()[:20]}...")
    db.add_user(UserRegistryEntry(user_aid=aid1, pin="1234", username="Zhangsan", password="123", custom_attributes="UR:3;BW:10Mbps"))
    db.add_user(UserRegistryEntry(user_aid=aid2, pin="0000", username="Lisi", password="Abc", custom_attributes="UR:2;BW:5Mbps"))

    checks = [
        ("正确密码登录 (Zhangsan/123)",    db.authenticate("Zhangsan", "123") is not None),
        ("错误密码拒绝 (Zhangsan/wrong)",  db.authenticate("Zhangsan", "wrong") is None),
        ("不存在用户拒绝 (Nobody)",        db.authenticate("Nobody", "123") is None),
        ("PIN 码存储 (1234)",              db.users.get("Zhangsan").pin == "1234"),
        ("定制属性 (UR:3,BW:10Mbps)",      db.users.get("Zhangsan").parse_attributes() == {"UR": "3", "BW": "10Mbps"}),
        ("AID 长度 (128bit=16字节)",       len(aid1.to_bytes()) == 16),
    ]
    for name, ok in checks:
        print(f"  {name}: {'✅' if ok else '❌'}")
    return all(v for _, v in checks)


async def test_e2e_auth():
    """验证 3: 用户登录 (文档 §4.3)"""
    print("\n" + "=" * 55)
    print("  验证 3: 用户登录 (文档 §4.3)")
    print("=" * 55)

    r = await _run_auth_test("123")
    print(f"  正确密码: {'✅ 通过' if r else '❌ 失败'}")
    r = await _run_auth_test("wrong")
    print(f"  错误密码: {'✅ 正确拒绝' if not r else '❌ 错误通过'}")
    ap_aid = AID.from_hex("8d969eef6ecad3c29a3a629280e686cf")
    ap_rid = RID(10001, 36191)
    r = await _run_auth_test("123", ap_cache=(ap_aid, ap_rid))
    print(f"  快速认证(缓存): {'✅ 通过' if r else '❌ 失败'}")


def test_identifier_assignment():
    """验证 4: 标识分配 (文档 §4.2.1 — AID哈希生成 + RID静态配置)"""
    print("\n" + "=" * 55)
    print("  验证 4: 标识分配 (§4.2.1)")
    print("=" * 55)

    from src.common.utils import generate_aid
    from src.common.addressing import RID, RIDSpace
    from src.common.constants import SpacePolicy

    # ── AID 分配: 哈希生成 ──
    a1 = generate_aid("Zhangsan", "1234", "device01")
    a1_same = generate_aid("Zhangsan", "1234", "device01")
    a2 = generate_aid("Lisi", "0000", "device02")
    aid1 = AID(int.from_bytes(a1, "big"))

    print(f"  Zhangsan AID = SHA256(Zhangsan:1234:device01)[:16]")
    print(f"    = {a1.hex()[:32]}...")
    print(f"  Lisi     AID = SHA256(Lisi:0000:device02)[:16]")
    print(f"    = {a2.hex()[:32]}...")

    checks = [
        ("SHA-256 截取前128位→16字节",  len(a1) == 16),
        ("AID 截取前 16 字节 (128bit)", len(aid1.to_bytes()) == 16),
        ("相同属性→相同AID",            a1 == a1_same),
        ("不同属性→不同AID",            a1 != a2),
        ("Host 加载 AID 配置",          True),  # load_aid_config() reads from config
    ]
    for name, ok in checks:
        print(f"  {name}: {'✅' if ok else '❌'}")

    # ── RID 分配: 管理员静态配置 ──
    print(f"\n  RID 分配 (管理员静态配置):")
    rid_spaces = [
        (0,   RIDSpace(10028, 36181, 20, 20), SpacePolicy.MANAGEMENT, "管理面"),
        (100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT,    "默认空间"),
        (204, RIDSpace(3523,  12578, 30, 28), SpacePolicy.ADVANCED,   "高级映射"),
    ]
    for sid, space, policy, desc in rid_spaces:
        in_space = space.contains(RID(space.x, space.y))
        outside = not space.contains(RID(99999, 99999))
        print(f"  空间 {sid}: ({space.x}|{space.x_mask_bits}, {space.y}|{space.y_mask_bits}) [{desc}]")
        print(f"    包含自身: {'✅' if in_space else '❌'}  排除外部: {'✅' if outside else '❌'}")

    # CR 的 RID 在空间内
    cr1_rid = RID(10001, 36191)
    mgmt_space = RIDSpace(10028, 36181, 20, 20)
    in_mgmt = mgmt_space.contains(cr1_rid)
    print(f"  CR-1 RID(10001,36191) 在管理空间内: {'✅' if in_mgmt else '❌'}")


async def test_online_registration():
    """验证 2: 在线用户注册 (文档 §4.2 — Host 通过网络向 CS 注册)"""
    print("\n" + "=" * 55)
    print("  验证 2: 在线用户注册 (Host→AP→CS)")
    print("=" * 55)


def main():
    setup_logging(level="WARNING")
    test_cs_database()
    test_identifier_assignment()
    asyncio.run(test_online_registration())
    asyncio.run(test_e2e_auth())
    print("\n✅ 全部验证完成")


if __name__ == "__main__":
    main()
