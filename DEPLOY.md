# 标识网络模态 — 真实物理环境部署 & 验证方案

> 依据: 《多模态网络核心设备-标识网络模态验证方案》第四章 & 第五章

---

## 一、设备清单与拓扑

### 1.1 设备清单

| 序号 | 名称 | 数量 | 提供方 | 说明 |
|------|------|------|--------|------|
| 1 | 多模态网络核心路由器 (CR) | 6 台 | 中兴 | 原生支持标识模态，AID/RID 识别/封装/解封装/转发 |
| 2 | 服务器 | 2 台 | 北交大 | 1台CS (控制平面) + 1台TS (业务测试) |
| 3 | 用户终端 (Host) | 2 台 | 北交大 | 笔记本电脑，有线/无线双接口 |
| 4 | 无线接入设备 (AP) | ≥2 台 | 北交大 | Linux 工控机/服务器，运行 Python |
| 5 | 交换机 | 2 台 | 中兴 | 1台控制平面 + 1台数据平面 (含端口隔离) |

### 1.2 物理拓扑

```
                        ┌──────────────┐
                        │ 北交大 CS     │  (服务器, Python)
                        │ AAA+映射+路由  │
                        └──────┬───────┘
                               │ 管理口
                 ┌─────────────┴─────────────────┐
                 │    交换机 #1: 控制平面 (中兴)   │
                 │    CS + CR1~6 管理口互联        │
                 └─────────────┬─────────────────┘
                               │
        ┌──────────────────────┼──────────────────────────┐
        │           交换机 #2: 数据平面 (中兴)              │
        │                                                  │
        │   VLAN 10: 核心面 — CR1~6 核心口互联 (RID 格式)    │
        │   VLAN 20: 接入面 — CR-1/AP-1/TS/Host-1          │
        │   VLAN 30: 接入面 — CR-2/AP-2/Host-2             │
        │   端口隔离: AP↔CR 绑定对, AP 之间不通              │
        └──┬───────┬───────┬───────┬───────┬───────┬──────┘
           │       │       │       │       │       │
       ┌───┴──┐┌───┴──┐┌───┴──┐┌───┴──┐┌───┴──┐┌───┴──┐
       │ CR-1 ││ CR-2 ││ CR-3 ││ CR-4 ││ CR-5 ││ CR-6 │  中兴硬件
       │2-3口 ││2-3口 ││2-3口 ││2-3口 ││2-3口 ││2-3口 │
       └──┬───┘└──┬───┘└──────┘└──────┘└──────┘└──────┘
          │       │
     ┌────┴─┐ ┌──┴─────┐
     │ AP-1 │ │  AP-2  │  北交大 Linux (Python)
     │  TS  │ │ Host-2 │
     │Host-1│ │        │
     └──────┘ └────────┘
```

---

## 二、部署前准备 (文档 §4.1)

### 2.1 交换机配置

#### 交换机 #1: 控制平面

```
功能: CS 与所有 CR 的管理口互联
配置: 普通 L2 转发, 无需端口隔离
端口: CS(1) + CR1~6 管理口(6) = 至少 7 口
```

#### 交换机 #2: 数据平面

```
功能: 核心面 + 接入面, 通过 VLAN 隔离
端口: CR1~6 核心口(6) + CR1~6 接入口(6) + AP1~2(2) + TS(1) + Host1~2(2) = 至少 17 口

VLAN 10 (核心面):
  成员: CR-1 核心口, CR-2 核心口, ..., CR-6 核心口
  规则: 所有端口互通 (无隔离)

VLAN 20 (接入面1, CR-1 侧):
  成员: CR-1 接入口, AP-1, TS, Host-1
  端口隔离:
    组A: CR-1 接入口 ↔ AP-1
    组B: CR-1 接入口 ↔ TS
    组C: AP-1 ↔ Host-1
    (AP-1 不能直接通 TS, 必须经 CR-1)

VLAN 30 (接入面2, CR-2 侧):
  成员: CR-2 接入口, AP-2, Host-2
  端口隔离:
    组A: CR-2 接入口 ↔ AP-2
    组B: AP-2 ↔ Host-2
```

### 2.2 中兴 CR 初始配置 (文档 §4.1.1)

每台 CR 出厂后, 需通过管理口或 Console 配置以下表项。

#### (1) 接口信息表

| 接口 | 名称 | 类型 | 连接目标 |
|------|------|------|---------|
| 口1 | 管理口 | ROUTE | 交换机 #1 (控制平面) |
| 口2 | 核心口 | ROUTE | 交换机 #2 VLAN 10 (核心面) |
| 口3 | 接入口 | ACCESS | 交换机 #2 VLAN 20/30 (接入面) |

以 CR-1 为例:
```
接口索引 1: Eth0, MAC=00:18:54:FD:29:01, 状态=UP, 类型=ROUTE  (管理)
接口索引 2: Eth1, MAC=00:0C:AB:1E:76:8A, 状态=UP, 类型=ROUTE  (核心)
接口索引 3: Eth2, MAC=00:0C:AB:1E:76:8B, 状态=UP, 类型=ACCESS (接入)
```

#### (2) RID 空间表

每台 CR 至少配置:
```
空间 0:   (10028|20, 36181|20) — 管理面
空间 100: (12345|20, 34267|24) — 默认数据空间
空间 204: (3523|30,  12578|28) — 高级映射 (按需)
```

#### (3) CR 自身 RID

```
CR-1: RID(10001, 36191)   CR-2: RID(12360, 34280)
CR-3: RID(10030, 36190)   CR-4: RID(12365, 34282)
CR-5: RID(3540,  12768)   CR-6: RID(3545,  12770)
CS:   RID(10028, 36181)   (管理面内)
```

#### (4) 邻居信息

**路由空间邻居 (核心面):**
以 CR-1 为例:
```
空间 100: 邻居 RID(12360,34280), MAC=00:0C:AB:1E:76:8C, 接口=核心口
空间 100: 邻居 RID(10030,36190), MAC=..., 接口=核心口
...
```

**接入空间邻居 (接入面):**
以 CR-1 为例:
```
邻居 AID(8d969eef...86cf), MAC=00:04:AB:1F:40:A6, 接口=接入口  (AP-1)
邻居 AID(d3c29a3a...6eca), MAC=00:1A:2B:3C:4D:02, 接口=接入口  (TS)
```

#### (5) 路由信息

**RID 路由表 (核心面, 空间 100):**
以 CR-1 为例:
```
目的地 (12345|20, 34267|24) → 下一跳 RID(12360,34280)   [去 CR-2]
目的地 (10028|20, 36181|20) → 下一跳 RID(10030,36190)   [去 CR-3->CS]
```

**AID 路由表 (接入面):**
以 CR-1 为例 (静态预置 AP/TS 的 AID):
```
目的地 AID(AP-1) → 下一跳 AID(AP-1)   [本地直连]
目的地 AID(TS)   → 下一跳 AID(AP-1)   [经 AP-1]
```

#### (6) 映射信息

**本地映射 (CR-1 侧的设备):**
```
AP-1 的 AID  → 映射 RID(10001,36191),  空间 0
Host-1的AID  → 映射 RID(10001,36191),  空间 100
TS 的 AID    → 映射 RID(10003,36193),  空间 100
```

**远端映射 (其他 CR 侧的设备, CR-2 为例):**
```
Host-2的AID  → 映射 RID(10002,36192), 远端CR=RID(12360,34280)
```

#### (7) 关联 AP 列表 & 用户状态列表

初始为空, 用户上线后由 AP 通过 CS 动态更新。

### 2.3 北交大设备初始配置 (Python 部署)

#### CS (控制平面服务器)

配置内容 (文档 §4.1.3):
```
- 本机 RID: (10028, 36181)
- 管理网卡: 连交换机 #1
- 预注册用户: Zhangsan (PIN=1234, UR:3, BW:10Mbps)
              Lisi     (PIN=0000, UR:2, BW:5Mbps)
- 管理 CR 列表: CR1~6 的 RID
- AP→CR 映射: AP-1→CR-1, AP-2→CR-2
```

部署命令:
```bash
cd /opt/identifier-network-sim
sudo python3 scripts/real_deploy.py --role cs --config config/cs.yaml
```

#### AP (无线接入设备)

配置内容 (文档 §4.1.2):
```
- 本机 AID: 8d969eef6ecad3c29a3a629280e686cf
- 本机 RID: (10001, 36191)
- CS 的 RID + MAC
- 关联 CR 的 RID + MAC (接入接口)
- WiFi: SSID="ID-Network-1", 频率=2.4GHz
- 本地区域用户: Host-1 的 AID/IP/MAC
```

部署命令 (每台 AP):
```bash
sudo python3 scripts/real_deploy.py --role ap --config config/ap1.yaml
```

#### TS (业务测试服务器)

配置内容 (文档 §4.1.4 部分):
```
- 本机 AID: d3c29a3a629280e686cf8d969eef6eca
- 本机 RID: (10003, 36193)
- 接入网卡: 连交换机 #2 VLAN 20
- 部署 HTTP 服务 (页面浏览)
- 部署 FTP 服务 (文件下载)
- 部署视频流服务
- 网络性能测试工具 (带宽/时延/抖动)
- 标识数据包构建和收发监测工具
```

部署命令:
```bash
sudo python3 scripts/real_deploy.py --role ts --config config/ts.yaml
```

#### Host (用户终端)

配置内容 (文档 §4.1.4):
```
- IP: 192.168.1.100/24, 网关: 192.168.1.1
- 连接 AP-1 (SSID: "ID-Network-1")
- AID 认证配置文件: cad3c29a3a629280e686cf8d969eef6e
- 用户名: Zhangsan, 密码: 123
- 浏览器/curl (HTTP), FTP 客户端, 视频播放器
```

部署命令:
```bash
sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml
```

---

## 三、验证项目 (文档 §4.2)

### 验证 1: 标识组网 — CR 转发功能 (文档 §4.2.1)

**目的:** 验证 CR 在核心网内能识别并转发 RID 数据包。

**操作步骤:**

```bash
# ==== 终端 A: 交换机镜像口抓包 (核心面 VLAN 10) ====
ssh root@<数据交换机IP>
monitor session 1 source interface <CR-1核心口> both
monitor session 1 destination interface <镜像口>
# 在镜像口连接的笔记本上:
tcpdump -i eth0 -XX -w /tmp/cr_forwarding.pcap &
# 另一个终端实时查看:
tcpdump -i eth0 -XX | grep -E '0x88b6|0x88b5'

# ==== 终端 B: TS 服务器 ====
ssh ngit@<TS_IP>
cd /opt/identifier-network-sim
# 启动 TS (含 RID 探测发包功能)
sudo python3 scripts/real_deploy.py --role ts --config config/ts.yaml
# TS 启动后自动:
#  1. 构建 RID 探测包: PROBE:TS->CR-2:seq=1
#  2. 通过 AF_PACKET 注入 CR-1 核心口
#  3. 每 2 秒发一次, 共发 10 个

# ==== 终端 C: CR-1 debug (可选, 如果中兴提供 debug 接口) ====
ssh admin@<CR-1_管理IP>
show rid-routes              # 查看 RID 路由表
show rid-neighbors           # 查看核心邻居
show interface statistics    # 查看接口收发统计
debug rid-packet             # 开启 RID 包调试
```

**抓包验证:**
```bash
# 停止抓包后分析
tcpdump -r /tmp/cr_forwarding.pcap 'ether proto 0x88b6' | head -20
# 预期看到多条:
#   TS_MAC > CR-2_MAC, ethertype RID (0x88b6), length 80
#   含 payload: PROBE:TS->CR-2:seq=1

# 确认 RID 包结构正确 (24字节包头)
tcpdump -r /tmp/cr_forwarding.pcap 'ether proto 0x88b6' -XX | head -40
```

**预期结果:**
- ✅ 抓包可见 EtherType=0x88B6 的 RID 帧
- ✅ CR-1 成功按二维前缀乘积匹配转发到 CR-2
- ✅ 所有 CR 间双向可达 (发探包到每台 CR)

---

### 验证 2: 用户注册 (文档 §4.2.2)

**目的:** 验证用户注册流程, AID 由用户属性生成。

**操作步骤:**

```bash
# ==== 终端 A: CS 服务器 ====
ssh ngit@<CS_IP>
cd /opt/identifier-network-sim
# CS 启动时 config/cs.yaml 中已预注册用户, 查看日志确认:
sudo python3 scripts/real_deploy.py --role cs --config config/cs.yaml 2>&1 | tee /tmp/cs.log
# 预期日志输出:
#   registered user: Zhangsan → AID(102b8dd2…)
#   registered user: Lisi     → AID(825873a2…)

# 手动验证 AID 生成:
python3 -c "
from src.common.utils import generate_aid
from src.common.addressing import AID
a1 = generate_aid('Zhangsan', '1234', 'device01')
a2 = generate_aid('Zhangsan', '1234', 'device01')
a3 = generate_aid('Lisi', '0000', 'device02')
print(f'Zhangsan AID: {a1.hex()}')
print(f'Zhangsan AID: {a2.hex()}   ← 完全相同的AID (确定性)')
print(f'Lisi AID:     {a3.hex()}   ← 不同用户不同AID')
print(f'长度: {len(a1)} bytes (128bit)')
"

# (可选) 在线注册新用户: Host 侧发起
# Host 通过 AP 向 CS 注册, CS 收到后自动生成 AID 入库
```

**预期结果:**
- ✅ 相同输入产生相同 AID (SHA-256 确定性)
- ✅ 不同输入产生不同 AID (防碰撞)
- ✅ AID = 128bits = 16 字节
- ✅ PIN 码和定制属性 (UR/BW) 正确存储

---

### 验证 3: 用户登录 (文档 §4.2.3)

**目的:** 验证首次认证和快速认证。

**操作步骤:**

```bash
# ==== 终端 A: 管理面抓包 ====
ssh root@<数据交换机IP>
tcpdump -i <管理VLAN镜像口> -XX -w /tmp/auth.pcap &
# 实时过滤控制信令:
tcpdump -i <管理VLAN镜像口> 'ether proto 0x88b6' -XX | grep -A5 'AUTH'

# ==== 终端 B: CS 服务器 ====
sudo python3 scripts/real_deploy.py --role cs --config config/cs.yaml

# ==== 终端 C: AP-1 ====
sudo python3 scripts/real_deploy.py --role ap --config config/ap1.yaml

# ==== 终端 D: Host-1 (首次认证) ====
sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml
# 预期日志:
#   [host] Auth request sent
#   [ap] proxy-auth: Zhangsan → CS
#   [cs] auth OK: Zhangsan
#   [host] Auth response: OK

# ==== 终端 D: Host-1 (错误密码测试) ====
# 修改 config/host1.yaml 中 password 为 "wrong", 重新启动
sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml
# 预期日志:
#   [cs] auth FAIL: Zhangsan
#   [host] Auth response: FAIL

# ==== 终端 D: Host-1 (快速认证) ====
# 改回正确密码, 再次重启 Host-1
sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml
# 预期日志:
#   [ap] fast-auth: Zhangsan found in neighbour cache  ← 跳过CS
#   [host] Auth response: OK
```

**抓包验证:**
```bash
tcpdump -r /tmp/auth.pcap 'ether proto 0x88b6' -XX | grep -B2 -A10 'AUTH'
# 预期: EtherType=0x88B6, DataType=0x01, payload 含 AuthRequest/Response
```

**预期结果:**
- ✅ 正确密码: 认证通过, CS 返回 success=True
- ✅ 错误密码: CS 拒绝, Host 收到 success=False
- ✅ 快速认证: AP 缓存命中, 不经过 CS
- ✅ 控制信令使用 EtherType=0x88B6 + DataType=0x01

---

### 验证 4: 用户互通 (文档 §4.3)

**目的:** 验证完整的 IPv4→AID→RID→AID→IPv4 数据流。

**操作步骤:**

```bash
# ==== 终端 A: 双面抓包 ====
ssh root@<数据交换机IP>
# 接入面 (VLAN 20):
tcpdump -i <接入VLAN镜像口> -XX -w /tmp/access.pcap &
# 核心面 (VLAN 10):
tcpdump -i <核心VLAN镜像口> -XX -w /tmp/core.pcap &

# ==== 终端 B: CS, AP, TS 已在运行 ====

# ==== 终端 C: Host-1 发起 HTTP 请求 ====
sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml
# Host 认证成功后自动执行:
#   GET /page_0.html → TS
#   GET /page_1.html → TS
#   GET /page_4.html → TS

# ==== 终端 D: 性能测试 ====
watch -n 1 'ifconfig enp2s0 | grep "RX packets\|TX packets"'
# 或 iperf3:
# TS: iperf3 -s
# Host: iperf3 -c <TS_IP> -t 30
```

**抓包验证:**
```bash
# 1. 接入面: 应只看到 AID 帧 (0x88B5)
tcpdump -r /tmp/access.pcap 'ether proto 0x88b5' | wc -l
tcpdump -r /tmp/access.pcap 'ether proto 0x88b5' -XX | head -60

# 2. 核心面: 应只看到 RID 帧 (0x88B6)
tcpdump -r /tmp/core.pcap 'ether proto 0x88b6' | wc -l
tcpdump -r /tmp/core.pcap 'ether proto 0x88b6' -XX | head -40

# 3. 确认格式隔离
tcpdump -r /tmp/access.pcap 'ether proto 0x88b6' | wc -l  # 预期: 0
tcpdump -r /tmp/core.pcap 'ether proto 0x88b5' | wc -l      # 预期: 0

# 4. 跨 CR 通信
# Host-1 → Host-2 (修改 target_aid 为 Host-2 的 AID)
tcpdump -r /tmp/core.pcap 'ether proto 0x88b6 and ether dst <CR-2_MAC>' | head
```

**预期结果:**
- ✅ 接入面 (VLAN 20): 仅见 AID 帧 (EtherType=0x88B5)
- ✅ 核心面 (VLAN 10): 仅见 RID 帧 (EtherType=0x88B6)
- ✅ RID 包内封装完整 AID 包 (嵌套封装正确)
- ✅ Host 正常收到 HTTP 响应
- ✅ 带宽/时延/抖动统计正常

---

### 验证 5: 移动切换 (文档 §4.4)

**目的:** 验证四种切换场景 — 主动发送/接收 + 被动接收(旧CR重定向)。

**操作步骤:**

```bash
# ==== 前置: CS + CR + TS + AP-1 + AP-2 全部运行中 ====

# ==== 终端 A: 抓包 ====
ssh root@<数据交换机IP>
tcpdump -i <核心VLAN镜像口> -XX -w /tmp/mobility_core.pcap &
tcpdump -i <管理VLAN镜像口> -XX -w /tmp/mobility_mgmt.pcap &

# ==== 终端 B: Host-1 在 AP-1 下 (场景1&2: 切换前) ====
sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml

# ==== 终端 C: 模拟切换 (Host-1 AP-1 → AP-2) ====
# 方式1: 停止 Host-1, 修改配置指向 AP-2, 重新启动
# 方式2: Host 切换 WiFi 到 AP-2 的 SSID

# AP-2 检测到新连接 → 自动激活用户
tail -f /tmp/ap2.log | grep -E 'activate|mapping|neighbour'

# CS 日志:
tail -f /tmp/cs.log | grep -E 'registered|propagated'

# CR 状态检查 (如果中兴提供):
show user-status AID(102b8dd2…)
# CR-1: MOVED_AWAY  |  CR-2: ONLINE

# ==== 终端 B: Host-1 从新位置发数据 (场景3) ====
sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml

# ==== 终端 D: Host-2 向 Host-1 发数据 (场景4: 被动接收) ====
# Host-2 仍用旧映射 → CR-2封装RID发往CR-1 → CR-1发现MOVED_AWAY → 重定向
sudo python3 scripts/real_deploy.py --role host --config config/host2.yaml
# 查看 CR-1 日志:
# "User AID(…) moved away – redirecting"
# "MobilityAlert → CS"

# CS 日志:
# "mobility alert: AID(…) moved RID(…→…)"
# "mobility propagated to 6 CRs"
```

**抓包验证:**
```bash
# 核心面: 同一AID包出现两次
tcpdump -r /tmp/mobility_core.pcap 'ether proto 0x88b6' -XX | grep -B2 -A10 'MOVED'
# 第一次: CR-2 → CR-1 (远端旧映射)
# 第二次: CR-1 → CR-2 (CR-1重定向)

# 管理面: MobilityAlert 控制信令
tcpdump -r /tmp/mobility_mgmt.pcap 'ether proto 0x88b6' -XX | grep -A5 'mobility'
```

**预期结果:**
- ✅ 切换后主动发包正常 (场景3)
- ✅ 被动接收成功, CR-1 重定向 (场景4)
- ✅ CR-1: MOVED_AWAY, CR-2: ONLINE
- ✅ CS 映射更新且全局传播
- ✅ MobilityAlert 正确触发

---

## 四、部署操作手册

### 4.1 环境准备 (一次性)

```bash
# 每台北交大 Linux 设备上执行
cd /opt
git clone <repo-url> identifier-network-sim
cd identifier-network-sim
pip3 install -r requirements.txt

# 确认网卡名称
ip link show
# 根据实际网卡名修改 config/*.yaml 中的 interfaces.name
```

### 4.2 启动顺序

```
1. 交换机上电, 确认 VLAN 和端口隔离已配置
2. 中兴 CR 上电, 确认 §2.2 配置已生效
3. CS 启动:
     sudo python3 scripts/real_deploy.py --role cs --config config/cs.yaml
4. TS 启动:
     sudo python3 scripts/real_deploy.py --role ts --config config/ts.yaml
5. AP 启动 (每台):
     sudo python3 scripts/real_deploy.py --role ap --config config/ap1.yaml
6. Host 启动:
     sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml
```

### 4.3 抓包验证

```bash
# 过滤 AID 帧
tcpdump -r /tmp/access.pcap 'ether proto 0x88b5'

# 过滤 RID 帧
tcpdump -r /tmp/core.pcap 'ether proto 0x88b6'

# 过滤 RID 控制信令
tcpdump -r /tmp/core.pcap 'ether proto 0x88b6 and ether[20:1]=0x01'
```

---

## 五、代码部署清单

| 文件 | 部署位置 | 说明 |
|------|---------|------|
| `scripts/real_deploy.py` | CS/AP/TS/Host | 真机部署入口 |
| `config/cs.yaml` | CS | CS 配置 |
| `config/ap1.yaml` `config/ap2.yaml` | AP-1, AP-2 | AP 配置 |
| `config/ts.yaml` | TS | TS 配置 |
| `config/host1.yaml` `config/host2.yaml` | Host-1, Host-2 | Host 配置 |
| `src/` (全部) | 所有设备 | 协议栈代码 |
| 中兴 CR | 仅配置, 不部署代码 | 表项配置 |

**不需要部署的:**
- `simulation.py` `real_simulation.py` — 纯软件仿真, 真机不用
- `test_*.py` — 测试脚本
- `verify.py` `visualize.py` — 验证工具
- `setup_netns.sh` — veth 环境, 真机不用
