#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  标识网络 — TAP + Bridge 真实网络
#  每设备: TAP (Python) + veth (tcpdump) 都在对应 bridge 中
#  用法: sudo bash scripts/setup_netns.sh [setup|teardown]
# ═══════════════════════════════════════════════════════════════════════
set -e; ACTION="${1:-setup}"

# 设备 -> (TAP名, MAC, Bridge)
declare -A TAP TAP_MAC TAP_BR

_tap() { TAP[$1]="tap-$1"; TAP_MAC[$1]="$2"; TAP_BR[$1]="$3"; }

# mgmt-br: 管理面
_tap cr1-mgmt "00:c0:01:01:00:01" "mgmt-br"
_tap cr2-mgmt "00:c0:01:02:00:01" "mgmt-br"
_tap cs       "00:c0:01:10:00:01" "mgmt-br"

# core-br: 核心面(RID)
_tap cr1-core "00:c0:01:01:00:02" "core-br"
_tap cr2-core "00:c0:01:02:00:02" "core-br"

# acc-br1: 接入面1
_tap cr1-acc "00:c0:01:01:00:03" "acc-br1"
_tap ap1     "00:c0:01:11:00:01" "acc-br1"
_tap ts      "00:c0:01:20:00:01" "acc-br1"
_tap host1   "00:c0:01:31:00:01" "acc-br1"

# acc-br2: 接入面2
_tap cr2-acc "00:c0:01:02:00:03" "acc-br2"
_tap ap2     "00:c0:01:12:00:01" "acc-br2"
_tap host2   "00:c0:01:32:00:01" "acc-br2"

TAP_KEYS=(cr1-mgmt cr1-core cr1-acc cr2-mgmt cr2-core cr2-acc cs ap1 ap2 ts host1 host2)
BRIDGES=(mgmt-br core-br acc-br1 acc-br2)
NS_DEVICES=(cr1 cr2 cs ap1 ap2 ts host1 host2)

teardown() {
    echo "=== 清理 ==="
    for d in "${NS_DEVICES[@]}"; do ip netns del "ns-${d}" 2>/dev/null || true; done
    for br in "${BRIDGES[@]}"; do ip link del "$br" 2>/dev/null || true; done
    for k in "${TAP_KEYS[@]}"; do ip link del "${TAP[$k]}" 2>/dev/null || true; done
    for v in $(ip link show 2>/dev/null | grep -oP 'v-[a-z0-9]+(?=@)' | sort -u); do
        ip link del "$v" 2>/dev/null || true
    done
    echo "完成"
}

setup() {
    echo "=== TAP 真实仿真 ==="

    # Bridges
    for br in "${BRIDGES[@]}"; do
        ip link add "$br" type bridge stp_state 0 forward_delay 0
        ip link set "$br" up
    done

    # TAPs in bridges
    for k in "${TAP_KEYS[@]}"; do
        local tap="${TAP[$k]}" mac="${TAP_MAC[$k]}" br="${TAP_BR[$k]}"
        ip tuntap add "$tap" mode tap
        ip link set "$tap" address "$mac"
        ip link set "$tap" master "$br"
        ip link set "$tap" up
    done

    # Namespaces + veth (for tcpdump)
    for d in "${NS_DEVICES[@]}"; do
        local ns="ns-${d}"
        ip netns add "$ns"
        ip netns exec "$ns" ip link set lo up
    done
    # veth for each device (single ns per device, use first TAP's bridge)
    for d in cr1 cr2 cs ap1 ap2 ts host1 host2; do
        local vh="v-${d}" vns="v-${d}-ns" ns="ns-${d}"
        # determine which bridge: use the first TAP for this device
        local br="acc-br1"
        case $d in
            cr1) br="acc-br1";; cr2) br="acc-br2";; cs) br="mgmt-br";;
            ap1|ts|host1) br="acc-br1";; ap2|host2) br="acc-br2";;
        esac
        ip link add "$vh" type veth peer name "$vns"
        ip link set "$vh" master "$br"; ip link set "$vh" up
        ip link set "$vns" netns "$ns"
        ip netns exec "$ns" ip link set "$vns" up
    done

    echo ""
    echo "=== 创建完成 ==="
    echo "  Bridges: ${BRIDGES[*]}"
    echo "  TAPs: ${#TAP_KEYS[@]}"
    echo "  抓包: sudo ip netns exec ns-cr1 tcpdump -i v-cr1-ns -XX"
    echo "  仿真: sudo python3 scripts/real_orchestrator.py test"
}

case "$ACTION" in
    setup) setup;;  teardown) teardown;;
    *) echo "用法: $0 setup|teardown"; exit 1;;
esac
