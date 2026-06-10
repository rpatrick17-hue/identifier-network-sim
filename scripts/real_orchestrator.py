#!/usr/bin/env python3
"""
标识网络 — 一体式真实仿真编排器

1. 创建 TAP + Bridge 网络环境
2. 启动全部 8 个设备进程 (各自独立)
3. Host 进程自动执行内置场景 (HTTP 请求)
4. 收集各进程的统计结果
5. 清理网络

用法: sudo python3 scripts/real_orchestrator.py
"""

from __future__ import annotations
import os, signal, subprocess, sys, time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SETUP_SH  = PROJECT / "scripts" / "setup_netns.sh"
DEVICE_PY = PROJECT / "scripts" / "real_device.py"
PWD = "bjtungit\n"

DEVICES = ["cs", "ts", "cr1", "cr2", "ap1", "ap2", "host1", "host2"]


def sudo(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(["sudo", "-S"] + args, input=PWD,
                          capture_output=True, text=True, timeout=timeout)


def sh(cmd: str, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(f"echo '{PWD}' | sudo -S bash -c '{cmd}'",
                          shell=True, capture_output=True, text=True, timeout=timeout)


def setup_network() -> bool:
    print("=== 创建网络 (TAP + Bridge) ===")
    # Kill any lingering device processes that hold TAP fds
    sh("pkill -f real_device.py 2>/dev/null; true")
    time.sleep(0.5)
    sh("bash " + str(SETUP_SH) + " teardown 2>/dev/null; true")
    time.sleep(0.5)
    r = sh("bash " + str(SETUP_SH) + " setup")
    print(r.stdout[-500:] if len(r.stdout) > 500 else r.stdout)
    return r.returncode == 0


def teardown_network() -> None:
    print("=== 清理网络 ===")
    sh("bash " + str(SETUP_SH) + " teardown 2>/dev/null; true")


def launch_device(dev: str) -> subprocess.Popen:
    """Launch a device process. All processes run in host namespace
    since TAPs are in host namespace and in bridges."""
    cmd = ["sudo", "-S", "python3", str(DEVICE_PY), dev]
    print(f"  launch {dev}")
    return subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # Note: stdin PIPE needed for sudo -S password, but we use NOPASSWD via -S


def main() -> None:
    if os.geteuid() != 0:
        print("需要 root!  sudo python3 scripts/real_orchestrator.py")
        sys.exit(1)

    print("=== 一体式真实仿真 (TAP 架构) ===\n")

    # 1. Network setup
    if not setup_network():
        print("网络创建失败!")
        sys.exit(1)
    time.sleep(0.5)

    # 2. Launch all device processes
    print("\n=== 启动设备进程 ===")
    procs: dict[str, subprocess.Popen] = {}
    for dev in DEVICES:
        p = launch_device(dev)
        # Send password via stdin for sudo -S
        p.stdin.write(PWD); p.stdin.flush()
        procs[dev] = p
        time.sleep(0.15)

    print(f"\n{len(procs)} 个进程运行中, 等待场景完成...")

    # 3. Wait for completion
    timeout_s = 35
    start = time.time()
    results: dict[str, str] = {}

    try:
        while time.time() - start < timeout_s:
            for dev, proc in list(procs.items()):
                if proc.poll() is not None and dev not in results:
                    out = (proc.stdout.read() or "") + (proc.stderr.read() or "")
                    results[dev] = out
                    print(f"  [{dev}] exited rc={proc.returncode}")
            if len(results) >= len(procs):
                break
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n中断...")
    finally:
        # Kill remaining
        for dev, proc in procs.items():
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=2)
                except: proc.kill()

    # 4. Report
    elapsed = time.time() - start
    print(f"\n{'='*55}")
    print(f"  仿真结果 ({elapsed:.1f}s)")
    print(f"{'='*55}")
    for dev in DEVICES:
        if dev in results:
            for line in results[dev].split('\n'):
                if 'RESULT:' in line or 'stopped' in line:
                    print(f"  [{dev}] {line.strip()}")
        else:
            print(f"  [{dev}] 未完成")

    # 5. Cleanup
    print()
    teardown_network()
    print("完成.")


if __name__ == "__main__":
    main()
