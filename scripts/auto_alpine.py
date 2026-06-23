"""Full automated Alpine install via pexpect."""
import pexpect, time, os

DISK = "/home/ngit/GNS3/images/QEMU/alpine-base.qcow2"
ISO  = "/home/ngit/GNS3/images/QEMU/alpine-virt-3.21.3-x86_64.iso"

print("=== Phase 1: Install Alpine to disk ===")
child = pexpect.spawn(
    f"qemu-system-x86_64 -m 512 "
    f"-drive file={DISK},if=ide "
    f"-cdrom {ISO} -boot d "
    f"-nic user,model=virtio "
    f"-display none -serial stdio -monitor none -no-reboot",
    timeout=180, encoding="utf-8", codec_errors="ignore"
)

child.expect("login:", timeout=60)
print("Got login")
child.sendline("root")
child.expect("# ")
print("Root OK")

# Step 1: Bring up network
child.sendline("udhcpc -i eth0")
child.expect("# ", timeout=15)
print("Network up")

# Step 2: Set APK repos to network
child.sendline("cat > /etc/apk/repositories << EOF")
child.sendline("https://dl-cdn.alpinelinux.org/alpine/v3.21/main")
child.sendline("https://dl-cdn.alpinelinux.org/alpine/v3.21/community")
child.sendline("EOF")
child.expect("# ")

# Step 3: Update and install grub
child.sendline("apk update")
child.expect("# ", timeout=20)
print("apk updated")
child.sendline("apk add grub grub-bios")
child.expect("# ", timeout=30)
print("grub installed")

# Step 4: Install to disk
child.sendline("setup-disk -m sys /dev/sda")
idx = child.expect(["continue?", "# "], timeout=15)
if idx == 0:
    child.sendline("y")
    child.expect("halt", timeout=120)
    print("Phase 1 done!")
else:
    print("setup-disk may have auto-completed")

child.close()
time.sleep(3)

# ============================================================
print("=== Phase 2: Install Python + project ===")
child2 = pexpect.spawn(
    f"qemu-system-x86_64 -m 512 "
    f"-drive file={DISK},if=ide "
    f"-nic user,model=virtio "
    f"-display none -serial stdio -monitor none",
    timeout=180, encoding="utf-8", codec_errors="ignore"
)

child2.expect("login:", timeout=60)
child2.sendline("root")
child2.expect("# ")
print("Booted from disk")

# Network
child2.sendline("udhcpc -i eth0")
child2.expect("# ", timeout=15)

# APK repos
child2.sendline("cat > /etc/apk/repositories << EOF")
child2.sendline("https://dl-cdn.alpinelinux.org/alpine/v3.21/main")
child2.sendline("https://dl-cdn.alpinelinux.org/alpine/v3.21/community")
child2.sendline("EOF")
child2.expect("# ")

# Python
child2.sendline("apk update")
child2.expect("# ", timeout=20)
child2.sendline("apk add python3 py3-pip")
child2.expect("# ", timeout=60)
print("Python installed")
child2.sendline("pip3 install loguru prometheus_client PyYAML")
child2.expect("# ", timeout=60)
print("Pip packages installed")

# Project code
child2.sendline("mkdir -p /opt/identifier-network-sim")
child2.expect("# ")
child2.sendline("wget -q http://10.0.2.2:8765/project.tar.gz -O /opt/identifier-network-sim/project.tar.gz")
child2.expect("# ", timeout=30)
child2.sendline("cd /opt/identifier-network-sim && tar xzf project.tar.gz && rm project.tar.gz")
child2.expect("# ")
print("Project code injected")

# Startup script
startup_cmd = """cat > /etc/local.d/start.start << 'INIT'
#!/bin/sh
ROLE=$(cat /opt/identifier-network-sim/role.txt 2>/dev/null)
if [ -n "$ROLE" ]; then
    cd /opt/identifier-network-sim
    python3 scripts/real_deploy.py --role "$ROLE" --config config/qemu/"$ROLE".yaml > /var/log/id-net.log 2>&1 &
fi
INIT"""
child2.sendline(startup_cmd)
child2.expect("# ")
child2.sendline("chmod +x /etc/local.d/start.start")
child2.expect("# ")
child2.sendline("rc-update add local")
child2.expect("# ")
child2.sendline("ls /opt/identifier-network-sim/src/common/")
child2.expect("# ")
print("Startup script ready")

child2.sendline("poweroff")
time.sleep(15)
child2.close()
print("Golden image complete!")
print(f"Disk: {DISK}")