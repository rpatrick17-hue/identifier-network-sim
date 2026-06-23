"""Phase 2: Boot from disk, install Python + project code."""
import subprocess, time

DISK = "/home/ngit/GNS3/images/QEMU/alpine-base.qcow2"
PROJ = "/home/ngit/identifier-network-sim"

print("Booting from disk (no ISO)...")
proc = subprocess.Popen(
    ["qemu-system-x86_64", "-m", "512",
     "-drive", f"file={DISK},if=virtio",
     "-nic", "user,model=virtio,hostfwd=tcp::2223-:22",
     "-display", "none", "-serial", "stdio", "-monitor", "none"],
    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL, text=True
)

time.sleep(20)
print("Login root...")
proc.stdin.write("root\n"); proc.stdin.flush()
time.sleep(2)

print("Setup network + install Python...")
cmds = [
    "udhcpc -i eth0",
    "sleep 3",
    "cat > /etc/apk/repositories << EOF",
    "https://dl-cdn.alpinelinux.org/alpine/v3.21/main",
    "https://dl-cdn.alpinelinux.org/alpine/v3.21/community",
    "EOF",
    "apk update",
    "apk add python3 py3-pip",
    "pip3 install loguru prometheus_client PyYAML",
]
for cmd in cmds:
    proc.stdin.write(cmd + "\n"); proc.stdin.flush()
    print(f"  -> {cmd}")
    time.sleep(3)

time.sleep(20)

print("Create startup script + project dir...")
cmds2 = [
    "mkdir -p /opt/identifier-network-sim",
    "cat > /etc/local.d/start.start << 'INIT'",
    "#!/bin/sh",
    "ROLE=$(cat /opt/identifier-network-sim/role.txt 2>/dev/null)",
    "if [ -n \"$ROLE\" ]; then",
    "  cd /opt/identifier-network-sim",
    "  python3 scripts/real_deploy.py --role \"$ROLE\" --config config/qemu/\"$ROLE\".yaml > /var/log/id-net.log 2>&1 &",
    "fi",
    "INIT",
    "chmod +x /etc/local.d/start.start",
    "rc-update add local",
]
for cmd in cmds2:
    proc.stdin.write(cmd + "\n"); proc.stdin.flush()
    print(f"  -> {cmd}")
    time.sleep(1)

time.sleep(3)
print("Poweroff...")
proc.stdin.write("poweroff\n"); proc.stdin.flush()
time.sleep(10)
proc.terminate(); proc.wait(timeout=5)
print("Golden image ready!")
print(DISK)
