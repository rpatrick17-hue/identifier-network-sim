"""Phase 1: Boot Alpine ISO, auto-install to disk."""
import subprocess, time

DISK = "/home/ngit/GNS3/images/QEMU/alpine-base.qcow2"
ISO  = "/home/ngit/GNS3/images/QEMU/alpine-virt-3.21.3-x86_64.iso"

print("Booting Alpine ISO...")
proc = subprocess.Popen(
    ["qemu-system-x86_64", "-m", "512",
     "-drive", f"file={DISK},if=virtio",
     "-cdrom", ISO, "-boot", "d",
     "-nic", "user,model=virtio",
     "-display", "none", "-serial", "stdio", "-monitor", "none", "-no-reboot"],
    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL, text=True
)

# Wait for boot - press Enter at boot prompt, then wait for login
time.sleep(5)
proc.stdin.write("\n"); proc.stdin.flush()  # Press Enter at ISOLINUX boot prompt
time.sleep(35)

print("Login root...")
proc.stdin.write("root\n"); proc.stdin.flush()
time.sleep(3)

print("Setup network + install grub + run setup-disk...")
cmds = [
    "udhcpc -i eth0",
    "sleep 3",
    "cat > /etc/apk/repositories << EOF",
    "https://dl-cdn.alpinelinux.org/alpine/v3.21/main",
    "https://dl-cdn.alpinelinux.org/alpine/v3.21/community",
    "EOF",
    "apk update",
    "apk add grub grub-bios",
    "BOOTLOADER=grub setup-disk -m sys /dev/sda",
]
for cmd in cmds:
    proc.stdin.write(cmd + "\n"); proc.stdin.flush()
    print(f"  -> {cmd}")
    time.sleep(3)

time.sleep(5)
proc.stdin.write("y\n"); proc.stdin.flush()
print("  -> y (confirm)")

print("Waiting for install (90s)...")
time.sleep(90)

proc.stdin.write("reboot\n"); proc.stdin.flush()
print("  -> reboot")
time.sleep(10)
proc.terminate(); proc.wait(timeout=5)
print("Phase 1 complete!")
