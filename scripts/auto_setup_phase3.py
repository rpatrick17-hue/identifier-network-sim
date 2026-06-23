"""Phase 3: Download project code into golden image via HTTP."""
import subprocess, time

DISK = "/home/ngit/GNS3/images/QEMU/alpine-base.qcow2"

print("Booting golden image...")
proc = subprocess.Popen(
    ["qemu-system-x86_64", "-m", "512",
     "-drive", f"file={DISK},if=virtio",
     "-nic", "user,model=virtio",
     "-display", "none", "-serial", "stdio", "-monitor", "none"],
    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL, text=True
)

time.sleep(20)
proc.stdin.write("root\n"); proc.stdin.flush()
time.sleep(2)

print("Configuring network...")
proc.stdin.write("udhcpc -i eth0\n"); proc.stdin.flush()
time.sleep(5)

print("Downloading project code from host (10.0.2.2:8765)...")
cmds = [
    "cd /opt/identifier-network-sim",
    "wget -q http://10.0.2.2:8765/project.tar.gz",
    "tar xzf project.tar.gz",
    "rm project.tar.gz",
    "ls -la",
    "ls src/ scripts/ config/ 2>/dev/null",
]
for cmd in cmds:
    proc.stdin.write(cmd + "\n"); proc.stdin.flush()
    time.sleep(2)

print("Verifying project structure...")
time.sleep(3)

print("Shutting down...")
proc.stdin.write("poweroff\n"); proc.stdin.flush()
time.sleep(10)
proc.terminate(); proc.wait(timeout=5)
print("Golden image complete with project code!")
