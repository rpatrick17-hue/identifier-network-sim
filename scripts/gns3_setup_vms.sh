#!/bin/bash
# ============================================================================
#  GNS3 Alpine VM 批量部署脚本
#
#  1. 创建 12 个 QEMU 磁盘 (qcow2)
#  2. 构建一个 Alpine 黄金镜像 (含 Python + 项目代码)
#  3. 克隆黄金镜像到每个角色的磁盘
#  4. 注入角色配置
#
#  用法: bash scripts/gns3_setup_vms.sh
# ============================================================================

set -e
PROJECT_DIR="/home/ngit/identifier-network-sim"
DISK_DIR="/home/ngit/GNS3/images/QEMU"
ALPINE_ISO="$DISK_DIR/alpine-virt-3.21.3-x86_64.iso"
GOLDEN_DISK="$DISK_DIR/alpine-golden.qcow2"
DISK_SIZE="2G"

ROLES=("CS" "CR-1" "CR-2" "CR-3" "CR-4" "CR-5" "CR-6" "TS" "AP-1" "AP-2" "Host-1" "Host-2")

echo "=== 1. 创建 QEMU 磁盘 ==="
for role in "${ROLES[@]}"; do
    disk="$DISK_DIR/alpine-${role}.qcow2"
    if [ -f "$disk" ]; then
        echo "  [skip] $disk exists"
    else
        qemu-img create -f qcow2 "$disk" "$DISK_SIZE"
        echo "  [created] $disk ($DISK_SIZE)"
    fi
done

echo ""
echo "=== 2. 构建黄金镜像 ==="
echo "  启动 Alpine ISO 并安装系统到 $GOLDEN_DISK"
echo ""
echo "  手动步骤 (在 GNS3 中创建一台临时 VM):"
echo "  ----------------------------------------"
echo "  1. 在 GNS3 中拖一个 QEMU VM 模板"
echo "  2. 磁盘: 用 $GOLDEN_DISK"
echo "  3. 光驱: 挂载 $ALPINE_ISO"
echo "  4. 启动 VM → 右键 Console → telnet 连接"
echo "  5. 登录 (root, 无密码)"
echo ""
echo "  在 Alpine 中执行以下命令:"
echo "  ----------------------------------------"
cat << 'ALPINE_SETUP'
  # 安装 Alpine 到磁盘
  setup-alpine -e << EOF
us
us
alpine
alpine
alpine
sda
sys
none
none
none
openssh
reboot
EOF

  # 重启后登录
  # 安装 Python 和依赖
  apk add python3 py3-pip
  pip3 install loguru prometheus_client PyYAML

  # 复制项目代码
  mkdir -p /opt/identifier-network-sim
  # (从主机复制: scp 或挂载共享目录)

  # 创建角色识别脚本
  cat > /etc/local.d/startup.start << 'INIT'
#!/bin/sh
# 读取角色配置, 启动对应服务
ROLE_FILE=/opt/identifier-network-sim/config/role.txt
if [ -f $ROLE_FILE ]; then
    ROLE=$(cat $ROLE_FILE)
    cd /opt/identifier-network-sim
    python3 scripts/real_deploy.py --role $ROLE --config config/qemu/${ROLE}.yaml &
fi
INIT
  chmod +x /etc/local.d/startup.start
  rc-update add local

ALPINE_SETUP

echo "  ----------------------------------------"
echo "  6. 关机: poweroff"
echo "  7. 这个 $GOLDEN_DISK 就是黄金镜像"
echo ""
echo "=== 3. 克隆到所有角色 ==="
echo "  每个角色磁盘 = 黄金镜像 + 角色名文件"
echo ""
echo "  for role in ${ROLES[*]}; do"
echo "    qemu-img create -f qcow2 -o backing_file=$GOLDEN_DISK \$role.qcow2"
echo "  done"

echo ""
echo "=== 完成 ==="
