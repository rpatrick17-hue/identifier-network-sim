"""Topology builder – reads YAML configs and wires up all nodes.

Produces a fully-connected simulation graph with:
    - 6 Core Routers (mesh on the core side)
    - 2+ Access Points (connected to CRs via access switches)
    - 1 Control Server (connected via management switch)
    - 1 Test Server (connected via data switch)
    - 2 Hosts (connected to APs)
    - 2 VirtualSwitches (management + data with port isolation)
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from ..common.addressing import AID, RID, RIDSpace
from ..common.constants import InterfaceType, SpacePolicy
from ..common.utils import generate_aid
from ..nodes.access_point import AccessPoint
from ..nodes.base_node import BaseNode
from ..nodes.control_server import ControlServer
from ..nodes.core_router import CoreRouter
from ..nodes.host import Host
from ..nodes.test_server import TestServer
from ..simulation.virtual_link import VirtualLink, VirtualSwitch


class Topology:
    """Holds all simulation nodes and links."""

    def __init__(self):
        self.nodes: Dict[str, BaseNode] = {}
        self.core_routers: Dict[str, CoreRouter] = {}
        self.access_points: Dict[str, AccessPoint] = {}
        self.control_server: Optional[ControlServer] = None
        self.test_server: Optional[TestServer] = None
        self.hosts: Dict[str, Host] = {}
        self.switches: Dict[str, VirtualSwitch] = {}
        self.links: List[VirtualLink] = []

    # ==================================================================
    #  Build from config
    # ==================================================================

    @classmethod
    def from_yaml(cls, config_path: str | Path) -> Topology:
        """Build the full topology from a YAML configuration file."""
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        topo = cls()

        # -- 1. Create switches -------------------------------------------------
        topo._create_switches(cfg.get("switches", {}))

        # -- 2. Create nodes ---------------------------------------------------
        topo._create_nodes(cfg.get("nodes", {}))

        # -- 3. Wire connections -----------------------------------------------
        topo._wire_connections(cfg.get("connections", []))

        return topo

    def _create_switches(self, sw_cfg: dict) -> None:
        for name, sc in sw_cfg.items():
            sw = VirtualSwitch(name=name)
            self.switches[name] = sw

            # Configure isolation groups
            for group in sc.get("isolation_groups", []):
                sw.set_isolation_group(
                    group.get("id", 0),
                    group.get("ports", []),
                )

    def _create_nodes(self, nodes_cfg: dict) -> None:
        # CRs
        for cr_cfg in nodes_cfg.get("core_routers", []):
            cr = CoreRouter(name=cr_cfg["name"])
            cr.my_rid = RID.from_tuple(tuple(cr_cfg["rid"])) if cr_cfg.get("rid") else None

            # Interfaces
            for iface_cfg in cr_cfg.get("interfaces", []):
                idx = cr.add_interface(
                    name=iface_cfg["name"],
                    mac=iface_cfg["mac"],
                    if_type=InterfaceType[iface_cfg.get("type", "ACCESS")],
                )
                cr.configure_interface(
                    idx, iface_cfg["name"], iface_cfg["mac"],
                    InterfaceType[iface_cfg.get("type", "ACCESS")],
                )

            # RID spaces
            for space_cfg in cr_cfg.get("rid_spaces", []):
                cr.add_rid_space(
                    space_cfg["id"],
                    RIDSpace(
                        x=space_cfg["x"],
                        y=space_cfg["y"],
                        x_mask_bits=space_cfg.get("x_mask", 20),
                        y_mask_bits=space_cfg.get("y_mask", 20),
                    ),
                    SpacePolicy[space_cfg.get("policy", "DEFAULT")],
                )

            # RID routes (static config)
            for route_cfg in cr_cfg.get("rid_routes", []):
                cr.add_rid_route(
                    space_id=route_cfg["space_id"],
                    x=route_cfg["x"], y=route_cfg["y"],
                    x_mask=route_cfg.get("x_mask", 20),
                    y_mask=route_cfg.get("y_mask", 20),
                    next_hop=RID.from_tuple(tuple(route_cfg["next_hop"])),
                )

            # AID routes
            for route_cfg in cr_cfg.get("aid_routes", []):
                cr.add_aid_route(
                    dst_aid=AID.from_hex(route_cfg["dst_aid"]),
                    next_hop_aid=AID.from_hex(route_cfg["next_hop"]),
                )

            # Associated APs
            for ap_cfg in cr_cfg.get("associated_aps", []):
                cr.add_associated_ap(
                    ap_aid=AID.from_hex(ap_cfg["aid"]),
                    ap_rid=RID.from_tuple(tuple(ap_cfg["rid"])),
                    iface_idx=ap_cfg.get("interface", 0),
                )

            # Local mappings
            for map_cfg in cr_cfg.get("local_mappings", []):
                cr.add_local_mapping(
                    aid=AID.from_hex(map_cfg["aid"]),
                    rid=RID.from_tuple(tuple(map_cfg["rid"])),
                    space_id=map_cfg.get("space_id", 0),
                )

            # Users
            for user_cfg in cr_cfg.get("users", []):
                from ..common.constants import UserStatus
                cr.set_user_status(
                    user_aid=AID.from_hex(user_cfg["aid"]),
                    ap_aid=AID.from_hex(user_cfg.get("ap_aid", "0" * 32)),
                    status=UserStatus[user_cfg.get("status", "ONLINE")],
                    attrs=user_cfg.get("attributes", ""),
                )

            self.core_routers[cr.name] = cr
            self.nodes[cr.name] = cr

        # CS
        cs_cfg = nodes_cfg.get("control_server")
        if cs_cfg:
            cs = ControlServer(name=cs_cfg["name"])
            cs.rid = RID.from_tuple(tuple(cs_cfg["rid"])) if cs_cfg.get("rid") else None
            for iface_cfg in cs_cfg.get("interfaces", []):
                cs.add_interface(iface_cfg["name"], iface_cfg["mac"], InterfaceType.ROUTE)
            # Pre-register users
            for user_cfg in cs_cfg.get("pre_registered_users", []):
                cs.register_user(
                    username=user_cfg["username"],
                    password=user_cfg["password"],
                    pin=user_cfg.get("pin", "0000"),
                    custom_attributes=user_cfg.get("attributes", ""),
                )
            self.control_server = cs
            self.nodes[cs.name] = cs

        # APs
        for ap_cfg in nodes_cfg.get("access_points", []):
            ap = AccessPoint(name=ap_cfg["name"])
            ap.aid = AID.from_hex(ap_cfg["aid"]) if ap_cfg.get("aid") else None
            ap.rid = RID.from_tuple(tuple(ap_cfg["rid"])) if ap_cfg.get("rid") else None
            ap.cs_rid = RID.from_tuple(tuple(ap_cfg["cs_rid"])) if ap_cfg.get("cs_rid") else None
            ap.cr_rid = RID.from_tuple(tuple(ap_cfg["cr_rid"])) if ap_cfg.get("cr_rid") else None
            ap.ssid = ap_cfg.get("ssid", "ID-Network")
            ap.frequency = ap_cfg.get("frequency", "2.4GHz")
            ap.ip_subnet = ap_cfg.get("ip_subnet", "192.168.1.0/24")
            for iface_cfg in ap_cfg.get("interfaces", []):
                ap.add_interface(iface_cfg["name"], iface_cfg["mac"], InterfaceType.ACCESS)
            ap._access_iface = ap_cfg.get("access_iface", 0)
            ap._cr_iface = ap_cfg.get("cr_iface", 0)
            self.access_points[ap.name] = ap
            self.nodes[ap.name] = ap

        # Test server
        ts_cfg = nodes_cfg.get("test_server")
        if ts_cfg:
            ts = TestServer(name=ts_cfg["name"])
            ts.aid = AID.from_hex(ts_cfg["aid"]) if ts_cfg.get("aid") else None
            ts.rid = RID.from_tuple(tuple(ts_cfg["rid"])) if ts_cfg.get("rid") else None
            for iface_cfg in ts_cfg.get("interfaces", []):
                ts.add_interface(iface_cfg["name"], iface_cfg["mac"], InterfaceType.ACCESS)
            self.test_server = ts
            self.nodes[ts.name] = ts

        # Hosts
        for host_cfg in nodes_cfg.get("hosts", []):
            host = Host(name=host_cfg["name"])
            host.ip_address = host_cfg.get("ip", "192.168.1.100")
            host.ip_netmask = host_cfg.get("netmask", "255.255.255.0")
            host.ip_gateway = host_cfg.get("gateway", "192.168.1.1")
            host._ap_mac = host_cfg.get("ap_mac", "")
            if host_cfg.get("aid"):
                host.load_aid_config(
                    host_cfg["aid"],
                    host_cfg.get("username", ""),
                    host_cfg.get("password", ""),
                )
            for iface_cfg in host_cfg.get("interfaces", []):
                host.add_interface(iface_cfg["name"], iface_cfg["mac"], InterfaceType.ACCESS)
            self.hosts[host.name] = host
            self.nodes[host.name] = host

    def _wire_connections(self, conns: list) -> None:
        """Wire node interfaces to switches."""
        for conn in conns:
            node_name = conn["node"]
            iface_idx = conn["interface"]
            switch_name = conn["switch"]
            port = conn["port"]

            node = self.nodes.get(node_name)
            sw = self.switches.get(switch_name)
            if node is None or sw is None:
                continue

            node.connect_switch(iface_idx, sw, port)

    # ==================================================================
    #  Query helpers
    # ==================================================================

    def get_cr(self, name: str) -> CoreRouter:
        return self.core_routers[name]

    def get_ap(self, name: str) -> AccessPoint:
        return self.access_points[name]

    def list_nodes(self) -> List[str]:
        return list(self.nodes.keys())

    def summary(self) -> str:
        lines = [
            f"Topology: {len(self.nodes)} nodes",
            f"  CRs:  {list(self.core_routers.keys())}",
            f"  APs:  {list(self.access_points.keys())}",
            f"  CS:   {self.control_server.name if self.control_server else 'N/A'}",
            f"  TS:   {self.test_server.name if self.test_server else 'N/A'}",
            f"  Hosts: {list(self.hosts.keys())}",
            f"  Switches: {list(self.switches.keys())}",
        ]
        return "\n".join(lines)
