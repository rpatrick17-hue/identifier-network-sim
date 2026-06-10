# 标识网络模态仿真 — 运行教程

## 环境

| 项目 | 值 |
|------|-----|
| 远端服务器 | `ssh ngit@192.168.80.222` |
| 项目路径 | `/home/ngit/identifier-network-sim` |
| Python | 3.10.12 |
| 需 root | 是（veth/命名空间需要 sudo） |

---

## 一、快速启动（3 步）

```bash
# 1. SSH 登录
ssh ngit@192.168.80.222

# 2. 进入项目
cd /home/ngit/identifier-network-sim

# 3. 搭建网络 + 运行仿真
sudo bash scripts/setup_netns.sh setup
sudo python3 scripts/real_simulation.py test
```

## 二、详细步骤

### 步骤 1：搭建网络环境

```bash
sudo bash scripts/setup_netns.sh setup
```

这会创建：
- **8 个网络命名空间**：`ns-cr1` `ns-cr2` `ns-cs` `ns-ap1` `ns-ap2` `ns-ts` `ns-host1` `ns-host2`
- **8 对 veth**：每对一端在宿主机（Python 控制），一端在命名空间（可抓包）

输出示例：
```
=== veth 直连仿真 ===
  + cr1: veth-cr1 ↔ ns-cr1:veth-cr1-ns (00:c0:01:01:00:01)
  + cr2: veth-cr2 ↔ ns-cr2:veth-cr2-ns (00:c0:01:02:00:01)
  + cs: veth-cs ↔ ns-cs:veth-cs-ns (00:c0:01:10:00:01)
  + ap1: veth-ap1 ↔ ns-ap1:veth-ap1-ns (00:c0:01:11:00:01)
  + ap2: veth-ap2 ↔ ns-ap2:veth-ap2-ns (00:c0:01:12:00:01)
  + ts: veth-ts ↔ ns-ts:veth-ts-ns (00:c0:01:20:00:01)
  + host1: veth-host1 ↔ ns-host1:veth-host1-ns (00:c0:01:31:00:01)
  + host2: veth-host2 ↔ ns-host2:veth-host2-ns (00:c0:01:32:00:01)
=== 8 veth pairs ready ===
```

### 步骤 2：运行仿真

```bash
# 冒烟测试（默认）— 验证连通性
sudo python3 scripts/real_simulation.py test

# HTTP 浏览演示
sudo python3 scripts/real_simulation.py http

# 移动切换演示
sudo python3 scripts/real_simulation.py mobility

# 全部依次运行
sudo python3 scripts/real_simulation.py all
```

输出示例：
```
  mirror host1 → veth-host1
  mirror host2 → veth-host2
  ...
8 节点已启动, 8 veth mirrors 活跃

=== 冒烟测试: 8节点连通性 ===
  Host-1: sent=1
  Host-2: sent=1
  TS:     recv=2
  CR-1:   recv=2
  CR-2:   recv=3

停止...
  veth host1: 1 frames mirrored
  veth host2: 1 frames mirrored
  veth ap1: 1 frames mirrored
  veth ap2: 1 frames mirrored
  veth cs: 4 frames mirrored
  总计 8 帧已写入 veth (tcpdump 可见)

=======================================================
  Simulation Report
=======================================================
  CR-1       sent=   0 recv=   2
  CR-2       sent=   0 recv=   3
  CS         sent=   4 recv=   2       ← CS 处理了 2 个认证请求
  AP-1       sent=   1 recv=   1
  AP-2       sent=   1 recv=   2
  TS         sent=   0 recv=   2       ← 2 个 HTTP 请求到达
  Host-1     sent=   1 recv=   2
  Host-2     sent=   1 recv=   3
```

### 步骤 3：抓包验证（另开终端）

```bash
# 终端 1：启动仿真
sudo python3 scripts/real_simulation.py test

# 终端 2：抓包（仿真运行期间执行）
sudo ip netns exec ns-host1 tcpdump -i veth-host1-ns -c 5 -XX
sudo ip netns exec ns-cr1   tcpdump -i veth-cr1-ns -c 5
sudo ip netns exec ns-ts    tcpdump -i veth-ts-ns -c 5
```

### 步骤 4：清理

```bash
sudo bash scripts/setup_netns.sh teardown
```

---

## 三、常见问题

### Q1：`RTNETLINK answers: File exists`

原因：上一次的 veth 没有完全清理。先 teardown 再 setup：

```bash
sudo bash scripts/setup_netns.sh teardown
sudo bash scripts/setup_netns.sh setup
```

### Q2：`ModuleNotFoundError: No module named 'loguru'`（sudo 时）

原因：root 用户没装依赖。安装：

```bash
sudo pip3 install loguru prometheus_client PyYAML
```

### Q3：tcpdump 抓不到自定义 EtherType 帧

原因：AF_PACKET 注入的自定义帧不会被 tcpdump 捕获。这是 Linux 内核限制。
可以抓内核产生的帧（IPv6 等），也可以看 veth mirror 的计数验证帧确实被写入了。

---

## 四、纯软件模式（不需要 root）

```bash
# 不需要搭建网络，直接运行
python3 scripts/simulation.py test
python3 scripts/simulation.py http
python3 scripts/simulation.py mobility
python3 scripts/simulation.py all

# 运行全部 56 个单元测试
python3 -m pytest tests/ -v -k 'not test_topology_start_stop'
```

---

## 五、验证清单

| 验证项 | 命令 | 预期 |
|--------|------|------|
| 网络环境创建 | `sudo bash scripts/setup_netns.sh setup` | 8 veth pairs ready |
| 冒烟测试 | `sudo python3 scripts/real_simulation.py test` | TS recv=2 |
| HTTP 演示 | `sudo python3 scripts/real_simulation.py http` | 5 次 GET 成功 |
| 移动切换 | `sudo python3 scripts/real_simulation.py mobility` | MOVED_AWAY → ONLINE |
| 单元测试 | `python3 -m pytest tests/ -v` | 56 passed |
| 命名空间检查 | `ls /var/run/netns/` | 8 个 ns-xxx |
| veth 检查 | `ip -br link show \| grep veth` | 8 对 veth |
| 抓包 | `sudo ip netns exec ns-host1 tcpdump -i veth-host1-ns -c 3` | 可见流量 |
