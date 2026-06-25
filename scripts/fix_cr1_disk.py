"""Copy clean core_router.py to CR-1 disk."""
import subprocess, time, os

DISK = "/home/ngit/GNS3/images/QEMU/alpine-CR-1.qcow2"
SRC = "/home/ngit/identifier-network-sim/src/nodes/core_router.py"
DST = "/mnt/opt/identifier-network-sim/src/nodes/core_router.py"

# Stop CR-1 via GNS3 API
import json, urllib.request
GNS3 = "http://localhost:3080/v2"
projects = json.loads(urllib.request.urlopen(GNS3 + "/projects").read())
pid = [p["project_id"] for p in projects if p["name"] == "identifier-network-sim"][0]
nodes = json.loads(urllib.request.urlopen(GNS3 + f"/projects/{pid}/nodes").read())
for n in nodes:
    if n["name"] == "CR-1" and n.get("status") == "started":
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"{GNS3}/projects/{pid}/nodes/{n['node_id']}/stop", method="POST"))
            print("Stopped CR-1")
        except:
            pass
time.sleep(3)

# Kill stale
subprocess.run("pkill -9 qemu-system 2>/dev/null", shell=True)
subprocess.run("pkill -9 qemu-nbd 2>/dev/null", shell=True)
subprocess.run("umount -l /mnt 2>/dev/null", shell=True)
time.sleep(2)

# Connect disk
r = subprocess.run(f"qemu-nbd --connect=/dev/nbd7 {DISK}", shell=True, capture_output=True, text=True)
if r.returncode != 0:
    print(f"nbd fail: {r.stderr}")
    exit(1)
time.sleep(2)

r = subprocess.run("mount /dev/nbd7p3 /mnt", shell=True, capture_output=True, text=True)
if r.returncode != 0:
    print(f"mount fail: {r.stderr}")
    subprocess.run("qemu-nbd --disconnect /dev/nbd7", shell=True)
    exit(1)

# Copy file
if os.path.exists(DST):
    subprocess.run(f"cp {SRC} {DST}", shell=True, check=True)
    print("Copied OK")
    subprocess.run(f"grep 'Branch 0.5' {DST}", shell=True)

subprocess.run("sync", shell=True)
subprocess.run("umount /mnt", shell=True)
subprocess.run("qemu-nbd --disconnect /dev/nbd7", shell=True)

# Delete CR-1 overlay
proj = "/home/ngit/GNS3/projects/1de1ee86-50ca-47f7-b0f1-dc4009302f32/project-files/qemu"
for d in os.listdir(proj):
    f = f"{proj}/{d}/hda_disk.qcow2"
    if os.path.exists(f):
        r = subprocess.run(f"qemu-img info {f}", shell=True, capture_output=True, text=True)
        if "alpine-CR-1.qcow2" in r.stdout:
            os.remove(f)
            print(f"Deleted overlay: {f}")

print("Done! Restart CR-1.")
