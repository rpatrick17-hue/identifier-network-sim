#!/usr/bin/env python3
"""
GNS3 VLAN 交换机重构

将单一的 'date' 交换机替换为 3 个独立交换机, 实现真正的 VLAN 隔离:
  core-sw     (VLAN 10 核心面)   CR-1~6 NIC1 互联
  access1-sw  (VLAN 20 接入面1)  CR-1 NIC2 + AP-1 + TS
  access2-sw  (VLAN 30 接入面2)  CR-2 NIC2 + AP-2

交换机之间不能直接通信 — 必须通过 CR 的 AID↔RID 转发,
这正是标识网络的核心机制。

用法: python3 scripts/gns3_vlan_switches.py
"""

import json, sys, time, urllib.request, urllib.error

GNS3 = "http://192.168.80.222:3080/v2"
PROJECT_NAME = "identifier-network-sim"


def api(method, path, data=None):
    url = GNS3 + path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        content = resp.read()
        return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        print("  API %d on %s %s" % (e.code, method, path))
        return None


def get_project_id():
    projects = api("GET", "/projects") or []
    for p in projects:
        if p["name"] == PROJECT_NAME:
            return p["project_id"]
    return None


def get_nodes(pid):
    nodes = api("GET", "/projects/%s/nodes" % pid) or []
    return {n["name"]: n for n in nodes}


def delete_links_for_node(pid, node_id):
    links = api("GET", "/projects/%s/links" % pid) or []
    for l in links:
        nodes_in_l = l.get("nodes", [])
        for ln in nodes_in_l:
            if ln.get("node_id") == node_id:
                api("DELETE", "/projects/%s/links/%s" % (pid, l["link_id"]))
                break


def delete_node(pid, node_id):
    api("DELETE", "/projects/%s/nodes/%s" % (pid, node_id))


def create_switch(pid, name, x, y, ports=16):
    data = {"name": name, "node_type": "ethernet_switch",
            "compute_id": "local", "x": x, "y": y}
    return api("POST", "/projects/%s/nodes" % pid, data)


def create_link(pid, node1_id, nic1, node2_id, nic2):
    data = {"nodes": [
        {"node_id": node1_id, "adapter_number": nic1, "port_number": 0},
        {"node_id": node2_id, "adapter_number": nic2, "port_number": 0},
    ]}
    return api("POST", "/projects/%s/links" % pid, data)


def main():
    pid = get_project_id()
    if not pid:
        print("项目不存在")
        sys.exit(1)

    nodes = get_nodes(pid)
    node_ids = {name: n["node_id"] for name, n in nodes.items()}

    # 1. Delete old 'date' switch (and its links)
    if "date" in node_ids:
        print("删除旧 date 交换机...")
        delete_links_for_node(pid, node_ids["date"])
        delete_node(pid, node_ids["date"])

    # 2. Create 3 VLAN switches
    print("创建 VLAN 交换机...")
    switches = {}

    # core-sw: positioned between CRs, x=-100
    sw = create_switch(pid, "core-sw", -100, 350)
    if sw:
        switches["core-sw"] = sw["node_id"]
        print("  core-sw (VLAN10): %s" % sw["node_id"][:8])

    # access1-sw: near CR-1 access side, x=200
    sw = create_switch(pid, "access1-sw", 200, 50)
    if sw:
        switches["access1-sw"] = sw["node_id"]
        print("  access1-sw (VLAN20): %s" % sw["node_id"][:8])

    # access2-sw: near CR-2 access side, x=200
    sw = create_switch(pid, "access2-sw", 200, 650)
    if sw:
        switches["access2-sw"] = sw["node_id"]
        print("  access2-sw (VLAN30): %s" % sw["node_id"][:8])

    # 3. Re-link: Core switch (CR-1~6 NIC1)
    print("\n连线 core-sw (VLAN10 核心面)...")
    for i in range(1, 7):
        cr_name = "CR-%d" % i
        if cr_name in node_ids and "core-sw" in switches:
            create_link(pid, switches["core-sw"], 0, node_ids[cr_name], 1)
            print("  %s(NIC1) <-> core-sw" % cr_name)

    # 4. Re-link: Access1 switch (CR-1 NIC2 + AP-1 + TS)
    print("\n连线 access1-sw (VLAN20 接入面1)...")
    for dev, nic in [("CR-1", 2), ("AP-1", 0), ("TS", 0)]:
        if dev in node_ids and "access1-sw" in switches:
            create_link(pid, switches["access1-sw"], 0, node_ids[dev], nic)
            print("  %s(NIC%d) <-> access1-sw" % (dev, nic))

    # 5. Re-link: Access2 switch (CR-2 NIC2 + AP-2)
    print("\n连线 access2-sw (VLAN30 接入面2)...")
    for dev, nic in [("CR-2", 2), ("AP-2", 0)]:
        if dev in node_ids and "access2-sw" in switches:
            create_link(pid, switches["access2-sw"], 0, node_ids[dev], nic)
            print("  %s(NIC%d) <-> access2-sw" % (dev, nic))

    # 6. mgmt switch stays as-is (CS + CR management)
    print("\n✅ VLAN 交换机重构完成!")
    print("  core-sw:     CR-1~6 核心口互联 (RID 域)")
    print("  access1-sw:  CR-1接入 + AP-1 + TS (AID 域)")
    print("  access2-sw:  CR-2接入 + AP-2 (AID 域)")
    print("  mgmt:        CS + CR 管理口 (管理域)")
    print("\n验证: VLAN20 ↔ VLAN30 不通 (必须经 CR 转发)")
    print("F5 刷新 GUI 查看新拓扑")


if __name__ == "__main__":
    main()
