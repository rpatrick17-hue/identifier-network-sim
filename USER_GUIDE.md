   # 标识网络模态仿真验证系统 — 使用教程

> **适用对象**：完全未接触过本项目的开发者 / 测试人员
>
> **前置知识**：了解 Python 基础语法即可，不需要网络协议背景

---

## 目录

1. [这个项目是做什么的](#1-这个项目是做什么的)
2. [核心概念速览](#2-核心概念速览)
3. [项目结构一览](#3-项目结构一览)
4. [环境准备](#4-环境准备)
5. [5 分钟快速体验](#5-5-分钟快速体验)
6. [运行所有测试](#6-运行所有测试)
7. [运行演示场景](#7-运行演示场景)
8. [配置文件说明](#8-配置文件说明)
9. [各组件功能速查](#9-各组件功能速查)
10. [常见问题排查](#10-常见问题排查)
11. [二次开发指南](#11-二次开发指南)

---

## 1. 这个项目是做什么的

本工程实现了一套**标识网络（Identifier Network）仿真验证系统**。

### 一句话解释

传统互联网用 IP 地址既表示"你是谁"又表示"你在哪里"，导致安全和移动性问题。
标识网络把这二者分开：

```
传统网络：  IP = 身份 + 位置  （混在一起）
标识网络：  AID = 身份        （你是谁）
           RID = 位置        （你在哪里）
           中间通过"映射"关联
```

### 系统做什么

- **控制面（Control Plane）**：用户认证、标识映射管理、路由配置
- **数据面（Data Plane）**：用户数据被自动封装成 AID→RID→AID 在核心网中转发
- **移动切换**：用户移动到新位置时，旧设备自动重定向数据到新位置

### 仿真规模

| 设备类型 | 数量 | 角色 |
|---------|------|------|
| 核心路由器 (CR) | 6 台 | 核心数据转发，AID↔RID 封装/解封装 |
| 控制服务器 (CS) | 1 台 | AAA 认证 + 映射服务 + 路由管理 |
| 无线接入设备 (AP) | 2 台 | 认证代理，传统 IP→AID 转换 |
| 业务测试服务器 (TS) | 1 台 | HTTP/FTP/Video 服务 + 性能监测 |
| 用户终端 (Host) | 2 台 | 带认证客户端的普通终端 |
| 网络交换机 (SW) | 2 台 | 控制面 + 数据面（含端口隔离） |

---

## 2. 核心概念速览

### 2.1 两种标识

```
接入标识 (AID)
├── 长度: 128 位 (16 字节)
├── 生成: 用户名+PIN+设备ID → SHA-256 → 截取前128位
├── 作用: 代表"用户身份"，接入网络后不变
└── 示例: cad3c29a3a629280e686cf8d969eef6e

路由标识 (RID)
├── 长度: 64 位 (32位X坐标 | 32位Y坐标)
├── 配置: 管理员静态分配
├── 作用: 代表"网络位置"，用于核心网路由转发
└── 示例: RID(10001, 36191) —— X=10001, Y=36191
```

### 2.2 两种数据包

```
AID 数据包 (工作在接入网)
┌────┬────┬────┬──────┬──────┬────┬────┬──────────┬──────────┬─────────┐
│版本│类型│QoS │保留位│载荷长│数据│TTL │源AID     │目的AID   │Payload  │
│4b  │4b  │8b  │16b   │度16b │类型│8b  │128b      │128b      │(IPv4/6) │
│    │    │    │      │      │8b  │    │          │          │         │
└────┴────┴────┴──────┴──────┴────┴────┴──────────┴──────────┴─────────┘
包头: 40 字节                          │←── 源AID(16B) ──│←── 目的AID(16B) ──│

RID 数据包 (工作在核心网)
┌────┬────┬────┬──────┬──────┬────┬────┬──────────┬──────────┬─────────┐
│版本│类型│QoS │空间ID│载荷长│数据│TTL │目的RID   │源RID     │Payload  │
│4b  │4b  │8b  │16b   │度16b │类型│8b  │64b       │64b       │(AID包)  │
│    │    │    │      │      │8b  │    │          │          │         │
└────┴────┴────┴──────┴──────┴────┴────┴──────────┴──────────┴─────────┘
包头: 24 字节                          │← 目的RID(8B) ──│← 源RID(8B) ──│
```

### 2.3 数据转发流程

```
Host-1 发送 IPv4 数据给 Host-2:
                                   
  Host-1 ──IPv4──▶ AP-1 ──AID包──▶ CR-1 ──RID包──▶ CR-2 ──AID包──▶ AP-2 ──IPv4──▶ Host-2
                    ▲                ▲   ▲                              ▲
                    │                │   │                              │
               AID封装        AID→RID映射  RID二维路由       RID解封装→AID
```

### 2.4 RID 路由算法：二维前缀乘积匹配

```
RID 坐标 = (X, Y) 二维网格

路由表项:  ( X|M1 , Y|M2 ) → 下一跳RID
           └──┬──┘ └──┬──┘
          X的M1位前缀  Y的M2位前缀

匹配规则: 在所有匹配的表项中，选择 M1×M2 乘积最大的
示例:
  表项A: (12345|20, 34267|24) → 乘积=480
  表项B: (12345|22, 34267|26) → 乘积=572  ← 胜出（更精确）
```

---

## 3. 项目结构一览

```
identifier-network-sim/
│
├── USER_GUIDE.md                  ← 📖 你正在阅读的文件
├── requirements.txt               ← Python 依赖列表
│
├── config/
│   └── topology.yaml              ← 🔧 拓扑配置：定义12个节点+链路+路由
│
├── scripts/
│   └── run.py                     ← 🚀 主入口 (基于YAML拓扑启动)
│
├── src/
│   ├── common/                    ← 🧱 基础层
│   │   ├── constants.py           ←   版本号、枚举定义、包头长度
│   │   ├── addressing.py          ←   AID(128bit) / RID(64bit) 地址类
│   │   ├── packets.py             ←   AIDPacket / RIDPacket 结构体
│   │   ├── serializer.py          ←   struct 二进制序列化
│   │   ├── ethernet.py            ←   以太网帧封装 (自定义EtherType)
│   │   └── utils.py               ←   日志、哈希、性能指标收集器
│   │
│   ├── tables/                    ← 📊 内存表定义
│   │   ├── cr_tables.py           ←   CR 的 9 张表 (接口/空间/邻居/路由/映射/用户...)
│   │   └── cs_tables.py           ←   CS 的用户注册数据库
│   │
│   ├── routing/                   ← 🧭 路由算法
│   │   ├── rid_routing.py         ←   RID 二维前缀乘积路由
│   │   ├── aid_routing.py         ←   AID 精确匹配路由
│   │   └── mapping.py             ←   AID↔RID 映射管理
│   │
│   ├── control_plane/             ← ✉️ 控制信令
│   │   └── signaling.py           ←   8 种控制消息 (认证/映射/移动/路由)
│   │
│   ├── nodes/                     ← 🖥️ 5 种网络节点
│   │   ├── base_node.py           ←   所有节点的异步基类
│   │   ├── core_router.py         ←   核心路由器 (AID↔RID 转发)
│   │   ├── access_point.py        ←   无线接入设备 (认证代理)
│   │   ├── control_server.py      ←   控制平面服务器 (AAA+映射+路由)
│   │   ├── test_server.py         ←   业务测试服务器 (HTTP/FTP/Video)
│   │   └── host.py                ←   用户终端 (认证客户端)
│   │
│   └── simulation/                ← 🎮 仿真引擎
│       ├── virtual_link.py        ←   虚拟链路 (延迟/丢包) + 虚拟交换机 (端口隔离)
│       ├── topology.py            ←   拓扑构建器 (从 YAML 创建全部节点)
│       ├── orchestrator.py        ←   仿真编排器 (启停/统计)
│       └── monitor.py             ←   实时性能监控面板
│
├── scenarios/                     ← 🎬 演示场景
│   ├── run_demo.py                ←   独立演示运行器 (最常用)
│   ├── http_demo.py               ←   HTTP 浏览场景
│   ├── ftp_demo.py                ←   FTP 下载场景
│   ├── video_demo.py              ←   视频流场景
│   └── mobility_handover.py       ←   移动切换场景
│
└── tests/                         ← 🧪 测试套件 (56 个测试)
    ├── test_packets.py            ←   包序列化测试 (22 个)
    ├── test_cr_routing.py         ←   路由算法测试 (15 个)
    ├── test_integration.py        ←   集成测试 (11 个)
    ├── test_smoke.py              ←   冒烟测试 (3 个)
    └── test_e2e_forwarding.py     ←   端到端+移动性测试 (5 个)
```

---

## 4. 环境准备

### 4.1 系统要求

| 要求 | 最低版本 |
|------|---------|
| 操作系统 | Linux / macOS / Windows |
| Python | 3.10+ |
| pip | 22.0+ |

### 4.2 安装步骤

```bash
# 1. 克隆或复制项目到本地
cd /path/to/identifier-network-sim

# 2. 安装依赖
pip install -r requirements.txt

# 3. 验证安装
python3 -c "from src.common.addressing import AID; print('OK')"
```

### 4.3 依赖列表

```
PyYAML>=5.4           # 配置文件解析
loguru>=0.7.0         # 结构化日志
prometheus_client>=0.20.0  # 性能指标
click>=8.0.0          # 命令行接口
pytest>=6.0.0         # 测试框架
pytest-asyncio>=0.21.0  # 异步测试支持
```

---

## 5. 5 分钟快速体验

### 第一步：运行所有测试

```bash
cd identifier-network-sim

# 运行全部测试（56个）
python3 -m pytest tests/ -v -k 'not test_topology_start_stop'
```

你应该看到：
```
tests/test_packets.py ............                                 [39%]
tests/test_cr_routing.py ...............                           [66%]
tests/test_integration.py ...........                              [85%]
tests/test_e2e_forwarding.py .....                                 [94%]
tests/test_smoke.py ...                                            [100%]

56 passed in 4.0s
```

### 第二步：运行 HTTP 浏览演示

```bash
python3 scenarios/run_demo.py http
```

预期输出：
```
============================================================
  HTTP Browsing Demo: Host-1 → Test Server
============================================================
  Host-1 authenticated | TS ready: 5 pages × 4KB
  GET /page_0.html → 0.1ms
  GET /page_1.html → 0.2ms
  GET /page_2.html → 0.1ms
  GET /page_3.html → 0.2ms
  GET /page_4.html → 0.1ms
  TS  recv: 10 pkts / 750B
  Host sent: 5 pkts
```

### 第三步：运行移动切换演示

```bash
python3 scenarios/run_demo.py mobility
```

预期输出：
```
============================================================
  Mobility Handover Demo: Host-1 AP-1 → AP-2
============================================================
  Phase 1: Host-1 on AP-1 (CR-1)
  Phase 2: Host-1 moves AP-1 → AP-2 (CR-2)
  Phase 3: Host-1 sends from new location
  CR-1: Host=MOVED_AWAY
  CR-2: Host=ONLINE
```

### 更多演示

```bash
python3 scenarios/run_demo.py ftp       # FTP 下载
python3 scenarios/run_demo.py video     # 视频流
python3 scenarios/run_demo.py all       # 全部串行
```

---

## 6. 运行所有测试

### 6.1 测试分类

```bash
# 只运行包序列化测试
python3 -m pytest tests/test_packets.py -v

# 只运行路由算法测试
python3 -m pytest tests/test_cr_routing.py -v

# 只运行集成测试
python3 -m pytest tests/test_integration.py -v

# 只运行端到端转发测试
python3 -m pytest tests/test_e2e_forwarding.py -v

# 只运行冒烟测试
python3 -m pytest tests/test_smoke.py -v
```

### 6.2 理解测试输出

```
tests/test_cr_routing.py::TestRIDRouting::test_exact_match PASSED  [  1%]
                                  │              │            │
                                  │              │            └── 结果 (PASSED/FAILED/SKIPPED)
                                  │              └── 测试方法名
                                  └── 测试类名
```

### 6.3 测试覆盖了什么

| 测试文件 | 数量 | 验证内容 |
|---------|------|---------|
| `test_packets.py` | 22 | AID/RID 地址创建、包序列化/反序列化、以太网帧封装、TTL、结构体校验 |
| `test_cr_routing.py` | 15 | RID 二维前缀乘积匹配、AID 路由、映射 CRUD、用户状态管理 |
| `test_integration.py` | 11 | 完整拓扑加载、CR 配置、虚拟链路收发/广播/延迟/丢包、交换机端口隔离 |
| `test_e2e_forwarding.py` | 5 | 端到端 AID→RID→AID 全流程、双向转发、移动切换重定向、告警触发 |
| `test_smoke.py` | 3 | CR↔CR 实时转发、Host-AP-CR 链路、TTL 防环 |

---

## 7. 运行演示场景

### 7.1 演示运行器用法

`scenarios/run_demo.py` 是最常用的入口，会**自动构建拓扑、启动节点、运行场景、停止并报告**。

```bash
# 语法
python3 scenarios/run_demo.py [场景名]

# 场景名可选:
#   http      - HTTP 页面浏览
#   ftp       - FTP 文件下载
#   video     - 视频流
#   mobility  - 移动切换
#   all       - 全部串行运行 (默认)
```

### 7.2 各场景说明

#### HTTP 浏览演示 (`http`)

验证**传统 HTTP 流量在标识网络隧道中透明传输**。

```
Host-1 发送5个 GET 请求 → AID封装 → RID封装 → 核心转发 → 解封装 → TS 接收
```

#### FTP 下载演示 (`ftp`)

验证**大文件在标识网络中的下载**。

```
Host-1 请求3个文件 → 每个200KB → 通过 AID/RID 隧道传输
```

#### 视频流演示 (`video`)

验证**持续视频流的传输性能和吞吐量**。

```
Host-2 请求视频流 → TS 发送20个50KB块 → 统计吞吐量(Mbps)
```

#### 移动切换演示 (`mobility`)

验证**用户从 AP-1 移动到 AP-2 后的数据重定向**。

```
Phase 1: Host-1 在 AP-1 → 正常通信
Phase 2: Host-1 切换到 AP-2 → CR-1 标记为"移走"
Phase 3: Host-1 从新位置发送数据 → 正常通信
```

---

## 8. 配置文件说明

### 8.1 拓扑配置 (`config/topology.yaml`)

这是系统最重要的配置文件，定义了：

```yaml
switches:              # 交换机定义 (含端口隔离规则)
nodes:
  core_routers:        # 6 台 CR: RID、接口、路由表、映射表、用户状态
  control_server:      # 1 台 CS: RID、预注册用户
  access_points:       # 2 台 AP: AID、RID、SSID、关联CR
  test_server:         # 1 台 TS
  hosts:               # 2 台 Host: IP、AID、认证信息
connections:           # 节点接口↔交换机端口的物理连接
```

### 8.2 修改示例

**增加一台 CR**：在 `core_routers` 列表中添加：

```yaml
    - name: CR-7
      rid: [40000, 50000]
      interfaces:
        - { name: Eth0, mac: "00:18:54:FD:29:07", type: ACCESS }
        - { name: Eth1, mac: "00:0C:AB:1E:76:92", type: ROUTE }
      rid_spaces:
        - { id: 100, x: 40000, y: 50000, x_mask: 20, y_mask: 20, policy: DEFAULT }
      rid_routes:
        - { space_id: 100, x: 12345, y: 34267, x_mask: 20, y_mask: 24, next_hop: [12360, 34280] }
```

---

## 9. 各组件功能速查

### 9.1 CoreRouter (核心路由器)

```python
from src.nodes.core_router import CoreRouter

cr = CoreRouter(name="CR-1")
cr.my_rid = RID(10001, 36191)

# 配置接口
cr.add_interface("Eth0", "00:18:54:fd:29:01", InterfaceType.ACCESS)
cr.configure_interface(0, "Eth0", "00:18:54:fd:29:01", InterfaceType.ACCESS)

# 配置 RID 空间和路由
cr.add_rid_space(100, RIDSpace(12345, 34267, 20, 24), SpacePolicy.DEFAULT)
cr.add_rid_route(100, 12345, 34267, 20, 24, RID(12360, 34280))

# 配置映射和用户
cr.add_local_mapping(AID.from_hex("..."), RID(10001, 36191))
cr.set_user_status(user_aid, ap_aid, UserStatus.ONLINE)
```

### 9.2 AccessPoint (无线接入设备)

```python
from src.nodes.access_point import AccessPoint

ap = AccessPoint(name="AP-1")
ap.aid = AID.from_hex("8d969eef6ecad3c29a3a629280e686cf")
ap.rid = RID(10001, 36191)
ap.cs_rid = RID(10028, 36181)   # 控制服务器的 RID
ap.cr_rid = RID(10001, 36191)   # 关联 CR 的 RID
ap.ssid = "ID-Network-1"
```

### 9.3 ControlServer (控制平面服务器)

```python
from src.nodes.control_server import ControlServer

cs = ControlServer(name="CS")
cs.rid = RID(10028, 36181)

# 注册用户（AID 自动由哈希生成）
cs.register_user(
    username="Zhangsan",
    password="123",
    pin="1234",
    custom_attributes="UR:3;BW:10Mbps",
)
```

### 9.4 Host (用户终端)

```python
from src.nodes.host import Host

host = Host(name="Host-1")
host.load_aid_config("cad3c29a3a629280e686cf8d969eef6e", "Zhangsan", "123")
host.ip_address = "192.168.1.100"

# 认证 + 发送业务请求
await host.authenticate()
await host.http_get("/index.html", server_aid)
await host.ftp_download("file.bin", server_aid)
```

### 9.5 TestServer (业务测试服务器)

```python
from src.nodes.test_server import TestServer

ts = TestServer(name="TS")
ts.aid = AID.from_hex("d3c29a3a629280e686cf8d969eef6eca")

# 启动模拟服务
await ts.start_http_server(page_size=4096, num_pages=5)
await ts.start_ftp_server(file_count=5, file_size=200_000)
await ts.start_video_server(chunk_count=20, chunk_size=50_000)
```

### 9.6 虚拟网络层

```python
from src.simulation.virtual_link import VirtualLink, VirtualSwitch

# 点对点链路
link = VirtualLink(name="core-link", delay_ms=5, loss_rate=0.01)
link.attach("node-a:0")
link.attach("node-b:0")
await link.send("node-a:0", "node-b:0", b"data")

# 交换机 (含端口隔离)
sw = VirtualSwitch(name="access-sw")
sw.add_port(1, bytes.fromhex("000c29ab1e01"))
sw.add_port(2, bytes.fromhex("000c29ab1e02"))
sw.set_isolation_group(1, [1, 2])  # 端口1和2可以通信
```

---

## 10. 常见问题排查

### Q1: `ModuleNotFoundError: No module named 'src'`

**原因**：Python 路径不包含项目根目录。

**解决**：
```bash
cd identifier-network-sim
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Q2: 测试运行时卡住不动

**原因**：`test_topology_start_stop` 需要同时启动12个异步节点，可能耗时较长。

**解决**：跳过该测试运行其他测试：
```bash
python3 -m pytest tests/ -v -k 'not test_topology_start_stop'
```

### Q3: 端口隔离测试失败

**原因**：交换机没有配置隔离组时默认允许所有流量（开放模式）。

**解决**：确认测试中正确配置了 `set_isolation_group()`。查看 `test_integration.py` 中的示例。

### Q4: 如何调试某个节点的行为

**方法**：提高日志级别并重新运行：
```python
from src.common.utils import setup_logging
setup_logging(level="DEBUG")  # 或 "TRACE"
```

### Q5: AID 包头部到底是 40 字节还是 48 字节

**答：40 字节**。

```
Version(4b)+IDType(4b) = 1B
QoS = 1B
Reserved = 2B
PayloadLength = 2B
DataType = 1B
TTL = 1B
SrcAID = 16B
DstAID = 16B
─────────────────
合计 = 40 字节
```

---

## 11. 二次开发指南

### 11.1 添加新的控制信令

1. 在 `src/control_plane/signaling.py` 中定义新的消息类
2. 在 `SignalType` 枚举中添加新类型
3. 在 `_SIGNAL_TYPE_MAP` 中注册映射
4. 在目标节点 (CS/CR/AP) 的 `_dispatch` 方法中添加处理分支

### 11.2 添加新场景

1. 在 `scenarios/` 下创建新文件（参考 `http_demo.py`）
2. 在 `scenarios/run_demo.py` 中添加对应的 `demo_xxx()` 函数
3. 在主函数的 `demos` 字典中注册

### 11.3 修改拓扑

编辑 `config/topology.yaml`：
- 增加节点：在对应节点列表中添加新条目
- 修改路由：编辑 `rid_routes` 列表
- 调整隔离策略：修改 `isolation_groups`

### 11.4 运行单个测试进行调试

```bash
# 运行特定测试函数
python3 -m pytest tests/test_cr_routing.py::TestRIDRouting::test_exact_match -v

# 显示详细输出
python3 -m pytest tests/test_cr_routing.py -v --tb=long

# 在第一个失败处停止
python3 -m pytest tests/ -x
```

---

## 附录：核心数据流全链路示例

以下是一次完整的 Host-1 → Test Server HTTP 请求的数据流：

```
时间线  │ 节点        │ 数据格式  │ 操作
────────┼────────────┼──────────┼────────────────────────────────
 T1     │ Host-1     │ IPv4     │ 构造 HTTP GET 请求
 T2     │ Host-1     │ AID      │ 封装为 AID 包 (src=Host-1.AID, dst=TS.AID)
 T3     │ AP-1       │ AID      │ 接收 AID 包，查 CS 获取 TS 的映射
 T4     │ CR-1       │ AID      │ 收到 AID 包 → 查映射表 → TS 映射在本地
 T5     │ CR-1       │ RID      │ 封装为 RID 包 (src=CR-1.RID, dst=TS.RID)
 T6     │ CR-1       │ RID      │ 查 RID 路由表 → 直接交付给 TS（本地）
 T7     │ CR-1       │ AID      │ 解封装 RID → 得到内部 AID 包
 T8     │ TS         │ AID      │ 解封装 AID → 得到原始 HTTP 请求
 T9     │ TS         │ IPv4     │ 处理 HTTP 请求，生成响应
 T10    │ TS → Host-1 │ AID→RID  │ 响应沿原路返回
```

---

> 📧 有问题？查看项目目录下的源码注释或运行 `python3 -m pytest tests/ -v` 确认系统状态。
