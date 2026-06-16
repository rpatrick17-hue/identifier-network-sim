# 真实部署教程 — 单机全角色运行

---

## 〇、物理拓扑：交换机怎么接

### 设备

```
Windows 笔记本 (VMware Workstation)
├── Linux VM (192.168.80.222)     ← 跑全部8个角色
│
├── 网卡1: ens34 (桥接到笔记本自带网卡 / NAT)
│   用途: CS 管理面 + CR 管理面
│
├── 网卡2: Type-C 拓展坞 (USB-C → RJ45)
│   VMware 桥接 → VM 内为 ens37
│   用途: 数据面 (VLAN 10/20/30)
│
└── 中兴交换机 ×2
```

### 单交换机方案（只有 1 个 Type-C 网口）

```
                  Windows 笔记本
                  ┌─────────────────────────────────────────────┐
                  │  Linux VM                                    │
                  │                                              │
                  │  ens34 (VMware NAT, 仅上外网 SSH 用)          │
                  │  ens37 (VMware桥接 → Type-C网卡)              │
                  │    ├── VLAN 1:   CS + CR-1管理 + CR-2管理    │
                  │    ├── VLAN 10:  CR-1核心 + CR-2核心         │
                  │    ├── VLAN 20:  CR-1接入 + AP-1 + TS        │
                  │    └── VLAN 30:  CR-2接入 + AP-2             │
                  └─────────────┬───────────────────────────────┘
                                │ 网线 (Type-C RJ45)
                  ┌─────────────┴───────────────────────────────────┐
                  │            交换机 #2 (数据面, trunk 模式)        │
                  │                                                │
                  │  口1 (trunk) ←── 笔记本 Type-C                  │
                  │      允许 VLAN 10, 20, 30, 带 tag 转发          │
                  │                                                │
                  │  VLAN 10 (核心面):  port1(tag)                  │
                  │    帧带 VLAN10 tag → CR-1核心/CR-2核心互通      │
                  │                                                │
                  │  VLAN 20 (接入面1): port1(tag)                  │
                  │    帧带 VLAN20 tag → CR-1接入/AP-1/TS 互通      │
                  │                                                │
                  │  VLAN 30 (接入面2): port1(tag)                  │
                  │    帧带 VLAN30 tag → CR-2接入/AP-2 互通         │
                  └────────────────────────────────────────────────┘

  说明:
  - 管理面 (VLAN 1) 的帧不打 tag, 直接走 ens37 本身
  - 核心面/接入面的帧分别打 VLAN 10/20/30 tag, 走 ens37.XX 子接口
  - 如果只有 1 台交换机, 管理面+数据面全走交换机 #2 (VLAN 隔离)
  - CS 的管理流量通过 ens34 (NAT, 仅限 VM 内部, 不经过交换机)
  - 或者 CS 也绑在 ens37 的 VLAN 1 上走交换机管理口
```

### 双交换机方案（加购第 2 个 Type-C 后）

```
                  Windows 笔记本
                  ┌─────────────────────────────────────┐
                  │  Linux VM                            │
                  │                                      │
                  │  ens37 (Type-C #1) ─── 交换机 #1     │
                  │    └── CS 管理面 (VLAN 1, untagged)   │
                  │    └── CR-1/CR-2 管理口 (VLAN 1)     │
                  │                                      │
                  │  ens38 (Type-C #2) ─── 交换机 #2     │
                  │    ├── VLAN 10: CR-1核心 + CR-2核心  │
                  │    ├── VLAN 20: CR-1接入 + AP-1 + TS │
                  │    └── VLAN 30: CR-2接入 + AP-2      │
                  └──────────┬──────────────┬───────────┘
                             │              │
                  ┌──────────┴──┐  ┌────────┴──────────┐
                  │ 交换机 #1   │  │    交换机 #2       │
                  │ (管理面)    │  │   (数据面 trunk)   │
                  │ 8口, access │  │ 口1 trunk          │
                  │ VLAN 1      │  │ VLAN 10/20/30      │
                  └─────────────┘  └───────────────────┘
```

### 交换机 #2 trunk 端口配置

```
端口模式: trunk
  允许 VLAN: 10, 20, 30
  入口规则: 保留 VLAN tag
  出口规则: 按 tag 转发到对应 VLAN

VLAN 间隔离:
  VLAN 10 ↔ VLAN 20: 通过 CR-1 的核心口↔接入口 完成（CR 内部转发）
  VLAN 10 ↔ VLAN 30: 通过 CR-2 的核心口↔接入口 完成（CR 内部转发）
  VLAN 20 ↔ VLAN 30: 不通（必须走 CR-1 → 核心面 → CR-2）
```

### 各角色在交换机上的分布

```
交换机 #2
┌─────────────────────────────────────────────┐
│                                             │
│  VLAN 10 (核心面, RID 帧)                    │
│    ens37.10 ─── CR-1 核心口                 │
│    ens37.10 ─── CR-2 核心口                 │
│    → CR 之间通过 RID 格式互相转发            │
│                                             │
│  VLAN 20 (接入面1, AID 帧)                   │
│    ens37.20 ─── CR-1 接入口                 │
│    ens37.20 ─── AP-1                        │
│    ens37.20 ─── TS                          │
│    → AP-1 的 AID 帧经 CR-1 接入侧进入核心面   │
│                                             │
│  VLAN 30 (接入面2, AID 帧)                   │
│    ens37.30 ─── CR-2 接入口                 │
│    ens37.30 ─── AP-2                        │
│    → AP-2 的 AID 帧经 CR-2 接入侧进入核心面   │
│                                             │
└─────────────────────────────────────────────┘
```

### 数据流完整路径

```
Host-1 ──lo──▶ AP-1 ──AID──▶ ens37.20 ──VLAN20──▶ CR-1接入口(ens37.20)
                                                      │
                                          CR-1 AID→RID 封装映射
                                                      │
                                          CR-1核心口(ens37.10) ──VLAN10──▶
                                                      │
                                          CR-2核心口(ens37.10) ◀──VLAN10──
                                                      │
                                          CR-2 RID→AID 解封
                                                      │
                                          CR-2接入口(ens37.30) ──VLAN30──▶
                                                      │
                                    TS ◀──AID── ens37.20 ◀──? 跨VLAN?

注意: TS 在 VLAN 20, CR-2 接入口在 VLAN 30.
      TS 的 RID 映射指向 CR-1 (本地), 所以 Host-1 → TS 的流量:
      CR-1 发现 TS 的 AID 映射在本 CR 下 → 直接通过 VLAN 20 发给 TS
      不需要经过 CR-2 和 VLAN 30.

      Host-1 → Host-2 的流量才需要跨 VLAN:
      AP-1(VLAN20) → CR-1 → VLAN10 → CR-2 → VLAN30 → AP-2(VLAN30) → Host-2
```

---

## 一、前提条件

```bash
# 1. SSH 登录
ssh ngit@192.168.80.222
cd /home/ngit/identifier-network-sim

# 2. 确认代码最新
git pull

# 3. 确认依赖已安装
sudo pip3 install loguru prometheus_client PyYAML

# 4. 确认网卡存在且 UP
ip link show ens34   # 管理面
ip link show ens37   # 数据面（Type-C 桥接）
# 状态应为 UP, LOWER_UP
```

---

## 二、无交换机模式（纯软件验证）

> 不涉及真实帧、不需要 root。直接用 asyncio.Queue 调通全部逻辑。

```bash
# 运行冒烟测试
sudo python3 scripts/real_simulation.py test

# 运行 HTTP 演示
sudo python3 scripts/real_simulation.py http

# 运行移动切换演示
sudo python3 scripts/real_simulation.py mobility
```

---

## 三、有交换机模式（真机部署）

### 3.1 创建 VLAN 子接口

```bash
# 创建 VLAN 子接口：ens37.10, ens37.20, ens37.30
sudo bash scripts/setup_vlan.sh setup

# 确认
ip -br link show | grep ens37
# 预期输出:
#   ens37       UP  ...
#   ens37.10@ens37  UP  ...
#   ens37.20@ens37  UP  ...
#   ens37.30@ens37  UP  ...
```

### 3.2 交换机配置

交换机对应端口配置为 **trunk 模式**，允许 VLAN 10、20、30 通过：

```
交换机 #2 port X → trunk, allow VLAN 10,20,30
```

如果两台交换机都在用，只需交换机 #2 配 trunk。

### 3.3 启动顺序

按依赖关系依次启动，每个角色在一个独立终端或后台运行：

```bash
# ==== 第 0 步：确认环境 ====
sudo bash scripts/setup_vlan.sh status

# ==== 第 1 步：启动 CS（控制平面） ====
sudo python3 scripts/real_deploy.py --role cs --config config/cs.yaml &
# 日志: [cs] running on ['ens34']

# ==== 第 2 步：启动 CR-1（核心路由器1） ====
sudo python3 scripts/real_deploy.py --role cr --config config/cr1.yaml &
# 日志: [cr] CR-1 tables: spaces=2 rid_routes=1 ... users=0 (initial)
#       [cr] running on ['ens34', 'ens37.10', 'ens37.20']

# ==== 第 3 步：启动 CR-2（核心路由器2） ====
sudo python3 scripts/real_deploy.py --role cr --config config/cr2.yaml &
# 日志: [cr] CR-2 tables: spaces=2 ... users=0 (initial)
#       [cr] running on ['ens34', 'ens37.10', 'ens37.30']

# ==== 第 4 步：启动 TS（测试服务器） ====
sudo python3 scripts/real_deploy.py --role ts --config config/ts.yaml &
# 日志: [ts] HTTP/FTP/Video servers + monitor ready
#       [ts] running on ['ens37']

# ==== 第 5 步：启动 AP-1 + AP-2 ====
sudo python3 scripts/real_deploy.py --role ap --config config/ap1.yaml &
# 日志: [ap] running on ['ens37']
sudo python3 scripts/real_deploy.py --role ap --config config/ap2.yaml &
# 日志: [ap] running on ['ens37']

# ==== 第 6 步：等 3 秒让控制面初始化 ====
sleep 3

# ==== 第 7 步：启动 Host-1 + Host-2（自动认证+发业务流量） ====
sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml &
sudo python3 scripts/real_deploy.py --role host --config config/host2.yaml &
# 日志: [host] running on ['wlan0']
#       [host] scenario done  → 自动退出
```

### 3.4 预期行为

Host 启动后会自动执行：
1. 向 CS 发起认证（通过 AP 代理）
2. 认证成功后，向 TS 发送 5 个 HTTP GET 请求
3. 所有请求完成后 Host 自动退出

TS 启动后：
1. 启动 HTTP/FTP/Video 服务
2. 启动实时监控面板（每 3 秒打印统计）
3. 向 CR-1 和 CR-2 发送 RID 转发探针

CR 启动后：
1. 打印全部 9 张表的状态
2. 持续监听接口，处理 AID/RID 帧
3. Ctrl+C 退出时打印最终用户状态数量

### 3.5 观察实时日志

```bash
# Host 认证和数据流
sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml
# 前台运行，直接看到:
#   [host] Auth request sent
#   [host] Auth response: OK
#   [host] GET /page_0.html → ...
#   [host] scenario done
```

### 3.6 验证数据流

```bash
# ==== 终端 A: 抓包 ====
# 在 ens37 上抓所有 VLAN 流量
sudo tcpdump -i ens37 -c 50 -XX | grep -E '0x1111|0x2222'

# 在 VLAN 子接口上分别抓
sudo tcpdump -i ens37.20 -c 20 -XX  # 接入面1 (AID 帧)
sudo tcpdump -i ens37.10 -c 20 -XX  # 核心面  (RID 帧)

# ==== 终端 B: 确认进程都在 ====
ps aux | grep real_deploy
# 应看到 8 个进程

# ==== 终端 C: 检查统计 ====
# TS 日志中的监控输出:
#   [TS Monitor] aid_rx=5 rid_rx=6 probes=3 flows=4 sent=... recv=...
```

### 3.7 停止

```bash
# 停止所有 real_deploy 进程
sudo pkill -f real_deploy

# 或逐个终端 Ctrl+C
```

### 3.8 清理 VLAN 子接口

```bash
sudo bash scripts/setup_vlan.sh teardown
```

---

## 四、启动顺序图解

```
   时间 ──────────────────────────────────────────────────▶

   ① CS ─────────────────────────────────────────────▶
         管理面就绪，等待 AP/CR 注册

   ② CR-1 ───────────────────────────────────────────▶
         核心面监听，转发就绪

   ③ CR-2 ───────────────────────────────────────────▶
         核心面监听，转发就绪

   ④ TS ─────────────────────────────────────────────▶
         HTTP/FTP/Video + 实时监控 + RID 探针

   ⑤ AP-1 + AP-2 ───────────────────────────────────▶
         WiFi 代理就绪

   sleep 3 ─

   ⑥ Host-1 ──▶ 认证 → HTTP请求×5 → 自动退出
   ⑥ Host-2 ──▶ 认证 → HTTP请求×5 → 自动退出
```

---

## 五、预期 TS 监控输出

```
[TS Monitor] aid_rx=5 rid_rx=6 probes=3 flows=4 sent=10pkt/14000B recv=10pkt/14000B
[TS Monitor] aid_rx=10 rid_rx=9 probes=6 flows=4 sent=15pkt/21000B recv=10pkt/14000B
```

| 字段 | 含义 |
|------|------|
| `aid_rx` | 收到 AID 帧数量（Host 的 HTTP 请求） |
| `rid_rx` | 收到 RID 帧数量（控制信令 + 探针） |
| `probes` | 收到探针包数量 |
| `flows` | 活跃流数量 |
| `sent/recv` | 发送/接收的数据包和字节数 |

---

## 六、常见问题

### Q1: `PermissionError: [Errno 1]` 在 AF_PACKET

```bash
# 确认用 sudo 运行
sudo python3 scripts/real_deploy.py ...
```

### Q2: NIC 不存在或状态 DOWN

```bash
ip link show ens37
# 如果 DOWN: sudo ip link set ens37 up
# 如果不存在: 检查 VMware 桥接设置 (Type-C 拓展坞)
```

### Q3: MAC 地址冲突

同一张网卡上多个角色绑不同 MAC 是正常的设计，不是冲突。

### Q4: Host 认证失败

确认 CS 已先启动，且 `config/cs.yaml` 中用户密码与 `config/host1.yaml` 一致。

### Q5: VLAN 子接口创建失败

```bash
# 检查内核是否支持 802.1Q
lsmod | grep 8021q
# 如果没有: sudo modprobe 8021q
```

---

## 七、扩展：多台物理机部署

当前所有角色在一台机器上。如果要分散到多台物理机：

```
机器 A (192.168.80.222)   机器 B (192.168.80.223)
├── CS                     ├── CR-1 + AP-1
├── TS                     └── CR-2 + AP-2
├── Host-1
└── Host-2
```

只需：
1. 每台机器克隆代码：`git clone https://github.com/rpatrick17-hue/identifier-network-sim.git`
2. 修改各机器上的 `config/*.yaml` 中的 MAC 地址（确保全局唯一）
3. 交换机端口分别接各机器的网卡
4. 按"CS → CR → TS → AP → Host"顺序启动
