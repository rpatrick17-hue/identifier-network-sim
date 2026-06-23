#!/bin/bash
# ============================================================================
#  GNS3 全栈部署: VLAN交换机 + Alpine黄金镜像 + 克隆 + 启动
# ============================================================================
#  步骤:
#   1. 构建黄金镜像 (手动, 10分钟, 只需做一次)
#   2. 克隆到 12 个角色 (自动)
#   3. 为每个角色注入配置 (自动)
#   4. 重建 VLAN 交换机拓扑 (自动, 通过 API)
# ============================================================================

set -e
DISK_DIR="/home/ngit/GNS3/images/QEMU"
GOLDEN="$DISK_DIR/alpine-golden.qcow2"
ALPINE_ISO="$DISK_DIR/alpine-virt-3.21.3-x86_64.iso"
PROJECT_DIR="/home/ngit/identifier-network-sim"

ROLES=("CS" "CR-1" "CR-2" "CR-3" "CR-4" "CR-5" "CR-6" "TS" "AP-1" "AP-2" "Host-1" "Host-2")

# ═══════════════════════════════════════════════════════════════
step1_golden() {
    echo "=============================================="
    echo "  步骤 1: 构建黄金镜像 (手动)"
    echo "=============================================="
    echo ""
    echo "  在 GNS3 GUI 中操作:"
    echo ""
    echo "  1. 左侧工具栏 → 拖 'QEMU' 到画布"
    echo "  2. 配置:"
    echo "     - Name: golden"
    echo "     - QEMU binary: /usr/bin/qemu-system-x86_64 (remote)"
    echo "     - RAM: 512 MB"
    echo "     - Disk image (hda): $GOLDEN (NEW, 2GB, qcow2)"
    echo "     - CD/DVD (hdb): $ALPINE_ISO"
    echo "     - Boot priority: CD first"
    echo ""
    echo "  3. 启动 VM → 右键 Console → telnet 连接"
    echo "  4. 登录 root (无密码)"
    echo "  5. 执行以下命令:"
    echo ""
    echo "  ┌────────────────────────────────────────────┐"
    echo "  │ # 安装 Alpine 到磁盘                       │"
    echo "  │ setup-disk -m sys /dev/sda                 │"
    echo "  │ # 重启                                     │"
    echo "  │ reboot                                     │"
    echo "  │                                            │"
    echo "  │ # 重启后登录, 安装软件                     │"
    echo "  │ apk add python3 py3-pip                    │"
    echo "  │ pip3 install loguru prometheus_client PyYAML │"
    echo "  │                                            │"
    echo "  │ # 部署项目代码 (从宿主机拷贝)               │"
    echo "  │ mkdir -p /opt/id-net                       │"
    echo "  │ # TODO: scp from host                      │"
    echo "  │                                            │"
    echo "  │ # 开机自启动脚本                            │"
    echo "  │ echo '#!/bin/sh' > /etc/local.d/start.start │"
    echo "  │ echo '/opt/id-net/start.sh' >> /etc/local.d/start.start │"
    echo "  │ chmod +x /etc/local.d/start.start          │"
    echo "  │ rc-update add local                        │"
    echo "  │                                            │"
    echo "  │ poweroff                                   │"
    echo "  └────────────────────────────────────────────┘"
    echo ""
    echo "  6. 删除 golden VM (磁盘保留!)"
    echo ""
    echo "  完成! 黄金镜像: $GOLDEN"
}

# ═══════════════════════════════════════════════════════════════
step2_clone() {
    echo "=== 步骤 2: 克隆磁盘 ==="
    if [ ! -f "$GOLDEN" ]; then
        echo "错误: 黄金镜像 $GOLDEN 不存在!"
        echo "先完成步骤 1: bash $0 step1"
        exit 1
    fi
    for role in "${ROLES[@]}"; do
        disk="$DISK_DIR/alpine-${role}.qcow2"
        # Use backing file to save space
        qemu-img create -f qcow2 -b "$GOLDEN" -F qcow2 "$disk" 2>/dev/null
        echo "  [cloned] $role -> $(du -h $disk | cut -f1)"
    done
    echo "12 个磁盘克隆完成 (共享黄金镜像, 总占用 < 200MB)"
}

# ═══════════════════════════════════════════════════════════════
step3_config() {
    echo "=== 步骤 3: 更新 GNS3 节点使用新磁盘 ==="
    echo "  运行: python3 scripts/gns3_apply_disks.py"
    python3 "$PROJECT_DIR/scripts/gns3_apply_disks.py"
}

# ═══════════════════════════════════════════════════════════════
step4_vlan() {
    echo "=== 步骤 4: VLAN 交换机拓扑 ==="
    python3 "$PROJECT_DIR/scripts/gns3_vlan_switches.py"
}

# ═══════════════════════════════════════════════════════════════
step5_start() {
    echo "=== 步骤 5: 启动全部节点 ==="
    python3 "$PROJECT_DIR/scripts/gns3_topology.py" start
}

# ═══════════════════════════════════════════════════════════════
case "${1:-help}" in
    step1) step1_golden ;;
    step2) step2_clone ;;
    step3) step3_config ;;
    step4) step4_vlan ;;
    all)   step2_clone; step3_config; step4_vlan; step5_start ;;
    *)     echo "Usage: $0 {step1|step2|step3|step4|all}"
           echo "  step1: 手动构建黄金镜像"
           echo "  step2: 克隆磁盘到12个角色"
           echo "  step3: 更新GNS3节点磁盘"
           echo "  step4: VLAN交换机拓扑"
           echo "  all:   自动执行 2+3+4+5" ;;
esac
