"""Fix CR-1 disk: role.txt + config + core_router.py + overlay delete."""
import subprocess, time, os, json, urllib.request

DISK = "/home/ngit/GNS3/images/QEMU/alpine-CR-1.qcow2"
SRC_PY = "/home/ngit/identifier-network-sim/src/nodes/core_router.py"

# Stop CR-1
GNS3 = "http://localhost:3080/v2"
projects = json.loads(urllib.request.urlopen(GNS3 + "/projects").read())
pid = [p["project_id"] for p in projects if p["name"] == "identifier-network-sim"][0]
nodes = json.loads(urllib.request.urlopen(GNS3 + f"/projects/{pid}/nodes").read())
for n in nodes:
    if n["name"] == "CR-1" and n.get("status") == "started":
        urllib.request.urlopen(urllib.request.Request(
            f"{GNS3}/projects/{pid}/nodes/{n['node_id']}/stop", method="POST"))
time.sleep(3)

subprocess.run("pkill -9 qemu-nbd 2>/dev/null", shell=True)
subprocess.run("umount -l /mnt 2>/dev/null", shell=True)
time.sleep(2)

r = subprocess.run(f"qemu-nbd --connect=/dev/nbd7 {DISK}", shell=True, capture_output=True, text=True)
if r.returncode != 0: print(f"nbd fail: {r.stderr}"); exit(1)
time.sleep(2)
r = subprocess.run("mount /dev/nbd7p3 /mnt", shell=True, capture_output=True, text=True)
if r.returncode != 0: print(f"mount fail: {r.stderr}"); exit(1)

# Fix role.txt
with open("/mnt/opt/identifier-network-sim/role.txt", "w") as f: f.write("CR-1")
print(f"role.txt: {open('/mnt/opt/identifier-network-sim/role.txt').read().strip()}")

# Fix core_router.py
subprocess.run(f"cp {SRC_PY} /mnt/opt/identifier-network-sim/src/nodes/core_router.py", shell=True, check=True)

# Create config
os.makedirs("/mnt/opt/identifier-network-sim/config/qemu", exist_ok=True)
with open("/mnt/opt/identifier-network-sim/config/qemu/CR-1.yaml", "w") as f:
    f.write("""role: cr
name: CR-1
rid: [10001, 36191]
interfaces:
  - { name: eth0, mac: "0c:83:3f:e7:00:00", type: ROUTE }
  - { name: eth1, mac: "0c:83:3f:e7:00:01", type: ROUTE }
  - { name: eth2, mac: "0c:83:3f:e7:00:02", type: ACCESS }
rid_spaces:
  - { id: 0, x: 10028, y: 36181, x_mask: 20, y_mask: 20, policy: MANAGEMENT }
  - { id: 100, x: 12345, y: 34267, x_mask: 20, y_mask: 24, policy: DEFAULT }
route_neighbors:
  - { space_id: 0, rid: [10028, 36181], mac: "0c:fe:b7:7e:00:00", interface: 0 }
  - { space_id: 100, rid: [12360, 34280], mac: "0c:f1:d6:e0:00:01", interface: 1 }
access_neighbors:
  - { aid: "8d969eef6ecad3c29a3a629280e686cf", mac: "0c:81:a4:ac:00:00", interface: 2 }
  - { aid: "d3c29a3a629280e686cf8d969eef6eca", mac: "0c:82:f0:18:00:00", interface: 2 }
rid_routes:
  - { space_id: 100, x: 12345, y: 34267, x_mask: 20, y_mask: 24, next_hop: [12360, 34280] }
local_mappings:
  - { aid: "8d969eef6ecad3c29a3a629280e686cf", rid: [10011, 36191], space_id: 0 }
  - { aid: "f503a6c941bfce5afac32bb655dc1307", rid: [10001, 36191], space_id: 100 }
  - { aid: "d3c29a3a629280e686cf8d969eef6eca", rid: [10003, 36193], space_id: 100 }
remote_mappings:
  - { aid: "761bae2ffecae1a8785c6c25680329d8", mapped_rid: [12360, 34280], remote_cr: [12360, 34280], space_id: 100 }
associated_aps:
  - { aid: "8d969eef6ecad3c29a3a629280e686cf", rid: [10011, 36191], interface: 2 }
users: []
""")
print("config created")

subprocess.run("sync", shell=True)
subprocess.run("umount /mnt", shell=True)
subprocess.run("qemu-nbd --disconnect /dev/nbd7", shell=True)

# Delete overlay
proj = "/home/ngit/GNS3/projects/1de1ee86-50ca-47f7-b0f1-dc4009302f32/project-files/qemu"
for d in os.listdir(proj):
    f = f"{proj}/{d}/hda_disk.qcow2"
    if os.path.exists(f):
        r = subprocess.run(f"qemu-img info {f}", shell=True, capture_output=True, text=True)
        if "alpine-CR-1.qcow2" in r.stdout:
            os.remove(f); print(f"Deleted overlay")

print("Done! Restart CR-1.")
