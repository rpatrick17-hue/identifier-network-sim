"""Fix all source disks: role.txt + qemu config. Run on Linux host."""
import subprocess, json, time, os, urllib.request

DEST = "/home/ngit/GNS3/images/QEMU"
PWD = "bjtungit\n"

def sudo(cmd):
    return subprocess.run(f"echo {PWD} | sudo -S bash -c '{cmd}'",
                         shell=True, capture_output=True, text=True, timeout=30)

def mount_disk(disk_path):
    sudo("modprobe nbd 2>/dev/null")
    sudo("qemu-nbd --disconnect /dev/nbd8 2>/dev/null")
    time.sleep(1)
    sudo(f"qemu-nbd --connect=/dev/nbd8 {disk_path}")
    time.sleep(2)
    sudo("mount /dev/nbd8p3 /mnt 2>/dev/null")

def unmount_disk():
    sudo("umount -l /mnt 2>/dev/null")
    sudo("qemu-nbd --disconnect /dev/nbd8 2>/dev/null")
    time.sleep(1)

def write_file(path, content):
    """Write content to file inside mounted disk at /mnt."""
    sudo(f"mkdir -p $(dirname {path})")
    # Use tee to write
    result = subprocess.run(
        f"echo {PWD} | sudo -S tee {path} > /dev/null",
        input=content, text=True, shell=True, capture_output=True, timeout=10)
    return result.returncode == 0

def verify(path):
    result = subprocess.run(f"cat {path}", shell=True, capture_output=True, text=True, timeout=5)
    return result.stdout.strip()

# Stop all GNS3 VMs
GNS3 = "http://localhost:3080/v2"
projects = json.loads(urllib.request.urlopen(GNS3 + "/projects").read())
pid = None
for p in projects:
    if p["name"] == "identifier-network-sim":
        pid = p["project_id"]
        break
nodes = json.loads(urllib.request.urlopen(GNS3 + f"/projects/{pid}/nodes").read())
for n in nodes:
    if n.get("status") == "started" and n["name"] != "template":
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"{GNS3}/projects/{pid}/nodes/{n['node_id']}/stop", method="POST"))
            print(f"Stopped: {n['name']}")
        except:
            pass

time.sleep(3)
sudo("pkill -9 qemu 2>/dev/null; pkill -9 qemu-nbd 2>/dev/null")
sudo("umount -l /mnt 2>/dev/null")
time.sleep(2)

# ---- Fix each disk ----
configs = {
    "CS": ("CS", """role: cs
interfaces:
  - name: eth0
    mac: "00:1a:2b:3c:4d:01"
cs_rid: [10028, 36181]
users:
  - { username: "Zhangsan", password: "123", pin: "1234", attributes: "UR:3;BW:10Mbps" }
  - { username: "Lisi", password: "Abc", pin: "0000", attributes: "UR:2;BW:5Mbps" }
managed_crs:
  - [10001, 36191]
  - [12360, 34280]
ap_to_cr:
  - [[10001, 36191], [10001, 36191]]
  - [[10002, 36192], [12360, 34280]]
"""),
}

cr_config_template = """role: cr
name: {name}
rid: {rid}
interfaces:
  - {{ name: eth0, mac: "{mgmt_mac}", type: ROUTE }}
  - {{ name: eth1, mac: "{core_mac}", type: ROUTE }}
  - {{ name: eth2, mac: "{acc_mac}", type: ACCESS }}
rid_spaces:
  - {{ id: 0, x: 10028, y: 36181, x_mask: 20, y_mask: 20, policy: MANAGEMENT }}
  - {{ id: 100, x: 12345, y: 34267, x_mask: 20, y_mask: 24, policy: DEFAULT }}
route_neighbors:
  - {{ space_id: 0, rid: [10028, 36181], mac: "00:1a:2b:3c:4d:01", interface: 0 }}
  - {{ space_id: 100, rid: {nhop}, mac: "{nhop_mac}", interface: 1 }}
rid_routes:
  - {{ space_id: 100, x: 12345, y: 34267, x_mask: 20, y_mask: 24, next_hop: {nhop} }}
local_mappings: []
remote_mappings: []
associated_aps: []
users: []
"""

cr_nodes = [
    ("CR-1", "[10001, 36191]", "[12360, 34280]", "00:18:54:fd:29:01", "00:0c:ab:1e:76:8a", "00:0c:ab:1e:76:8b", "00:0c:ab:1e:76:8c"),
    ("CR-2", "[12360, 34280]", "[10001, 36191]", "00:18:54:fd:29:02", "00:0c:ab:1e:76:8c", "00:0c:ab:1e:76:8d", "00:0c:ab:1e:76:8a"),
    ("CR-3", "[10030, 36190]", "[10001, 36191]", "00:18:54:fd:29:03", "00:0c:ab:1e:76:8a", "00:0c:ab:1e:76:8b", "00:0c:ab:1e:76:8a"),
    ("CR-4", "[12365, 34282]", "[12360, 34280]", "00:18:54:fd:29:04", "00:0c:ab:1e:76:8c", "00:0c:ab:1e:76:8d", "00:0c:ab:1e:76:8c"),
    ("CR-5", "[3540, 12768]",  "[10001, 36191]", "00:18:54:fd:29:05", "00:0c:ab:1e:76:8a", "00:0c:ab:1e:76:8b", "00:0c:ab:1e:76:8a"),
    ("CR-6", "[3545, 12770]",  "[10001, 36191]", "00:18:54:fd:29:06", "00:0c:ab:1e:76:8a", "00:0c:ab:1e:76:8b", "00:0c:ab:1e:76:8a"),
]

for name, rid, nhop, mgmt_mac, core_mac, acc_mac, nhop_mac in cr_nodes:
    print(f"Fixing {name}...")
    mount_disk(f"{DEST}/alpine-{name}.qcow2")
    write_file("/mnt/opt/identifier-network-sim/role.txt", name)
    cfg = cr_config_template.format(name=name, rid=rid, nhop=nhop,
                                     mgmt_mac=mgmt_mac, core_mac=core_mac,
                                     acc_mac=acc_mac, nhop_mac=nhop_mac)
    write_file(f"/mnt/opt/identifier-network-sim/config/qemu/{name}.yaml", cfg)
    r = verify("/mnt/opt/identifier-network-sim/role.txt")
    c = verify(f"/mnt/opt/identifier-network-sim/config/qemu/{name}.yaml")
    print(f"  {name}: role=[{r}] config={len(c)}chars")
    unmount_disk()

ts_config = """role: ts
interfaces:
  - name: eth0
    mac: "00:1a:2b:3c:4d:02"
aid: "d3c29a3a629280e686cf8d969eef6eca"
rid: [10003, 36193]
"""
print("Fixing TS...")
mount_disk(f"{DEST}/alpine-TS.qcow2")
write_file("/mnt/opt/identifier-network-sim/role.txt", "TS")
write_file("/mnt/opt/identifier-network-sim/config/qemu/TS.yaml", ts_config)
print(f"  TS: role=[{verify('/mnt/opt/identifier-network-sim/role.txt')}]")
unmount_disk()

ap_template = """role: ap
interfaces:
  - {{ name: eth0, mac: "{eth0_mac}" }}
  - {{ name: eth1, mac: "{eth1_mac}" }}
aid: "{aid}"
rid: {rid}
cs_rid: [10028, 36181]
cs_mac: "00:1a:2b:3c:4d:01"
cr_rid: {cr_rid}
cr_mac: "{cr_mac}"
local_users: []
"""
ap_nodes = [
    ("AP-1", "8d969eef6ecad3c29a3a629280e686cf", "[10001, 36191]", "[10001, 36191]", "00:04:ab:1f:40:a6", "00:0c:ab:1e:76:8a"),
    ("AP-2", "280e686cf8d969eef6ecad3c29a3a629", "[10002, 36192]", "[12360, 34280]", "00:05:dc:12:33:28", "00:0c:ab:1e:76:8c"),
]
for name, aid, rid, cr_rid, eth0_mac, cr_mac in ap_nodes:
    print(f"Fixing {name}...")
    mount_disk(f"{DEST}/alpine-{name}.qcow2")
    write_file("/mnt/opt/identifier-network-sim/role.txt", name)
    cfg = ap_template.format(aid=aid, rid=rid, cr_rid=cr_rid, eth0_mac=eth0_mac, eth1_mac="00:11:22:33:44:01", cr_mac=cr_mac)
    write_file(f"/mnt/opt/identifier-network-sim/config/qemu/{name}.yaml", cfg)
    print(f"  {name}: role=[{verify('/mnt/opt/identifier-network-sim/role.txt')}]")
    unmount_disk()

host_template = """role: host
interfaces:
  - name: eth0
    mac: "{mac}"
aid: "{aid}"
username: "{user}"
password: "{pw}"
ip: "{ip}"
ap_mac: "{ap_mac}"
target_aid: "d3c29a3a629280e686cf8d969eef6eca"
"""
host_nodes = [
    ("Host-1", "cad3c29a3a629280e686cf8d969eef6e", "Zhangsan", "123", "192.168.1.100", "00:04:ab:1f:40:a6", "00:11:22:33:44:01"),
    ("Host-2", "969eef6ecad3c29a3a629280e686cf8d", "Lisi", "Abc", "192.168.2.100", "00:05:dc:12:33:28", "00:11:22:33:44:02"),
]
for name, aid, user, pw, ip, ap_mac, mac in host_nodes:
    print(f"Fixing {name}...")
    mount_disk(f"{DEST}/alpine-{name}.qcow2")
    write_file("/mnt/opt/identifier-network-sim/role.txt", name)
    cfg = host_template.format(aid=aid, user=user, pw=pw, ip=ip, ap_mac=ap_mac, mac=mac)
    write_file(f"/mnt/opt/identifier-network-sim/config/qemu/{name}.yaml", cfg)
    print(f"  {name}: role=[{verify('/mnt/opt/identifier-network-sim/role.txt')}]")
    unmount_disk()

# Delete overlays
print("Deleting GNS3 overlays...")
overlay_dir = "/home/ngit/GNS3/projects/1de1ee86-50ca-47f7-b0f1-dc4009302f32/project-files/qemu"
for d in os.listdir(overlay_dir):
    if d == "44aa24dc-f0a0-4577-aa52-6afc2dfea68c":
        continue
    f = f"{overlay_dir}/{d}/hda_disk.qcow2"
    if os.path.exists(f):
        sudo(f"rm -f {f}")
        print(f"  deleted: {d}")

print("\nAll done! Start CR-1 to test.")
