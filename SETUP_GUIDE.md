# 我的设备连线 & 部署教程

## 一、设备

```
Windows 笔记本 (VMware Workstation 运行 Linux VM)
├── Linux VM (ucs-worker-2, 192.168.80.222)
│   项目: ~/identifier-network-sim
│   网卡: ens34 (NAT, 上外网 SSH 用)
│         ens37 (可桥接)
│
├── Type-C 转 RJ45 拓展坞 ×1
│   插在笔记本上, VMware 可桥接给 Linux VM
│
└── 用途: SSH 进 VM, 代码编辑 (VSCode Remote), 抓包

中兴设备:
  CR ×6 (支持标识模态)
  交换机 ×2
```

## 二、瓶颈

**只有 1 个 Type-C 网口 → 只能接 1 台交换机。**

但验证需要两台交换机（管理面 + 数据面）。解法：

| 方案 | 做法 | 代价 |
|------|------|------|
| **A: 单交换机** | 只用 1 台交换机，管理+数据 VLAN 隔离 | 0 元，立即可做 |
| **B: 双网卡** | 再买 1 个 Type-C 拓展坞 | ~50 元 |

推荐先走方案 A，后面加购网卡升级到方案 B。

## 三、方案 A：单交换机 (当前)

```
          Windows 笔记本
          ┌────────────────────────────┐
          │  Linux VM (ucs-worker-2)  │
          │  ens37 ← VMware桥接        │
          └──────────┬─────────────────┘
                     │
              笔记本 Type-C 网卡 (RJ45)
                     │ 网线
          ┌──────────┴──────────────────────────────────┐
          │              交换机 (只用1台)                │
          │                                             │
          │  VLAN 1 (管理): 端口1(CS) + 端口2~7(CR管理) │
          │  VLAN 10 (核心): 端口8~13(CR核心)           │
          │  VLAN 20 (接入1): 端口14(CR1接入) +15(AP1+TS)│
          │  VLAN 30 (接入2): 端口16(CR2接入) +17(AP2)  │
          └──┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┘
             │   │   │   │   │   │   │   │   │   │
           CR-1 CR-2 ...                              AP
           (管理)(核心)(接入)                        (ens37)
```

### 接线 (1 张表)

| 交换机端口 | VLAN | 接什么 |
|-----------|------|--------|
| 1 | 1 | **笔记本 Type-C** (Linux VM 的唯一出口, CS+TS+AP 都走这) |
| 2 | 1 | CR-1 管理口 |
| 3 | 1 | CR-2 管理口 |
| 4~7 | 1 | CR-3~6 管理口 |
| 8 | 10 | CR-1 核心口 |
| 9 | 10 | CR-2 核心口 |
| 10~13 | 10 | CR-3~6 核心口 |
| 14 | 20 | CR-1 接入口 |
| 15 | 20 | (VM内 AP-1 + TS 共用端口1) |
| 16 | 30 | CR-2 接入口 |
| 17 | 30 | (VM内 AP-2 共用端口1) |

CS + TS + AP-1 + AP-2 的流量**全走端口1**（VM 唯一的物理出口）。交换机在端口1 上看到多个 MAC，VLAN 1 的帧走管理面，VLAN 20/30 的帧走数据面。

## 四、Type-C 桥接给 VM

```
1. Type-C 拓展坞插到 Windows 笔记本 USB-C 口
   → 设备管理器出现新网卡 (如 "Realtek USB GbE Family Controller")

2. VMware Workstation → 编辑虚拟机设置
   → 网络适配器 → 桥接模式
   → 桥接到: 选 Type-C 那个网卡

3. Linux VM 内确认:
   sudo ip link show
   # ens37 或新出现的网卡就是桥接的物理口

4. 确认 VLAN 可用:
   sudo ip link add link ens37 name ens37.20 type vlan id 20
   # 如果交换机端口是 trunk 模式, 用 VLAN 子接口分别打 tag
   # 如果是 access 模式, 直接绑 ens37 即可
```

## 五、部署 (全部在 VM 上)

```bash
ssh ngit@192.168.80.222
cd /home/ngit/identifier-network-sim

# 确认 Type-C 桥接的网卡名 (假设为 ens37)
ip link show ens37
# 状态应为 UP, LOWER_UP

# 所有角色绑同一张网卡 ens37, 不同 MAC:
sudo python3 scripts/real_deploy.py --role cs   --config config/cs.yaml &
sudo python3 scripts/real_deploy.py --role ts   --config config/ts.yaml &
sudo python3 scripts/real_deploy.py --role ap   --config config/ap1.yaml &
sudo python3 scripts/real_deploy.py --role ap   --config config/ap2.yaml &
sudo python3 scripts/real_deploy.py --role host --config config/host1.yaml &
sudo python3 scripts/real_deploy.py --role host --config config/host2.yaml &
```

## 六、方案 B：双网卡 (加购后)

```
Type-C #1 (桥接给 ens37):
  → 交换机 #1 (管理面)  — 仅 CS

Type-C #2 (桥接给 ens38):
  → 交换机 #2 VLAN 20  — TS + AP-1
  → 交换机 #2 VLAN 30  — AP-2 (VLAN tag)

接法:
  端口1  ← Type-C #1 → VM ens37 → CS
  端口15 ← Type-C #2 → VM ens38 → TS + AP-1 + AP-2
        (trunk 模式, VLAN 20 + 30)
```

## 七、Windows 笔记本的其他用途

| 用途 | 怎么做 |
|------|--------|
| SSH 终端 | `ssh ngit@192.168.80.222` |
| VSCode 开发 | Remote-SSH 插件连进去编辑代码 |
| Wireshark 抓包 | Type-C 插交换机镜像口, 抓实时流量 |
| 无网口的备用 | 如果 Type-C 已被 VM 占用, 用 WiFi SSH 进去 |
