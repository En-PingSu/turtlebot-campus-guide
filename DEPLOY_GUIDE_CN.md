# TurtleBot468 部署指南

## 一、环境准备

### 1.1 硬件要求
- TurtleBot4 机器人（命名空间：`turtlebot468`，IP：`192.168.50.31`）
- 笔记本电脑（Ubuntu 22.04 + ROS 2 Humble）
- 两台设备连接同一 WiFi 网络

### 1.2 软件依赖
```bash
# ROS 2 Humble（已安装）
source /opt/ros/humble/setup.bash

# 工作空间
source ~/CS5335TurtleBot/install/setup.bash

# Python 依赖
pip install fastapi uvicorn pyyaml

# SSH 工具
sudo apt install sshpass
```

### 1.3 DDS 环境变量（每个终端都需要设置）
```bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DISCOVERY_SERVER="192.168.50.31:11811"
export ROS_SUPER_CLIENT=True
```

---

## 二、部署流程

### 2.1 一键部署（推荐）

```bash
cd ~/CS5335TurtleBot
./deploy.sh --pose charging_station
```

**可用的初始位置：**

| 位置名称 | 坐标 (x, y) | 说明 |
|---------|-------------|------|
| `charging_station` | (-0.10, -0.24) | 充电桩（默认起点） |
| `front_door` | (5.19, 2.56) | 教室前门 |
| `back_door` | (-1.56, 0.86) | 教室后门 |
| `table_1` ~ `table_9` | 各桌位置 | 教室内各桌子 |
| `stand_monitor` | (2.56, 0.26) | 立式显示器 |

**常用参数：**
```bash
./deploy.sh --pose front_door          # 从前门启动
./deploy.sh --pose charging_station    # 从充电桩启动
./deploy.sh --skip-build --pose front_door  # 跳过编译（代码未改动时）
./deploy.sh --skip-clock --pose front_door  # 跳过时钟同步
```

### 2.2 部署脚本执行步骤

脚本会自动执行以下 8 个步骤：

1. **时钟同步** — 同步 RPi 和笔记本的时钟（chrony），防止 AMCL 因时间偏差失效
2. **编译** — `colcon build --packages-select campus_nav_llm`
3. **启动导航栈** — 启动 Nav2 所有节点（map_server, AMCL, planner, controller 等）
4. **等待节点就绪** — 等待所有 Nav2 节点出现（约 15 秒）
5. **激活生命周期节点** — 配置并激活 9 个 Nav2 生命周期节点，设置初始位姿
6. **健康检查** — 验证 AMCL 正在发布位姿
7. **等待 LLM 节点** — 等待 llm_planner 就绪
8. **验证** — 检查 `/user_input` 订阅者、`navigate_to_pose` 动作服务器

### 2.3 启动 Dashboard 控制面板

```bash
cd ~/CS5335TurtleBot/dashboard
# 启动（连接 ROS 2，必须加 --ros）
source /opt/ros/humble/setup.bash
source ~/CS5335TurtleBot/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DISCOVERY_SERVER="192.168.50.31:11811"
export ROS_SUPER_CLIENT=True
python3 dashboard_server.py --ros --port 8080 &
```

打开浏览器访问：**http://localhost:8080**

> **重要：** Dashboard 必须用 `--ros` 参数启动，否则导航命令不会发送到机器人！

---

## 三、Dashboard 使用说明

### 3.1 面板功能

| 面板 | 功能 |
|------|------|
| **System** | 显示机器人位姿、协方差、导航状态、电量 |
| **Pre-flight Checks** | 部署前检查（RPi 连通、时钟、Discovery Server、Odom、ROS2 Daemon） |
| **Deploy** | 一键部署，选择初始位姿 |
| **Robot Management** | 同步时钟、重启 Create3 App、重启 Create3、重启 RPi ROS、重启 ROS2 Daemon |
| **Navigate to** | 点击目的地按钮导航，Dock/Undock，Relocalize，Clear Costmap，Cancel Nav |
| **+ Add Location** | 点击地图添加新导航点 |
| **Chat** | 自然语言命令输入（如 "go to table 1 then table 2"） |

### 3.2 导航操作

**方式一：点击按钮**
- 在 "Navigate to" 区域直接点击目的地按钮

**方式二：自然语言**
- 在底部输入框输入命令，如：
  - `go to table 1`
  - `go to back door then go to front door`（多步导航）
  - `cancel`（取消当前导航）

**方式三：点击地图**
- 直接点击地图上的标注点

### 3.3 管理导航点

- **添加**：点击 `+ Add Location` 按钮 → 点击地图选位置 → 填写信息 → Save
- **编辑**：右键点击目的地按钮 → 修改信息或点击地图重新定位 → Save
- **删除**：右键点击目的地按钮 → 点击 Delete

> 系统会自动验证位置是否可达（不在墙上、距障碍物足够远）。如果位置无效，会建议最近的安全位置。

---

## 四、常见问题排查

### 4.1 Odom 不发布

**症状：** `odom` frame 不存在，TF 超时

**排查步骤：**
1. 运行 Pre-flight Checks（Dashboard 中点击 "Run Checks"）
2. 系统会自动诊断原因：
   - **无 Create3 节点** → GUID 不匹配，需要完整重启（Full Recovery）
   - **Create3 节点在但 TB4 节点缺失** → 重启 turtlebot4.service
   - **所有节点在但无 topic** → ROS2 Daemon 缓存过期，重启 Daemon
   - **topic 在但 odom 无数据** → 重启 Create3 App

**手动修复：**
```bash
# SSH 到 RPi 重启 turtlebot4
sshpass -p "$ROBOT_SSH_PASS" ssh ubuntu@192.168.50.31 "sudo systemctl restart turtlebot4.service"

# 重启本地 ROS2 daemon
ros2 daemon stop && ros2 daemon start

# 重启 Create3 App（通过 RPi）
sshpass -p "$ROBOT_SSH_PASS" ssh ubuntu@192.168.50.31 "curl -X POST http://192.168.186.2/api/restart-app"
```

### 4.2 AMCL 定位丢失

**症状：** 地图上机器人位置与实际不符，导航失败 "failed to create plan"

**解决方法：**
1. 在 Dashboard 点击 **Set Pose** 按钮
2. 在地图上点击机器人的实际位置
3. 或点击 **Relocalize** 让机器人原地旋转重新定位

> **新增功能：** AMCL 看门狗会自动检测 AMCL 停止发布的情况，自动重新发送初始位姿恢复。无需手动干预。

### 4.3 Discovery Server 问题

**症状：** `ros2 topic list` 只显示 `/parameter_events` 和 `/rosout`

**解决方法：**
```bash
# 重启 ROS2 Daemon
ros2 daemon stop && ros2 daemon start

# 检查 Discovery Server 是否在监听 UDP 端口
sshpass -p "$ROBOT_SSH_PASS" ssh ubuntu@192.168.50.31 "ss -ulnp | grep 11811"

# 如果端口没在监听，重启 Discovery Server
sshpass -p "$ROBOT_SSH_PASS" ssh ubuntu@192.168.50.31 "sudo systemctl restart discovery.service"
```

### 4.4 llm_planner 崩溃

**症状：** `process has died` 错误

**常见原因：**
- 部署进程被终止后 llm_planner 尝试重生，但临时参数文件已被删除
- **解决：** 重新部署 `./deploy.sh --pose charging_station`

### 4.5 Dock/Undock 不工作

**注意事项：**
- Create3 在充电桩上时**不能直接关机**，必须先 Undock
- 先点击 **Undock**，等机器人离开充电桩后再导航

### 4.6 时钟偏差

**手动同步：**
```bash
sshpass -p "$ROBOT_SSH_PASS" ssh ubuntu@192.168.50.31 "sudo chronyc -a makestep"
```

---

## 五、停止系统

```bash
# 停止导航栈
cd ~/CS5335TurtleBot
./stop.sh

# 停止 Dashboard
pkill -f dashboard_server
```

---

## 六、调试命令

```bash
# 查看机器人位姿
ros2 topic echo /turtlebot468/amcl_pose --once

# 查看 odom
ros2 topic echo /turtlebot468/odom --once

# 查看系统状态
ros2 topic echo /system_status --once

# 查看所有节点
ros2 node list

# 查看所有 topic
ros2 topic list

# 手动发送导航命令
ros2 topic pub --once /user_input std_msgs/msg/String "data: 'go to table 1'"

# 查看 Create3 web 界面（通过 SSH 隧道）
ssh -L 8080:192.168.186.2:80 ubuntu@192.168.50.31
# 然后浏览器打开 http://localhost:8080
```

---

## 七、部署检查清单

每次部署前确认：

- [ ] 机器人已开机，在充电桩上或已知位置
- [ ] RPi 可达：`ping 192.168.50.31`
- [ ] 运行 Pre-flight Checks 全部通过
- [ ] 选择正确的初始位姿（与机器人实际位置匹配）
- [ ] Dashboard 以 `--ros` 模式启动
- [ ] 部署完成后验证 AMCL 位姿与实际一致
