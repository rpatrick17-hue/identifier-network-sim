"""Copy clean access_point.py to AP-1 and AP-2 disks."""
import subprocess, time

SRC = "/home/ngit/identifier-network-sim/src/nodes/access_point.py"
DST = "/mnt/opt/identifier-network-sim/src/nodes/access_point.py"

for role in ["AP-1", "AP-2"]:
    disk = f"/home/ngit/GNS3/images/QEMU/alpine-{role}.qcow2"
    print(f"=== {role} ===")

    subprocess.run("pkill -9 qemu-nbd", shell=True)
    subprocess.run("umount -l /mnt", shell=True)
    time.sleep(2)

    r = subprocess.run(f"qemu-nbd --connect=/dev/nbd7 {disk}", shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"nbd fail: {r.stderr}")
        continue
    time.sleep(2)

    r = subprocess.run("mount /dev/nbd7p3 /mnt", shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"mount fail: {r.stderr}")
        continue

    r = subprocess.run(f"cp {SRC} {DST}", shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"cp fail: {r.stderr}")
    else:
        print("copied OK")

    subprocess.run("sync", shell=True)
    subprocess.run("umount /mnt", shell=True)
    subprocess.run("qemu-nbd --disconnect /dev/nbd7", shell=True)
    time.sleep(1)

# Delete overlays
import os, glob
proj = "/home/ngit/GNS3/projects/1de1ee86-50ca-47f7-b0f1-dc4009302f32/project-files/qemu"
for d in os.listdir(proj):
    f = f"{proj}/{d}/hda_disk.qcow2"
    if os.path.exists(f):
        r = subprocess.run(f"qemu-img info {f}", shell=True, capture_output=True, text=True)
        if "alpine-AP-1.qcow2" in r.stdout or "alpine-AP-2.qcow2" in r.stdout:
            os.remove(f)
            print(f"deleted overlay: {f}")

print("Done!")
