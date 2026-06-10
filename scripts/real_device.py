#!/usr/bin/env python3
"""
标识网络 — 真实设备进程 (TAP 模式)

每个设备进程通过 TAP 接口收发真实以太网帧,
所有帧经 Linux bridge 转发到其他设备。

用法 (由 orchestrator 调用):
    ip netns exec ns-xxx python3 scripts/real_device.py <type>
    type: cr1, cr2, cs, ap1, ap2, ts, host1, host2
"""

from __future__ import annotations
import asyncio, sys, time
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger as _log
from src.common.addressing import AID, RID, RIDSpace
from src.common.constants import InterfaceType, SpacePolicy, UserStatus, DataType
from src.common.ethernet import EthernetFrame, mac_from_str
from src.common.utils import setup_logging
from src.nodes.core_router import CoreRouter
from src.nodes.access_point import AccessPoint
from src.nodes.control_server import ControlServer
from src.nodes.test_server import TestServer
from src.nodes.host import Host
from src.network.tap_interface import TapDevice
from src.routing.mapping import cr_add_remote_mapping

# ═══════════════════════════════════════════════════════════
#  设备配置
# ═══════════════════════════════════════════════════════════

A = {
    "h1": AID.from_hex("cad3c29a3a629280e686cf8d969eef6e"),
    "h2": AID.from_hex("969eef6ecad3c29a3a629280e686cf8d"),
    "ap1": AID.from_hex("8d969eef6ecad3c29a3a629280e686cf"),
    "ap2": AID.from_hex("280e686cf8d969eef6ecad3c29a3a629"),
    "ts":  AID.from_hex("d3c29a3a629280e686cf8d969eef6eca"),
}
R1=RID(10001,36191); R2=RID(12360,34280); A1R=RID(10001,36191); A2R=RID(10002,36192)
CSR=RID(10028,36181); TSR=RID(10003,36193)

# MAC addresses (must match setup_netns.sh TAP_MAC)
MAC = {
    "cr1":   "00:c0:01:01:00:01",
    "cr2":   "00:c0:01:02:00:01",
    "cs":    "00:c0:01:10:00:01",
    "ap1":   "00:c0:01:11:00:01", "ap2":   "00:c0:01:12:00:01",
    "ts":    "00:c0:01:20:00:01",
    "host1": "00:c0:01:31:00:01", "host2": "00:c0:01:32:00:01",
}


# ═══════════════════════════════════════════════════════════
def build_node(dev_type: str):
    """Create and configure the appropriate node."""

    if dev_type == "cr1":
        cr = CoreRouter("CR-1"); cr.my_rid = R1
        # Single TAP interface — all traffic (AID/RID/control) through one port
        cr.add_interface("tap", MAC["cr1"])
        cr.configure_interface(0, "tap", MAC["cr1"], InterfaceType.ACCESS)
        cr.add_rid_space(100, RIDSpace(12345,34267,20,24), SpacePolicy.DEFAULT)
        cr.add_access_neighbor(A["ap1"], MAC["ap1"], 0)
        cr.add_access_neighbor(A["ts"], MAC["ts"], 0)
        cr.add_access_neighbor(A["h1"], MAC["host1"], 0)
        cr.add_route_neighbor(100, R2, MAC["cr2"], 0)
        cr.add_rid_route(100, 12345, 34267, 20, 24, R2)
        cr.add_associated_ap(A["ap1"], A1R, 0)
        cr.add_local_mapping(A["ap1"], A1R, 0); cr.add_local_mapping(A["h1"], A1R, 0); cr.add_local_mapping(A["ts"], TSR, 0)
        cr.set_user_status(A["h1"], A["ap1"], UserStatus.ONLINE); cr.set_user_status(A["ts"], A["ap1"], UserStatus.ONLINE)
        cr_add_remote_mapping(cr.tables, A["h2"], A2R, R2, 100)
        return cr

    if dev_type == "cr2":
        cr = CoreRouter("CR-2"); cr.my_rid = R2
        cr.add_interface("tap", MAC["cr2"])
        cr.configure_interface(0, "tap", MAC["cr2"], InterfaceType.ACCESS)
        cr.add_rid_space(100, RIDSpace(12345,34267,20,24), SpacePolicy.DEFAULT)
        cr.add_access_neighbor(A["ap2"], MAC["ap2"], 0)
        cr.add_access_neighbor(A["h2"], MAC["host2"], 0)
        cr.add_route_neighbor(100, R1, MAC["cr1"], 0)
        cr.add_rid_route(100, 10001, 36191, 20, 20, R1)
        cr.add_associated_ap(A["ap2"], A2R, 0)
        cr.add_local_mapping(A["ap2"], A2R, 0); cr.add_local_mapping(A["h2"], A2R, 0)
        cr.set_user_status(A["h2"], A["ap2"], UserStatus.ONLINE)
        cr_add_remote_mapping(cr.tables, A["h1"], A1R, R1, 100); cr_add_remote_mapping(cr.tables, A["ts"], TSR, R1, 100)
        return cr

    if dev_type == "cs":
        cs = ControlServer("CS"); cs.rid = CSR
        cs.add_interface("mgmt", MAC["cs"], InterfaceType.ROUTE); cs._mgmt_iface = 0
        cs.register_user("Zhangsan", "123", pin="1234", custom_attributes="UR:3;BW:10Mbps")
        cs.register_user("Lisi", "Abc", pin="0000", custom_attributes="UR:2;BW:5Mbps")
        return cs

    if dev_type == "ap1":
        ap = AccessPoint("AP-1"); ap.aid=A["ap1"]; ap.rid=A1R; ap.cs_rid=CSR; ap.cr_rid=R1; ap.cr_mac=mac_from_str(MAC["cr1"])
        ap.add_interface("acc", MAC["ap1"]); ap._access_iface=0; ap._cr_iface=0
        ap._add_local_user(A["h1"], "192.168.1.100", MAC["host1"], authenticated=True)
        return ap

    if dev_type == "ap2":
        ap = AccessPoint("AP-2"); ap.aid=A["ap2"]; ap.rid=A2R; ap.cs_rid=CSR; ap.cr_rid=R2; ap.cr_mac=mac_from_str(MAC["cr2"])
        ap.add_interface("acc", MAC["ap2"]); ap._access_iface=0; ap._cr_iface=0
        ap._add_local_user(A["h2"], "192.168.2.100", MAC["host2"], authenticated=True)
        return ap

    if dev_type == "ts":
        ts = TestServer("TS"); ts.aid=A["ts"]; ts.rid=TSR
        ts.add_interface("acc", MAC["ts"])
        return ts

    if dev_type == "host1":
        h = Host("Host-1"); h.aid=A["h1"]; h.ip_address="192.168.1.100"
        h.load_aid_config("cad3c29a3a629280e686cf8d969eef6e", "Zhangsan", "123")
        h.add_interface("acc", MAC["host1"]); h._iface_idx=0; h._ap_mac=MAC["ap1"]
        return h

    if dev_type == "host2":
        h = Host("Host-2"); h.aid=A["h2"]; h.ip_address="192.168.2.100"
        h.load_aid_config("969eef6ecad3c29a3a629280e686cf8d", "Lisi", "Abc")
        h.add_interface("acc", MAC["host2"]); h._iface_idx=0; h._ap_mac=MAC["ap2"]
        return h

    raise ValueError(f"Unknown device: {dev_type}")


# ═══════════════════════════════════════════════════════════
def tap_names(dev_type: str) -> list[str]:
    """Return the TAP interface name for a device (single bridge, one TAP per device)."""
    return [f"tap-{dev_type}"]


# ═══════════════════════════════════════════════════════════
async def run_device(dev_type: str) -> None:
    setup_logging(level="INFO")
    log = _log.bind(node=dev_type)
    log.info("starting")

    # 1. Build node
    node = build_node(dev_type)
    taps = [TapDevice(name) for name in tap_names(dev_type)]
    for t in taps:
        t.open()
        log.info(f"TAP {t.name} opened")

    # 2. Wire send_frame → TAP write
    orig_send = node.send_frame
    async def _tap_send(iface_idx: int, frame: EthernetFrame) -> bool:
        if 0 <= iface_idx < len(taps):
            ok = taps[iface_idx].write(frame.serialize())
            if ok:
                node.metrics.record_send(len(frame.serialize()))
            return ok
        return False
    node.send_frame = _tap_send

    # 3. Start node
    node._running = True
    await node.on_start()

    # 4. Register TAP readable callbacks
    loop = asyncio.get_running_loop()

    for idx, t in enumerate(taps):
        def _make_cb(_t=t, _idx=idx):
            def _cb():
                data = _t.read()
                if data and len(data) >= 14:
                    try:
                        frame = EthernetFrame.deserialize(data)
                        if frame.is_aid or frame.is_rid:
                            asyncio.ensure_future(node.on_frame(_idx, frame))
                    except Exception:
                        pass
            return _cb
        loop.add_reader(t.fileno, _make_cb())

    # 5. Scenario trigger (hosts auto-send, ts auto-start)
    if dev_type in ("host1", "host2"):
        async def _scenario():
            await asyncio.sleep(4.0)  # wait for all TAPs to be opened
            ts_aid = A["ts"]
            if dev_type == "host1":
                await node.authenticate()
                for i in range(3):
                    await node.http_get(f"/page_{i}.html", ts_aid)
                    await asyncio.sleep(0.5)
            else:
                await node.authenticate()
                await node.http_get("/test", ts_aid)
            log.info("scenario done, stopping")
            node._running = False  # trigger exit
        asyncio.create_task(_scenario())

    if dev_type == "ts":
        async def _ts_ready():
            await asyncio.sleep(0.5)
            await node.start_http_server(page_size=4096, num_pages=5)
            # Auto-exit after receiving enough packets (hosts send 4 total)
            for _ in range(50):  # wait up to 10s
                if node.metrics.summary()["recv_packets"] >= 4:
                    break
                await asyncio.sleep(0.2)
            log.info("TS auto-stop")
            node._running = False
        asyncio.create_task(_ts_ready())

    # 6. Auto-stop for non-host devices (after hosts finish scenario)
    if dev_type not in ("host1", "host2"):
        async def _auto_stop():
            await asyncio.sleep(15)
            log.info("auto-stop timeout")
            node._running = False
        asyncio.create_task(_auto_stop())

    # 7. Main loop
    try:
        while node._running:
            await asyncio.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        node._running = False
        for t in taps:
            try: loop.remove_reader(t.fileno)
            except: pass
            t.close()
        stats = node.metrics.summary()
        tx = sum(t.tx_pkts for t in taps)
        rx = sum(t.rx_pkts for t in taps)
        log.info(f"stopped s={stats['sent_packets']} r={stats['recv_packets']} tap_tx={tx} tap_rx={rx}")
        # Output for orchestrator
        print(f"RESULT:{dev_type}:sent={stats['sent_packets']},recv={stats['recv_packets']},tap_tx={tx},tap_rx={rx}")


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/real_device.py <type>")
        print("Types: cr1, cr2, cs, ap1, ap2, ts, host1, host2")
        sys.exit(1)
    await run_device(sys.argv[1])


if __name__ == "__main__":
    asyncio.run(main())
