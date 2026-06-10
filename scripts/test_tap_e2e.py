#!/usr/bin/env python3
"""Final TAP test with proper error handling"""
import os, fcntl, struct, subprocess, time
T=0x400454CA; I=0x0002; N=0x1000; PWD=b"bjtungit\n"

def sh(cmd):
    subprocess.run(["sudo","-S"]+cmd.split(), input=PWD, capture_output=True)

def drain(fd, n=20):
    for _ in range(n):
        try: os.read(fd, 2048)
        except (BlockingIOError, OSError): pass

# Kill old + fresh
subprocess.run(["sudo","-S","fuser","-k","/dev/net/tun"], input=PWD, capture_output=True)
time.sleep(1)
sh("ip link del br0 2>/dev/null; ip tuntap del tap-a mode tap 2>/dev/null; ip tuntap del tap-b mode tap 2>/dev/null; true")
time.sleep(0.3)
sh("ip link add br0 type bridge stp_state 0 forward_delay 0")
sh("ip link set br0 up")
sh("ip tuntap add tap-a mode tap && ip tuntap add tap-b mode tap")
sh("ip link set tap-a master br0 && ip link set tap-b master br0")
sh("ip link set tap-a up && ip link set tap-b up")
time.sleep(0.3)

fa=os.open("/dev/net/tun", os.O_RDWR)
fcntl.ioctl(fa, T, struct.pack("16sH", b"tap-a", I|N))
os.set_blocking(fa, False)
fb=os.open("/dev/net/tun", os.O_RDWR)
fcntl.ioctl(fb, T, struct.pack("16sH", b"tap-b", I|N))
os.set_blocking(fb, False)
time.sleep(0.2)
drain(fa); drain(fb)

# Send
os.write(fa, bytes.fromhex("ffffffffffff"+"00"*6+"88b5")+b"FINALTEST")
print("sent")
time.sleep(0.5)

# Read with retry (kernel frames may arrive first)
for attempt in range(20):
    try:
        data = os.read(fb, 2048)
        if data and b"FINALTEST" in data:
            print(f"SUCCESS on attempt {attempt+1}! ({len(data)}B)")
            break
    except (BlockingIOError, OSError):
        pass
    time.sleep(0.1)
else:
    print("FAIL: FINALTEST not received after 2s")

os.close(fa); os.close(fb)
sh("ip link del br0 2>/dev/null; true")
print("done")
