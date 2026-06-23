#!/usr/bin/env python3
"""
GNS3 Topology Automation — 标识网络完整拓扑

通过 GNS3 REST API 创建:
  - 6 CR (Core Router)
  - 1 CS (Control Server)
  - 1 TS (Test Server)
  - 2 AP (Access Point)
  - 2 Host (User Terminal)
  - 2 交换机 (管理面 + 数据面 with VLAN)

用法:
    python3 scripts/gns3_topology.py create    # 创建拓扑
    python3 scripts/gns3_topology.py start     # 启动全部节点
    python3 scripts/gns3_topology.py stop      # 停止全部节点
    python3 scripts/gns3_topology.py delete    # 删除项目
    python3 scripts/gns3_topology.py status    # 查看状态
"""

import json, os, sys, time, urllib.request, urllib.error

GNS3 = "http://192.168.80.222:3080/v2"
PROJECT_NAME = "identifier-network-sim"
ALPINE_ISO = "/home/ngit/GNS3/images/QEMU/alpine-virt-3.21.3-x86_64.iso"
QEMU_BIN = "/usr/bin/qemu-system-x86_64"


def api(method, path, data=None):
    """Call GNS3 REST API."""
    url = f"{GNS3}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        print(f"  API Error {e.code}: {e.reason} on {method} {path}")
        return None


# ═══════════════════════════════════════════════════════════
#  Node definitions
# ═══════════════════════════════════════════════════════════

# Each CR has 3 NICs: management, core (VLAN10), access (VLAN20/30)
# Other nodes have 1 NIC on appropriate VLAN
NODES = {
    "CR-1":  {"type": "qemu", "ram": 256, "nics": 3,
              "console": 5001, "rid": [10001, 36191]},
    "CR-2":  {"type": "qemu", "ram": 256, "nics": 3,
              "console": 5002, "rid": [12360, 34280]},
    "CR-3":  {"type": "qemu", "ram": 256, "nics": 3,
              "console": 5003, "rid": [10030, 36190]},
    "CR-4":  {"type": "qemu", "ram": 256, "nics": 3,
              "console": 5004, "rid": [12365, 34282]},
    "CR-5":  {"type": "qemu", "ram": 256, "nics": 3,
              "console": 5005, "rid": [3540, 12768]},
    "CR-6":  {"type": "qemu", "ram": 256, "nics": 3,
              "console": 5006, "rid": [3545, 12770]},
    "CS":    {"type": "qemu", "ram": 256, "nics": 1,
              "console": 5010, "rid": [10028, 36181]},
    "TS":    {"type": "qemu", "ram": 256, "nics": 1,
              "console": 5011, "rid": [10003, 36193]},
    "AP-1":  {"type": "qemu", "ram": 256, "nics": 1,
              "console": 5012, "rid": [10001, 36191]},
    "AP-2":  {"type": "qemu", "ram": 256, "nics": 1,
              "console": 5013, "rid": [10002, 36192]},
    "Host-1":{"type": "qemu", "ram": 128, "nics": 1,
              "console": 5014, "rid": None},
    "Host-2":{"type": "qemu", "ram": 128, "nics": 1,
              "console": 5015, "rid": None},
}


# ═══════════════════════════════════════════════════════════
#  Switch & link definitions
# ═══════════════════════════════════════════════════════════

# Management switch: CS + all CR management (NIC 0)
MGMT_PORTS = ["CS", "CR-1", "CR-2", "CR-3", "CR-4", "CR-5", "CR-6"]

# Data switch VLANs
VLAN10_CORE = ["CR-1", "CR-2", "CR-3", "CR-4", "CR-5", "CR-6"]  # NIC 1
VLAN20_ACC1 = ["CR-1", "AP-1", "TS", "Host-1"]                  # NIC 2 (CR-1), NIC 0 (others)
VLAN30_ACC2 = ["CR-2", "AP-2", "Host-2"]                         # NIC 2 (CR-2), NIC 0 (others)


def _nic_index(node_name, vlan_nodes):
    """Determine which NIC of a node connects to a given VLAN."""
    if node_name.startswith("CR"):
        if vlan_nodes == VLAN10_CORE:
            return 1   # CR core port = NIC 1
        else:
            return 2   # CR access port = NIC 2
    return 0  # non-CR = only NIC 0


# ═══════════════════════════════════════════════════════════
def cmd_create():
    """Create project, switches, nodes, and links."""
    # 1. Create or open project
    projects = api("GET", "/projects") or []
    pid = None
    for p in projects:
        if p["name"] == PROJECT_NAME:
            pid = p["project_id"]
            print(f"项目已存在: {pid}")
            break
    if not pid:
        p = api("POST", "/projects", {"name": PROJECT_NAME})
        pid = p["project_id"]
        print(f"创建项目: {pid}")
    api("POST", f"/projects/{pid}/open")

    # 2. Create QEMU nodes
    node_ids = {}
    for name, cfg in NODES.items():
        print(f"创建节点: {name} (QEMU, {cfg['ram']}MB, {cfg['nics']} NICs)")
        n = api("POST", f"/projects/{pid}/nodes", {
            "name": name,
            "node_type": "qemu",
            "compute_id": "local",
            "properties": {
                "qemu_path": QEMU_BIN,
                "hda_disk_image": ALPINE_ISO,
                "hda_disk_interface": "ide",
                "ram": cfg["ram"],
                "adapters": cfg["nics"],
                "console_type": "telnet",
                "console": cfg["console"],
            }
        })
        if n:
            node_ids[name] = n["node_id"]
            print(f"  → {n['node_id']} (console: telnet://ucs-worker-2:{cfg['console']})")

    # 3. Create switches
    print("创建交换机...")
    mgmt_sw = api("POST", f"/projects/{pid}/nodes", {
        "name": "Mgmt-Switch",
        "node_type": "ethernet_switch",
        "compute_id": "local",
    })
    data_sw = api("POST", f"/projects/{pid}/nodes", {
        "name": "Data-Switch",
        "node_type": "ethernet_switch",
        "compute_id": "local",
    })
    if mgmt_sw: node_ids["Mgmt-Switch"] = mgmt_sw["node_id"]
    if data_sw: node_ids["Data-Switch"] = data_sw["node_id"]

    # 4. Create links
    print("创建连线...")
    links_created = 0

    # Management switch links
    for node in MGMT_PORTS:
        if node in node_ids:
            _link(pid, node_ids[node], 0, node_ids["Mgmt-Switch"], 0)
            links_created += 1

    # VLAN 10 (core) links → Data Switch
    for node in VLAN10_CORE:
        if node in node_ids:
            nic = _nic_index(node, VLAN10_CORE)
            _link(pid, node_ids[node], nic, node_ids["Data-Switch"], 0)
            links_created += 1

    # VLAN 20 (access1) links → Data Switch
    for node in VLAN20_ACC1:
        if node in node_ids:
            nic = _nic_index(node, VLAN20_ACC1)
            _link(pid, node_ids[node], nic, node_ids["Data-Switch"], 0)
            links_created += 1

    # VLAN 30 (access2) links → Data Switch
    for node in VLAN30_ACC2:
        if node in node_ids:
            nic = _nic_index(node, VLAN30_ACC2)
            _link(pid, node_ids[node], nic, node_ids["Data-Switch"], 0)
            links_created += 1

    print(f"\n拓扑创建完成!")
    print(f"  项目ID: {pid}")
    print(f"  节点:   {len(node_ids)}")
    print(f"  连线:   {links_created}")
    print(f"  可在 GUI 中刷新查看拓扑")


def _link(pid, node1_id, nic1, node2_id, nic2):
    """Create a link between two nodes."""
    return api("POST", f"/projects/{pid}/links", {
        "nodes": [
            {"node_id": node1_id, "adapter_number": nic1, "port_number": 0},
            {"node_id": node2_id, "adapter_number": nic2, "port_number": 0},
        ]
    })


# ═══════════════════════════════════════════════════════════
def cmd_start():
    """Start all nodes."""
    pid = _get_project_id()
    if not pid: return
    nodes = api("GET", f"/projects/{pid}/nodes") or []
    for n in nodes:
        print(f"启动 {n['name']}...")
        api("POST", f"/projects/{pid}/nodes/{n['node_id']}/start")
        time.sleep(1)
    print("全部启动完成")


def cmd_stop():
    """Stop all nodes."""
    pid = _get_project_id()
    if not pid: return
    nodes = api("GET", f"/projects/{pid}/nodes") or []
    for n in nodes:
        print(f"停止 {n['name']}...")
        api("POST", f"/projects/{pid}/nodes/{n['node_id']}/stop")
    print("全部停止")


def cmd_delete():
    pid = _get_project_id()
    if not pid: return
    api("DELETE", f"/projects/{pid}")
    print(f"项目 {PROJECT_NAME} 已删除")


def cmd_status():
    pid = _get_project_id()
    if not pid:
        print(f"项目 {PROJECT_NAME} 不存在")
        return
    nodes = api("GET", f"/projects/{pid}/nodes") or []
    print(f"{'Node':<10} {'Status':<12} {'Console'}")
    print("-" * 40)
    for n in nodes:
        status = n.get("status", "unknown")
        console = n.get("console", "")
        if console:
            print(f"{n['name']:<10} {status:<12} telnet://ucs-worker-2:{console}")
        else:
            print(f"{n['name']:<10} {status:<12}")


def _get_project_id():
    projects = api("GET", "/projects") or []
    for p in projects:
        if p["name"] == PROJECT_NAME:
            return p["project_id"]
    print(f"项目 {PROJECT_NAME} 不存在, 先执行 create")
    return None


# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"create": cmd_create, "start": cmd_start, "stop": cmd_stop,
     "delete": cmd_delete, "status": cmd_status}.get(cmd, cmd_status)()
