"""Fix CR-1 role.txt on source disk."""
import subprocess, time, os, json, urllib.request

DISK = "/home/ngit/GNS3/images/QEMU/alpine-CR-1.qcow2"

# Stop CR-1
GNS3 = "http://localhost:3080/v2"
projects = json.loads(urllib.request.urlopen(GNS3 + "/projects").read())
pid = [p["project_id"] for p in projects if p["name"] == "identifier-network-sim"][0]
nodes = json.loads(urllib.request.urlopen(GNS3 + f"/projects/{pid}/nodes").read())
for n in nodes:
    if n["name"] == "CR-1" and n.get("status") == "started":
        urllib.request.urlopen(urllib.request.Request(
            f"{GNS3}/projects/{pid}/nodes/{n['node_id']}/stop", method="POST"))
        print("Stopped CR-1")
time.sleep(3)

subprocess.run("pkill -9 qemu-nbd 2>/dev/null", shell=True)
subprocess.run("umount -l /mnt 2>/dev/null", shell=True)
time.sleep(2)

r = subprocess.run(f"qemu-nbd --connect=/dev/nbd7 {DISK}", shell=True, capture_output=True, text=True)
if r.returncode != 0:
    print(f"nbd fail: {r.stderr}"); exit(1)
time.sleep(2)

r = subprocess.run("mount /dev/nbd7p3 /mnt", shell=True, capture_output=True, text=True)
if r.returncode != 0:
    print(f"mount fail: {r.stderr}"); exit(1)

path = "/mnt/opt/identifier-network-sim/role.txt"
with open(path, "w") as f:
    f.write("CR-1")
print(f"Fixed role.txt: {open(path).read().strip()}")

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

print("Done!")
