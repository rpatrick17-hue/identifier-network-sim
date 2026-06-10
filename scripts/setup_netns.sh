#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  标识网络 — veth 对
#  用法: sudo bash scripts/setup_netns.sh [setup|teardown]
# ═══════════════════════════════════════════════════════════════
ACTION="${1:-setup}"

declare -A VETH_MAC
VETH_MAC[cr1]="00:c0:01:01:00:01"; VETH_MAC[cr2]="00:c0:01:02:00:01"
VETH_MAC[cs]="00:c0:01:10:00:01";   VETH_MAC[ap1]="00:c0:01:11:00:01"
VETH_MAC[ap2]="00:c0:01:12:00:01";  VETH_MAC[ts]="00:c0:01:20:00:01"
VETH_MAC[host1]="00:c0:01:31:00:01"; VETH_MAC[host2]="00:c0:01:32:00:01"
DEVICES=(cr1 cr2 cs ap1 ap2 ts host1 host2)

teardown() {
    echo "=== 清理网络环境 ==="
    # 1. 删除命名空间 (连带删除 ns 内的 veth)
    for d in "${DEVICES[@]}"; do
        ip netns del "ns-${d}" 2>/dev/null
    done
    # 2. 删除残留的宿主机侧 veth (命名空间删除后, peer 可能残留)
    for v in $(ip link show 2>/dev/null | grep -oP 'veth-[a-z0-9]+(?=@)' | sort -u); do
        ip link del "$v" 2>/dev/null
    done
    echo "清理完成"
}

setup() {
    # 先彻底清理残留, 确保干净环境
    teardown

    echo ""
    echo "=== 创建 veth 对 ==="
    for d in "${DEVICES[@]}"; do
        local ns="ns-${d}" vh="veth-${d}" vns="veth-${d}-ns" mac="${VETH_MAC[$d]}"

        ip netns add "$ns" 2>/dev/null
        ip netns exec "$ns" ip link set lo up

        ip link add "$vh" type veth peer name "$vns" 2>/dev/null
        ip link set "$vh" up
        ip link set "$vns" netns "$ns"
        ip netns exec "$ns" ip link set "$vns" address "$mac" 2>/dev/null
        ip netns exec "$ns" ip link set "$vns" up

        echo "  + $d: $vh ↔ $ns:$vns ($mac)"
    done

    echo ""
    echo "=== ${#DEVICES[@]} 对 veth 创建完成 ==="
    echo ""
    echo "  运行仿真: sudo python3 scripts/real_simulation.py test"
    echo "  清理环境: sudo bash scripts/setup_netns.sh teardown"
}

case "$ACTION" in
    setup)    setup ;;
    teardown) teardown ;;
    *)        echo "用法: $0 setup|teardown" ;;
esac
