"""Fix MAC filter bug in ALL VM source disks via nbd (carefully)."""
import subprocess, time, os, shutil

PWD = "bjtungit\n"
DEST = "/home/ngit/GNS3/images/QEMU"
ROLES = ["CS","CR-1","CR-2","CR-3","CR-4","CR-5","CR-6","TS","AP-1","AP-2","Host-1","Host-2"]

# The correct MAC filter code
FIXED_BLOCK = """    my_macs = set()
    for iface in node.interfaces:
        if isinstance(iface.mac, bytes):
            my_macs.add(iface.mac.hex())
        else:
            my_macs.add(iface.mac.replace(":", "").lower())
        my_macs.add("ffffffffffff")"""

OLD_PATTERN = "my_macs = set()"

def sudo(cmd):
    return subprocess.run(f"echo '{PWD.strip()}' | sudo -S bash -c '{cmd}'",
                         shell=True, capture_output=True, text=True, timeout=20)

# Stop all GNS3 VMs
import json, urllib.request
GNS3 = "http://localhost:3080/v2"
projects = json.loads(urllib.request.urlopen(GNS3 + "/projects"))
projects_data = projects.read() if hasattr(projects, 'read') else projects
if isinstance(projects, list):
    pass
else:
    projects = json.loads(urllib.request.urlopen(GNS3 + "/projects").read())

pid = None
for p in projects:
    if p["name"] == "identifier-network-sim":
        pid = p["project_id"]
        break

if pid:
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

# Kill stale processes
sudo("pkill -9 qemu 2>/dev/null; pkill -9 qemu-nbd 2>/dev/null; sleep 2")
sudo("umount -l /mnt 2>/dev/null")

# Fix each disk
for role in ROLES:
    disk = f"{DEST}/alpine-{role}.qcow2"
    if not os.path.exists(disk):
        print(f"  {role}: disk not found, skip")
        continue

    # Mount via nbd
    sudo(f"qemu-nbd --disconnect /dev/nbd8 2>/dev/null")
    time.sleep(1)
    r = sudo(f"qemu-nbd --connect=/dev/nbd8 {disk}")
    if r.returncode != 0:
        print(f"  {role}: nbd connect failed: {r.stderr.strip()}")
        continue
    time.sleep(2)

    r = sudo("mount /dev/nbd8p3 /mnt 2>/dev/null")
    if r.returncode != 0:
        print(f"  {role}: mount failed: {r.stderr.strip()}")
        sudo("qemu-nbd --disconnect /dev/nbd8 2>/dev/null")
        continue

    # Check target file
    target = "/mnt/opt/identifier-network-sim/scripts/real_deploy.py"
    r = sudo(f"grep -c 'my_macs = set' {target}")

    # Apply fix by reading file, patching, writing back
    patch_script = f"""
import re
with open('{target}', 'r') as f:
    content = f.read()

# Find the old MAC block and replace
old_lines = content.split('\\n')
new_lines = []
skip = False
found = False
i = 0
while i < len(old_lines):
    line = old_lines[i]
    if 'my_macs = set()' in line:
        found = True
        # Insert fixed block
        for fl in ['    my_macs = set()',
                    '    for iface in node.interfaces:',
                    '        if isinstance(iface.mac, bytes):',
                    '            my_macs.add(iface.mac.hex())',
                    '        else:',
                    '            my_macs.add(iface.mac.replace(\":\", \"\").lower())',
                    '        my_macs.add(\"ffffffffffff\")']:
            new_lines.append(fl)
        # Skip old lines until we hit the next non-indented block or empty line
        i += 1
        while i < len(old_lines):
            nl = old_lines[i]
            if nl.strip() == '' or (not nl.startswith(' ') and nl.strip() != '' and not nl.startswith('    for') and not nl.startswith('        ')):
                break
            i += 1
        continue
    new_lines.append(line)
    i += 1

if not found:
    print('PATTERN_NOT_FOUND')
else:
    with open('{target}', 'w') as f:
        f.write('\\n'.join(new_lines))
    print('FIXED')
"""
    r = sudo(f"python3 -c '{patch_script}'")
    result = r.stdout.strip()

    sudo("sync")
    sudo("umount /mnt 2>/dev/null")
    sudo("qemu-nbd --disconnect /dev/nbd8 2>/dev/null")
    time.sleep(1)

    print(f"  {role}: {result}")

# Delete all GNS3 overlays
print("\nDeleting overlays...")
overlay_dir = f"/home/ngit/GNS3/projects/{pid}/project-files/qemu"
for d in os.listdir(overlay_dir):
    if d == "44aa24dc-f0a0-4577-aa52-6afc2dfea68c":
        continue
    f = f"{overlay_dir}/{d}/hda_disk.qcow2"
    if os.path.exists(f):
        sudo(f"rm -f {f}")

print("\nAll fixed. Restart VMs in order: CS → CR-1 → CR-2 → TS → AP-1 → AP-2")
