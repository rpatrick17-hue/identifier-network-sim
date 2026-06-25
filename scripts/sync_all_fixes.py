"""Sync signaling.py, core_router.py, control_server.py to VM source disks."""
import subprocess, time, os, json, urllib.request

DISKS = {
    "/home/ngit/GNS3/images/QEMU/alpine-CS.qcow2":   ["control_server.py", "signaling.py"],
    "/home/ngit/GNS3/images/QEMU/alpine-CR-1.qcow2": ["core_router.py", "signaling.py"],
    "/home/ngit/GNS3/images/QEMU/alpine-CR-2.qcow2": ["core_router.py", "signaling.py"],
}
SRC_BASE = "/home/ngit/identifier-network-sim/src"
FILE_MAP = {
    "core_router.py":    "nodes/core_router.py",
    "signaling.py":      "control_plane/signaling.py",
    "control_server.py": "nodes/control_server.py",
}

# Stop all via API
GNS3 = "http://localhost:3080/v2"
projects = json.loads(urllib.request.urlopen(GNS3 + "/projects").read())
pid = [p["project_id"] for p in projects if p["name"] == "identifier-network-sim"][0]
nodes = json.loads(urllib.request.urlopen(GNS3 + f"/projects/{pid}/nodes").read())
for n in nodes:
    if n.get("status") == "started":
        try: urllib.request.urlopen(urllib.request.Request(
            f"{GNS3}/projects/{pid}/nodes/{n['node_id']}/stop", method="POST"))
        except: pass
time.sleep(3)

subprocess.run("pkill -9 qemu-nbd 2>/dev/null", shell=True)
subprocess.run("umount -l /mnt 2>/dev/null", shell=True)
time.sleep(2)

for disk, files in DISKS.items():
    name = os.path.basename(disk).replace("alpine-","").replace(".qcow2","")
    print(f"=== {name} ===")

    r = subprocess.run(f"qemu-nbd --connect=/dev/nbd7 {disk}", shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  nbd fail: {r.stderr}"); continue
    time.sleep(2)

    r = subprocess.run("mount /dev/nbd7p3 /mnt", shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  mount fail: {r.stderr}")
        subprocess.run("qemu-nbd --disconnect /dev/nbd7", shell=True); continue

    for fname in files:
        src = f"{SRC_BASE}/{FILE_MAP[fname]}"
        dst = f"/mnt/opt/identifier-network-sim/src/{FILE_MAP[fname]}"
        if os.path.exists(src) and os.path.exists(os.path.dirname(dst)):
            subprocess.run(f"cp {src} {dst}", shell=True, check=True)
            print(f"  copied {fname}")
        else:
            print(f"  skip {fname} (src={os.path.exists(src)} dst_dir={os.path.exists(os.path.dirname(dst))})")

    subprocess.run("sync", shell=True)
    subprocess.run("umount /mnt", shell=True)
    subprocess.run("qemu-nbd --disconnect /dev/nbd7", shell=True)
    time.sleep(1)

# Delete overlays
proj = "/home/ngit/GNS3/projects/1de1ee86-50ca-47f7-b0f1-dc4009302f32/project-files/qemu"
for d in os.listdir(proj):
    f = f"{proj}/{d}/hda_disk.qcow2"
    if os.path.exists(f):
        r = subprocess.run(f"qemu-img info {f}", shell=True, capture_output=True, text=True)
        if "alpine-CS.qcow2" in r.stdout or "alpine-CR-1.qcow2" in r.stdout or "alpine-CR-2.qcow2" in r.stdout:
            os.remove(f); print(f"Deleted overlay: {d}")

print("Done! Restart CS, CR-1, CR-2.")
