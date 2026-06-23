#!/usr/bin/env python3
"""
自动化构建 Alpine 黄金镜像

使用 QEMU + 串口自动化, 无需人工干预:
  1. 创建 qcow2 磁盘
  2. 从 ISO 启动 Alpine, 通过串口自动安装到磁盘
  3. 安装后启动, SSH 进入安装 Python + 依赖
  4. 复制项目代码
  5. 创建启动脚本
  6. 关机 → 黄金镜像就绪

用法: python3 scripts/build_golden_image.py
前提: qemu-system-x86_64 已安装, Alpine ISO 已下载
"""

import os, subprocess, sys, time, socket, select

DISK_DIR = "/home/ngit/GNS3/images/QEMU"
ALPINE_ISO = f"{DISK_DIR}/alpine-virt-3.21.3-x86_64.iso"
GOLDEN_DISK = f"{DISK_DIR}/alpine-golden.qcow2"
DISK_SIZE = "2G"
PROJECT_DIR = "/home/ngit/identifier-network-sim"
SSH_KEY = os.path.expanduser("~/.ssh/id_rsa")


def run(cmd, check=True):
    print(f"  $ {cmd}")
    return subprocess.run(cmd, shell=True, check=check,
                          capture_output=True, text=True)


def step1_create_disk():
    """Create an empty qcow2 disk."""
    if os.path.exists(GOLDEN_DISK):
        print(f"  [skip] {GOLDEN_DISK} exists. Delete first to rebuild.")
        return False
    run(f"qemu-img create -f qcow2 {GOLDEN_DISK} {DISK_SIZE}")
    return True


def step2_install_alpine():
    """Boot Alpine ISO + empty disk via QEMU.  Piped answers auto-install."""
    print("\n=== Auto-installing Alpine to disk (60s) ===")

    # Alpine setup-alpine answers (in order):
    # keyboard, hostname, iface, ip, netmask, gw, dns, root pw, timezone,
    # proxy, mirror, ssh, ntp, disk mode, disk
    answers = "\n".join([
        "us",           # keyboard layout
        "us",           # variant
        "alpine",       # hostname
        "eth0",         # interface
        "dhcp",         # IP (dhcp)
        "",             # manual IP (skip)
        "",             # netmask
        "",             # gateway
        "",             # DNS
        "alpine",       # root password
        "alpine",       # confirm
        "UTC",          # timezone
        "none",         # proxy
        "1",            # mirror (fastest)
        "openssh",      # SSH server
        "chrony",       # NTP
        "none",         # no disk mode (we use setup-disk later)
    ])

    # Use setup-disk for quick install
    # After setup-alpine, run: setup-disk -m sys /dev/sda
    full_script = answers + "\nsetup-disk -m sys /dev/sda\ny\nreboot\n"

    # QEMU with serial console
    qemu_cmd = (
        f"qemu-system-x86_64 "
        f"-m 512 "
        f"-drive file={GOLDEN_DISK},if=virtio "
        f"-cdrom {ALPINE_ISO} "
        f"-boot d "
        f"-nographic "
        f"-serial stdio "
        f"-no-reboot "
    )

    proc = subprocess.Popen(
        qemu_cmd, shell=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True
    )

    # Wait for login prompt, then feed answers
    time.sleep(15)
    try:
        proc.stdin.write(full_script)
        proc.stdin.flush()
        time.sleep(120)
        proc.terminate()
        proc.wait(timeout=10)
    except:
        proc.kill()

    print("  Alpine installed to disk")


def step3_boot_and_setup():
    """Boot from disk (no ISO). Set up SSH, install Python, copy code."""
    print("\n=== Booting from disk, setting up Python (90s) ===")

    # Port forwarding: host:2222 -> VM:22
    qemu_cmd = (
        f"qemu-system-x86_64 "
        f"-m 512 "
        f"-drive file={GOLDEN_DISK},if=virtio "
        f"-netdev user,id=net0,hostfwd=tcp::2222-:22 "
        f"-device virtio-net,netdev=net0 "
        f"-nographic -serial stdio "
        f"-daemonize "
    )

    run(qemu_cmd)
    time.sleep(20)  # wait for boot + SSH

    # SSH in and install
    ssh_opts = "-o StrictHostKeyChecking=no -o ConnectTimeout=10 -p 2222"
    ssh_target = f"root@localhost"

    # Install packages
    run(f"ssh {ssh_opts} {ssh_target} 'apk add python3 py3-pip' 2>&1", check=False)
    run(f"ssh {ssh_opts} {ssh_target} 'pip3 install loguru prometheus_client PyYAML' 2>&1", check=False)

    # Copy project code
    run(f"ssh {ssh_opts} {ssh_target} 'mkdir -p /opt/identifier-network-sim' 2>&1", check=False)
    run(f"scp {ssh_opts} -r {PROJECT_DIR}/src root@localhost:/opt/identifier-network-sim/ 2>&1", check=False)
    run(f"scp {ssh_opts} -r {PROJECT_DIR}/scripts root@localhost:/opt/identifier-network-sim/ 2>&1", check=False)
    run(f"scp {ssh_opts} -r {PROJECT_DIR}/config root@localhost:/opt/identifier-network-sim/ 2>&1", check=False)

    # Startup script
    startup_script = """#!/bin/sh
ROLE_FILE=/opt/identifier-network-sim/config/role.txt
if [ -f $ROLE_FILE ]; then
    ROLE=$(cat $ROLE_FILE)
    cd /opt/identifier-network-sim
    python3 scripts/real_deploy.py --role $ROLE --config config/qemu/$ROLE.yaml > /var/log/id-net.log 2>&1 &
fi
"""
    run(f"ssh {ssh_opts} {ssh_target} 'echo \"{startup_script}\" > /etc/local.d/start.start && chmod +x /etc/local.d/start.start && rc-update add local' 2>&1", check=False)

    # Poweroff
    run(f"ssh {ssh_opts} {ssh_target} 'poweroff' 2>&1", check=False)
    time.sleep(5)

    # Kill QEMU
    run("pkill -f 'qemu-system.*alpine-golden'", check=False)
    print("  Golden image ready: %s" % GOLDEN_DISK)


# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not os.path.exists(ALPINE_ISO):
        print(f"错误: Alpine ISO 不存在: {ALPINE_ISO}")
        sys.exit(1)

    if step1_create_disk():
        step2_install_alpine()
        step3_boot_and_setup()
        print(f"\n✅ 黄金镜像构建完成: {GOLDEN_DISK}")
        print("   下一步: python3 scripts/gns3_apply_disks.py (克隆并关联到 GNS3 节点)")
    else:
        print("黄金镜像已存在, 跳过构建。")
        print("如需重建: rm %s" % GOLDEN_DISK)
