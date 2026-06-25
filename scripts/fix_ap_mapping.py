"""Fix mapped_rid in AP disks."""
import os, subprocess, time

PWD = "bjtungit"
OLD = b"mapped_rid = RID(user_aid.value >> 64 & 0xFFFFFFFF, user_aid.value & 0xFFFFFFFF)"
NEW = b"mapped_rid = self.cr_rid or RID(user_aid.value >> 64 & 0xFFFFFFFF, user_aid.value & 0xFFFFFFFF)"

for role in ["AP-1", "AP-2"]:
    disk = f"/home/ngit/GNS3/images/QEMU/alpine-{role}.qcow2"
    print(f"=== {role} ===")

    # Connect
    subprocess.run(f"echo {PWD} | sudo -S qemu-nbd --disconnect /dev/nbd7", shell=True, capture_output=True)
    subprocess.run(f"echo {PWD} | sudo -S umount -l /mnt", shell=True, capture_output=True)
    time.sleep(1)

    r = subprocess.run(f"echo {PWD} | sudo -S qemu-nbd --connect=/dev/nbd7 {disk}",
                       shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  nbd failed: {r.stderr}")
        continue
    time.sleep(2)

    r = subprocess.run(f"echo {PWD} | sudo -S mount /dev/nbd7p3 /mnt",
                       shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  mount failed: {r.stderr}")
        continue

    fpath = "/mnt/opt/identifier-network-sim/src/nodes/access_point.py"
    if not os.path.exists(fpath):
        print(f"  file not found: {fpath}")
    else:
        with open(fpath, "rb") as f:
            content = f.read()
        count = content.count(OLD)
        content = content.replace(OLD, NEW)
        with open(fpath, "wb") as f:
            f.write(content)
        print(f"  replaced {count} occurrences")

    subprocess.run("sync", shell=True)
    subprocess.run(f"echo {PWD} | sudo -S umount /mnt", shell=True, capture_output=True)
    subprocess.run(f"echo {PWD} | sudo -S qemu-nbd --disconnect /dev/nbd7", shell=True, capture_output=True)
    time.sleep(1)

print("Done!")
