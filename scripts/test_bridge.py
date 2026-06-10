#!/usr/bin/env python3
"""TAP bridge 转发验证 — TAP 必须先 open 才能让 bridge port UP"""
import fcntl, os, struct, subprocess, time
TUNSETIFF=0x400454CA; IFF_TAP=0x0002; IFF_NO_PI=0x1000; PWD="bjtungit\n"

def sudo(args):
    subprocess.run(["sudo","-S"]+args, input=PWD, capture_output=True, timeout=15)

def sh(cmd):
    subprocess.run(f"echo '{PWD}' | sudo -S bash -c '{cmd}'", shell=True, capture_output=True, timeout=15)

# cleanup
sh("ip netns del ns-a 2>/dev/null; ip netns del ns-b 2>/dev/null; ip link del br0 2>/dev/null; ip tuntap del tap-a mode tap 2>/dev/null; true")
time.sleep(0.2)

# setup
sh("ip link add br0 type bridge stp_state 0 forward_delay 0 && ip link set br0 up")
sh("ip tuntap add tap-a mode tap && ip link set tap-a master br0 && ip link set tap-a up")
sh("ip netns add ns-a && ip netns exec ns-a ip link set lo up")
sh("ip link add v-a type veth peer name v-a-ns")
sh("ip link set v-a master br0 && ip link set v-a up")
sh("ip link set v-a-ns netns ns-a && ip netns exec ns-a ip link set v-a-ns up")
time.sleep(0.3)

# Check state BEFORE opening TAP
r = subprocess.run(f"echo '{PWD}' | sudo -S bridge link show dev br0", shell=True, capture_output=True, text=True)
print("BEFORE TAP open:", r.stdout[:120] if r.stdout else "(empty)")

# NOW open TAP
tap_fd = os.open("/dev/net/tun", os.O_RDWR)
ifr = struct.pack("16sH", b"tap-a", IFF_TAP | IFF_NO_PI)
fcntl.ioctl(tap_fd, TUNSETIFF, ifr)
os.set_blocking(tap_fd, False)
time.sleep(0.2)

# Check state AFTER opening TAP
r = subprocess.run(f"echo '{PWD}' | sudo -S bridge link show dev br0", shell=True, capture_output=True, text=True)
print("AFTER  TAP open:", r.stdout[:200] if r.stdout else "(empty)")

# Send frame through TAP
frame = bytes.fromhex("ffffffffffff00c00101000188b5") + b"TAPTESTXYZ"
os.write(tap_fd, frame)
print(f"wrote {len(frame)}B to tap-a")
time.sleep(0.3)

# tcpdump on ns-a veth
r = subprocess.run(
    f"echo '{PWD}' | sudo -S timeout 2 ip netns exec ns-a tcpdump -i v-a-ns -c 5 2>&1",
    shell=True, capture_output=True, text=True, timeout=10
)
for line in r.stdout.split('\n'):
    if 'TAPTEST' in line or '0x88b5' in line:
        print("SUCCESS:", line.strip())
        break
else:
    print("Result: frame NOT forwarded through bridge")

os.close(tap_fd)
sh("ip netns del ns-a; ip link del br0; true")
print("done")
