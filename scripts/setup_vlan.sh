#!/bin/bash
# ============================================================================
#  VLAN 子接口初始化脚本
#
#  在 ens37 上创建 VLAN 子接口, 使一台 Linux 服务器可以跑全部角色:
#    ens37.10 → VLAN 10 (核心面: CR-1 ↔ CR-2)
#    ens37.20 → VLAN 20 (接入面1: CR-1 接入 + AP-1 + TS)
#    ens37.30 → VLAN 30 (接入面2: CR-2 接入 + AP-2)
#
#  前提: 交换机对应端口已配为 trunk 模式, 允许 VLAN 10/20/30
#
#  用法:
#    sudo bash scripts/setup_vlan.sh setup
#    sudo bash scripts/setup_vlan.sh teardown
#    sudo bash scripts/setup_vlan.sh status
# ============================================================================

set -e

PARENT="ens37"
VLANS=("10" "20" "30")

setup() {
    echo "=== 创建 VLAN 子接口 (parent: $PARENT) ==="

    # 确保父接口 UP
    ip link set "$PARENT" up 2>/dev/null || true

    for vid in "${VLANS[@]}"; do
        local ifname="${PARENT}.${vid}"
        if ip link show "$ifname" &>/dev/null; then
            echo "  [skip] $ifname already exists"
        else
            ip link add link "$PARENT" name "$ifname" type vlan id "$vid"
            echo "  [created] $ifname (VLAN $vid)"
        fi
        ip link set "$ifname" up
    done

    echo "=== VLAN 子接口就绪 ==="
    ip -br link show | grep "$PARENT"
}

teardown() {
    echo "=== 删除 VLAN 子接口 ==="
    for vid in "${VLANS[@]}"; do
        local ifname="${PARENT}.${vid}"
        if ip link show "$ifname" &>/dev/null; then
            ip link delete "$ifname"
            echo "  [deleted] $ifname"
        else
            echo "  [skip] $ifname not found"
        fi
    done
    echo "=== 清理完成 ==="
}

status() {
    echo "=== VLAN 子接口状态 ==="
    for vid in "${VLANS[@]}"; do
        local ifname="${PARENT}.${vid}"
        if ip link show "$ifname" &>/dev/null; then
            ip -br link show "$ifname"
        else
            echo "  $ifname: NOT FOUND"
        fi
    done
    echo ""
    echo "=== 交换机 trunk 验证提示 ==="
    echo "  交换机对应端口应为 trunk 模式, 允许 VLAN ${VLANS[*]}"
    echo "  验证: tcpdump -i $PARENT -c 5 -e vlan"
}

case "${1:-status}" in
    setup)    setup ;;
    teardown) teardown ;;
    status)   status ;;
    *)        echo "Usage: $0 {setup|teardown|status}" ;;
esac
