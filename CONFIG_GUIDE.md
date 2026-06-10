# 接线完成后 — 初始配置操作手册 (文档 §4.1)

## 前置确认

```bash
# 在 Linux VM 上
ssh ngit@192.168.80.222
cd /home/ngit/identifier-network-sim

# 确认网卡就绪
ip link show ens37
# 预期: state UP, LOWER_UP (Type-C 已插且交换机通电)

# 确认项目代码是最新的
git pull  # 或手动 scp 最新代码
```

---

## 一、交换机配置 (§4.1.5)

> 以下通过交换机 Console 口或 Web 管理界面操作。具体命令取决于中兴交换机型号。

### 1.1 交换机 #1 (管理面)

```
创建 VLAN 1 (默认, 所有端口):
  port 1~8 → VLAN 1, access 模式

预期: CS 与所有 CR 管理口 L2 互通
```

### 1.2 交换机 #2 (数据面)

```
VLAN 10 (核心面, RID 格式):
  port 1~6 (CR 核心口) → VLAN 10, access 模式, 互通

VLAN 20 (接入面1, AID 格式):
  port 7 (CR-1 接入) → VLAN 20, access 模式
  port 8 (TS+AP-1)   → VLAN 20, access 模式
  端口隔离:
    组1: port 7 ↔ port 8

VLAN 30 (接入面2, AID 格式):
  port 9 (CR-2 接入) → VLAN 30, access 模式
  port 10 (AP-2)     → VLAN 30, access 模式
  端口隔离:
    组1: port 9 ↔ port 10
```

---

## 二、中兴 CR 初始配置 (§4.1.1)

> 通过 Console 口或 SSH 登录每台 CR，由中兴工程师配合完成。

### 2.1 CR-1 配置示例

```
# ---- 接口信息表 (Table 1) ----
interface Eth0  → 管理口, ROUTE, MAC=00:18:54:FD:29:01, UP
interface Eth1  → 核心口, ROUTE, MAC=00:0C:AB:1E:76:8A, UP
interface Eth2  → 接入口, ACCESS, MAC=00:0C:AB:1E:76:8B, UP

# ---- RID 空间表 (Table 2) ----
rid-space 0   (10028|20, 36181|20)  policy=MANAGEMENT
rid-space 100 (12345|20, 34267|24)  policy=DEFAULT

# ---- 路由空间邻居 (Table 3, 核心侧) ----
route-neighbor space=100 rid=(12360,34280) mac=00:0C:AB:1E:76:8C port=Eth1   # CR-2
route-neighbor space=100 rid=(10030,36190) mac=...           port=Eth1   # CR-3

# ---- 接入空间邻居 (Table 4) ----
access-neighbor aid=8d969eef6ecad3c29a3a629280e686cf mac=00:04:AB:1F:40:A6 port=Eth2  # AP-1
access-neighbor aid=d3c29a3a629280e686cf8d969eef6eca mac=00:1A:2B:3C:4D:02 port=Eth2  # TS

# ---- RID 路由表 (Table 5) ----
rid-route space=100 dest=(12345|20,34267|24) next-hop=(12360,34280)   # → CR-2
rid-route space=100 dest=(10028|20,36181|20) next-hop=(10030,36190)   # → CR-3(去CS)

# ---- AID 路由表 (Table 6) ----
aid-route dest=8d969eef6ecad3c29a3a629280e686cf next-hop=8d969eef6ecad3c29a3a629280e686cf  # AP-1本地

# ---- 本地映射表 (Table 7) ----
local-mapping aid=8d969eef6ecad3c29a3a629280e686cf rid=(10001,36191) space=0     # AP-1
local-mapping aid=cad3c29a3a629280e686cf8d969eef6e rid=(10001,36191) space=100   # Host-1
local-mapping aid=d3c29a3a629280e686cf8d969eef6eca rid=(10003,36193) space=100   # TS

# ---- 关联 AP 列表 (Table 8) ----
associated-ap aid=8d969eef6ecad3c29a3a629280e686cf rid=(10001,36191) port=Eth2

# ---- 用户状态列表 (Table 9) ----
# 初始为空, 用户上线后由 CS 通过控制信令动态更新
```

### 2.2 CR-2 配置 (差异部分)

```
rid-route space=100 dest=(10001|20,36191|20) next-hop=(10001,36191)   # → CR-1

local-mapping aid=280e686cf8d969eef6ecad3c29a3a629 rid=(10002,36192)  # AP-2
local-mapping aid=969eef6ecad3c29a3a629280e686cf8d rid=(10002,36192)  # Host-2

associated-ap aid=280e686cf8d969eef6ecad3c29a3a629 rid=(10002,36192) port=Eth2
```

---

## 三、网卡分配

```
ens34 → VMware 桥接 → 交换机 #1 (管理面)   → 仅 CS
ens37 → Type-C 桥接 → 交换机 #2 (数据面)   → TS + AP-1 + AP-2
```

> ens34 原为 NAT 模式, 需在 VMware 设置中改为**桥接模式**(桥接到宿主机网卡), 这样 CS 的帧才能到交换机 #1.

## 四、北交大设备配置 (§4.1.2~4.1.4)

### 4.1 CS (§4.1.3) — ens34

```bash
# 编辑 config/cs.yaml

interfaces:
  - name: ens34        # ← 管理面, 独享
    mac: "00:1A:2B:3C:4D:01"

cs_rid: [10028, 36181]
users:
  - { username: "Zhangsan", password: "123",  pin: "1234", attributes: "UR:3;BW:10Mbps" }
  - { username: "Lisi",     password: "Abc",  pin: "0000", attributes: "UR:2;BW:5Mbps" }
managed_crs:
  - [10001, 36191]    # CR-1
  - [12360, 34280]    # CR-2
  # ... CR-3~6
ap_to_cr:
  - [[10001, 36191], [10001, 36191]]   # AP-1 → CR-1
  - [[10002, 36192], [12360, 34280]]   # AP-2 → CR-2

# 启动:
sudo python3 scripts/real_deploy.py --role cs --config config/cs.yaml
```

### 4.2 TS (§4.1.4) — ens37

```bash
# 编辑 config/ts.yaml

interfaces:
  - name: ens37        # 数据面, 和 AP 共用
    mac: "00:1A:2B:3C:4D:02"

aid: "d3c29a3a629280e686cf8d969eef6eca"
rid: [10003, 36193]

# 启动:
sudo python3 scripts/real_deploy.py --role ts --config config/ts.yaml
```

### 4.3 AP (§4.1.2) — ens37

```bash
# ==== AP-1 ====
# 编辑 config/ap1.yaml

interfaces:
  - name: ens37
    mac: "00:04:AB:1F:40:A6"

aid: "8d969eef6ecad3c29a3a629280e686cf"
rid: [10001, 36191]
cs_rid: [10028, 36181]
cs_mac: "00:1A:2B:3C:4D:01"
cr_rid: [10001, 36191]
cr_mac: "00:18:54:FD:29:01"

local_users:
  - { aid: "cad3c29a3a629280e686cf8d969eef6e", ip: "192.168.1.100", mac: "00:11:22:33:44:01" }

# 启动:
sudo python3 scripts/real_deploy.py --role ap --config config/ap1.yaml

# ==== AP-2 ====
# 编辑 config/ap2.yaml (差异部分:)

aid: "280e686cf8d969eef6ecad3c29a3a629"
rid: [10002, 36192]
cr_rid: [12360, 34280]
cr_mac: "00:18:54:FD:29:02"
mac: "00:05:DC:12:33:28"

local_users:
  - { aid: "969eef6ecad3c29a3a629280e686cf8d", ip: "192.168.2.100", mac: "00:11:22:33:44:02" }
```

### 4.4 Host (§4.1.4) — ens34 (NAT, 仅 IP 通信)

```bash
# ==== Host-1 ====
# 编辑 config/host1.yaml

interfaces:
  - name: ens34        # 不走 Type-C, 走 VM 内 NAT (连 AP)
    mac: "00:11:22:33:44:01"

aid: "cad3c29a3a629280e686cf8d969eef6e"
username: "Zhangsan"
password: "123"
ip: "192.168.1.100"
ap_mac: "00:04:AB:1F:40:A6"      # AP-1 的 MAC
target_aid: "d3c29a3a629280e686cf8d969eef6eca"  # TS 的 AID (HTTP 目标)

# 启动:
sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml
```

## 五、启动顺序

```bash
# 1. 交换机已上电, VLAN 配好
# 2. CR 已按 §二 配置完成
# 3. 启动 CS
sudo python3 scripts/real_deploy.py --role cs --config config/cs.yaml &

# 4. 启动 TS
sudo python3 scripts/real_deploy.py --role ts --config config/ts.yaml &

# 5. 启动 AP-1 + AP-2
sudo python3 scripts/real_deploy.py --role ap --config config/ap1.yaml &
sudo python3 scripts/real_deploy.py --role ap --config config/ap2.yaml &

# 6. 等 3 秒让控制面初始化
sleep 3

# 7. 启动 Host (发业务流量)
sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml &
sudo python3 scripts/real_deploy.py --role host --config config/host2.yaml &
```

## 六、验证初始配置

```bash
# 1. 确认所有进程在跑
ps aux | grep real_deploy

# 2. 抓包确认流量
sudo tcpdump -i ens37 -c 20 -XX | grep -E '0x1111|0x2222'

# 3. 检查 CR 管理口是否可达 (从 VM ping CR)
ping <CR-1管理IP>

# 后续验证按 DEPLOY.md 第三章执行
```
