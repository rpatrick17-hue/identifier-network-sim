#!/usr/bin/env python3
"""
标识网络模态 — 真机部署入口

每台北交大设备运行此脚本, 绑定真实物理网卡, 通过 AF_PACKET 收发
标识网络帧 (AID/RID)。中兴 CR 由硬件原生支持, 不在此部署范围内。

用法:
    sudo python3 scripts/real_deploy.py --role cs   --config config/cs.yaml
    sudo python3 scripts/real_deploy.py --role ap   --config config/ap1.yaml
    sudo python3 scripts/real_deploy.py --role ts   --config config/ts.yaml
    sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml

配置文件格式见 config/*.yaml.example
"""

from __future__ import annotations
import argparse, asyncio, os, signal, socket, struct, sys, time
from pathlib import Path
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger
from src.common.addressing import AID, RID, RIDSpace
from src.common.constants import InterfaceType, SpacePolicy, UserStatus, DataType
from src.common.ethernet import EthernetFrame, mac_from_str
from src.common.utils import setup_logging
from src.nodes.control_server import ControlServer
from src.nodes.access_point import AccessPoint
from src.nodes.test_server import TestServer
from src.nodes.host import Host

ETH_P_ALL = 0x0003; MTU = 2048


class RealNIC:
    """AF_PACKET raw socket bound to a physical NIC."""
    def __init__(self, name: str):
        self.name = name; self.sock: socket.socket | None = None; self.tx = 0; self.rx = 0

    def open(self) -> None:
        self.sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
        self.sock.bind((self.name, 0)); self.sock.setblocking(False)
        logger.info(f"NIC {self.name} opened")

    def send(self, data: bytes) -> bool:
        try: self.sock.send(data); self.tx += 1; return True
        except OSError: return False

    def recv(self) -> bytes | None:
        try: data = self.sock.recv(MTU); self.rx += 1; return data
        except (BlockingIOError, OSError): return None

    def fileno(self) -> int: return self.sock.fileno() if self.sock else -1
    def close(self) -> None:
        if self.sock: self.sock.close(); self.sock = None


# ═══════════════════════════════════════════════════════════
def build_cs(cfg: dict) -> ControlServer:
    cs = ControlServer("CS")
    cs.rid = RID(*cfg["cs_rid"])
    cs._mgmt_iface = 0
    cs.add_interface("mgmt", cfg["interfaces"][0]["mac"])
    for u in cfg.get("users", []):
        cs.register_user(u["username"], u["password"], pin=u.get("pin", "0000"),
                         custom_attributes=u.get("attributes", ""))
    for cr_rid in cfg.get("managed_crs", []):
        cs.db.managed_crs[RID(*cr_rid)] = f"CR-{cr_rid}"
    for ap_rid, cr_rid in cfg.get("ap_to_cr", []):
        cs.db.ap_to_cr[RID(*ap_rid)] = RID(*cr_rid)
    return cs


def build_ap(cfg: dict) -> AccessPoint:
    ap = AccessPoint("AP")
    ap.aid = AID.from_hex(cfg["aid"]); ap.rid = RID(*cfg["rid"])
    ap.cs_rid = RID(*cfg["cs_rid"]); ap.cr_rid = RID(*cfg["cr_rid"])
    ap.cs_mac = mac_from_str(cfg["cs_mac"]); ap.cr_mac = mac_from_str(cfg["cr_mac"])
    ap.add_interface("access", cfg["interfaces"][0]["mac"])
    ap._access_iface = 0; ap._cr_iface = 0
    for u in cfg.get("local_users", []):
        ap._add_local_user(AID.from_hex(u["aid"]), u.get("ip", ""), u.get("mac", ""),
                           authenticated=True)
    return ap


def build_ts(cfg: dict) -> TestServer:
    ts = TestServer("TS")
    ts.aid = AID.from_hex(cfg["aid"]); ts.rid = RID(*cfg["rid"]) if cfg.get("rid") else None
    ts.add_interface("access", cfg["interfaces"][0]["mac"])
    return ts


def build_host(cfg: dict) -> Host:
    h = Host("Host")
    h.aid = AID.from_hex(cfg["aid"])
    h.ip_address = cfg.get("ip", "192.168.1.100")
    h.username = cfg["username"]; h.password = cfg["password"]
    h.add_interface("access", cfg["interfaces"][0]["mac"])
    h._iface_idx = 0; h._ap_mac = cfg.get("ap_mac", "")
    h.load_aid_config(cfg["aid"], h.username, h.password)
    return h


BUILDERS = {"cs": build_cs, "ap": build_ap, "ts": build_ts, "host": build_host}


# ═══════════════════════════════════════════════════════════
async def run_device(role: str, cfg: dict) -> None:
    setup_logging(level="INFO")

    # 1. Build node
    node = BUILDERS[role](cfg)
    ifaces = cfg["interfaces"]
    nics = [RealNIC(iface["name"]) for iface in ifaces]
    for nic in nics: nic.open()

    # 2. Wire send_frame → NIC
    async def _nic_send(idx: int, frame: EthernetFrame) -> bool:
        if 0 <= idx < len(nics):
            ok = nics[idx].send(frame.serialize())
            if ok: node.metrics.record_send(len(frame.serialize()))
            return ok
        return False
    node.send_frame = _nic_send

    # 3. Start node
    node._running = True
    await node.on_start()

    # 4. Register NIC readable callbacks (MAC filter for multi-role isolation)
    loop = asyncio.get_running_loop()
    my_macs = set()
    for iface in node.interfaces:
        my_macs.add(iface.mac.hex())
        my_macs.add("ffffffffffff")  # always accept broadcast

    for idx, nic in enumerate(nics):
        def _cb(_nic=nic, _idx=idx):
            data = _nic.recv()
            if data and len(data) >= 14:
                dst_mac = data[0:6].hex()
                if dst_mac not in my_macs:
                    return  # not for us (another role on same NIC)
                try:
                    frame = EthernetFrame.deserialize(data)
                    if frame.is_aid or frame.is_rid:
                        asyncio.ensure_future(node.on_frame(_idx, frame))
                except Exception: pass
        loop.add_reader(nic.fileno(), _cb)

    # 5. Role-specific triggers
    if role == "ts":
        asyncio.create_task(_ts_ready(node))
    elif role == "host":
        asyncio.create_task(_host_scenario(node, cfg.get("target_aid", "")))

    logger.info(f"[{role}] running on {[n.name for n in nics]}")

    # 6. Main loop
    try:
        while node._running:
            await asyncio.sleep(1)
            m = node.metrics.summary()
            tx = sum(n.tx for n in nics); rx = sum(n.rx for n in nics)
            if tx > 0 or rx > 0:
                logger.debug(f"[{role}] nic_tx={tx} nic_rx={rx} s={m['sent_packets']} r={m['recv_packets']}")
    except KeyboardInterrupt:
        pass
    finally:
        node._running = False
        for nic in nics:
            try: loop.remove_reader(nic.fileno())
            except: pass; nic.close()
        logger.info(f"[{role}] stopped")


async def _ts_ready(ts: TestServer) -> None:
    await asyncio.sleep(1)
    await ts.start_http_server(page_size=4096, num_pages=5)
    await ts.start_ftp_server(file_count=3, file_size=100_000)
    await ts.start_video_server(chunk_count=10, chunk_size=50_000)
    # Start live monitor (periodic stats)
    await ts.start_monitor(interval_s=3.0)
    logger.info("[ts] HTTP/FTP/Video servers + monitor ready")

    # Optional: run RID forwarding test if target RIDs configured
    if ts.rid:
        from src.common.addressing import RID
        # Default: probe CR-1 and CR-2
        target_rids = [RID(10001, 36191), RID(12360, 34280)]
        asyncio.create_task(ts.run_rid_forwarding_test(target_rids, probes_per_target=3))


async def _host_scenario(host: Host, target_aid_hex: str) -> None:
    await asyncio.sleep(2)
    if target_aid_hex:
        target = AID.from_hex(target_aid_hex)
        await host.authenticate()
        for i in range(5):
            await host.http_get(f"/page_{i}.html", target)
            await asyncio.sleep(1)
        logger.info("[host] scenario done")
        host._running = False


# ═══════════════════════════════════════════════════════════
def main() -> None:
    if os.geteuid() != 0:
        print("需要 root 权限! sudo python3 scripts/real_deploy.py --role cs --config config/cs.yaml")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="标识网络真机部署")
    parser.add_argument("--role", required=True, choices=["cs", "ap", "ts", "host"])
    parser.add_argument("--config", required=True, help="YAML 配置文件路径")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = _PROJECT_ROOT / config_path
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    asyncio.run(run_device(args.role, cfg))


if __name__ == "__main__":
    main()
