# Startup Guide

## Prerequisites

- Ubuntu 22.04 with ROS 2 Humble
- TurtleBot4 (turtlebot468) powered on and connected to ASUS_98 WiFi
- Laptop connected to ASUS_98 (ethernet or WiFi)
- Second network connection for internet (phone hotspot or second adapter)
- `sshpass` installed: `sudo apt install sshpass`
- Python packages: `pip install fastapi uvicorn pyyaml`

## Configuration

All settings are in `config.yaml` (project root). Edit this one file — both `deploy.sh` and the dashboard read from it.

```yaml
robot:
  ip: "192.168.50.31"
  namespace: "turtlebot468"
workspace:
  dir: "~/CS5335TurtleBot"
```

## Option A: Dashboard (recommended)

The dashboard provides a web interface for deployment, navigation, and monitoring.

```bash
# 1. Source ROS workspace
source ~/CS5335TurtleBot/install/setup.bash

# 2. Start dashboard with ROS bridge
cd ~/CS5335TurtleBot/dashboard
python dashboard_server.py --ros --port 8080

# 3. Open browser
#    http://127.0.0.1:8080
```

From the browser:

1. **Deploy panel** — select initial pose, check/uncheck skip options, click **Deploy**
2. Watch deploy logs stream in real-time (clock sync → build → launch → activate → health check)
3. Once deploy finishes, the map shows the robot position
4. **Set Pose** — click the button, then click on the map to set AMCL initial pose
5. **Navigate** — click a destination on the map or type a command in the input box

## Option B: Command line

```bash
# 1. Source workspace
source ~/CS5335TurtleBot/install/setup.bash

# 2. Deploy (clock sync + build + launch + activate + set pose)
cd ~/CS5335TurtleBot
./deploy.sh --pose front_door

# 3. Send commands from another terminal
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DISCOVERY_SERVER="192.168.50.31:11811"
export ROS_SUPER_CLIENT=True
source ~/CS5335TurtleBot/install/setup.bash

ros2 topic pub --once /user_input std_msgs/msg/String "data: 'go to table 1'"
ros2 topic echo /robot_reply
```

### deploy.sh flags

| Flag | Effect |
|------|--------|
| `--skip-build` | Skip `colcon build` |
| `--skip-clock` | Skip chrony clock sync |
| `--pose front_door` | Set initial pose (name from config.yaml) |
| `--pose "1.0 2.0 0.5"` | Set custom initial pose (x y theta) |

## What deploy.sh does

```
Step 1: Clock sync
  - Installs/configures chrony on RPi (laptop → RPi → Create3 NTP hierarchy)
  - Verifies drift ≤ 2 seconds
  - Falls back to date -s if chrony fails
  - Restarts turtlebot4 service, waits for robot topics

Step 2: Build
  - colcon build --packages-select campus_nav_llm
  - Exits on failure

Step 3: Launch
  - Kills stale ROS daemon, starts fresh
  - Launches navigation_mode.launch.py in background
  - Starts: odom_tf_publisher, map_server, AMCL, Nav2 stack,
    lifecycle_managers, task_executor (delayed 10s), llm_planner (delayed 15s)
  - All custom nodes have respawn enabled

Step 4: Wait for Nav2 nodes
  - Polls ros2 node list until ≥ 9 nodes in namespace

Step 5: Activate lifecycle nodes
  - For each of 9 Nav2 lifecycle nodes:
    - Get state → configure → activate
    - Retries 3 times with exponential backoff (5s → 10s → 20s)
  - Needed because FastDDS Discovery Server filters lifecycle services (Nav2 #3560)

Step 6: Health check
  - Waits for navigate_to_pose action server (up to 120s)
  - This is the definitive readiness gate

Step 7: Set initial pose
  - Computes quaternion from theta
  - Waits for AMCL to subscribe to /initialpose
  - Publishes PoseWithCovarianceStamped

Step 8: Wait for LLM nodes
  - Polls for task_executor and llm_planner

Step 9: Verify
  - Checks /user_input and /tool_cmd have subscribers
  - Checks navigate_to_pose action server
  - Prints summary
```

## Monitoring

### Dashboard (http://127.0.0.1:8080)

- **Map**: robot position (green dot + heading arrow), semantic locations (blue dots), click to navigate
- **System status**: pose, AMCL covariance (green < 0.5, yellow < 1.0, red ≥ 1.0), nav state
- **Chat**: user commands, robot replies, tool calls, system events
- **Deploy log**: real-time output from deploy.sh

### Command line

```bash
# System health (1 Hz JSON)
ros2 topic echo /system_status

# Robot position
ros2 topic echo /turtlebot468/amcl_pose

# Navigation progress
ros2 topic echo /nav_progress

# LLM replies
ros2 topic echo /robot_reply
```

## Troubleshooting

### Robot not discovered

```bash
# Check DDS environment
echo $RMW_IMPLEMENTATION        # should be rmw_fastrtps_cpp
echo $ROS_DISCOVERY_SERVER      # should be 192.168.50.31:11811
echo $ROS_SUPER_CLIENT          # should be True

# Restart daemon and check
ros2 daemon stop && ros2 daemon start
ros2 topic list | grep turtlebot468
```

### Lifecycle activation fails

This is expected with FastDDS Discovery Server. deploy.sh retries 3 times. If all fail:

```bash
# Manual activation
ros2 lifecycle set /turtlebot468/map_server configure
ros2 lifecycle set /turtlebot468/map_server activate
# Repeat for: amcl, controller_server, planner_server, behavior_server,
#             smoother_server, bt_navigator, waypoint_follower, velocity_smoother
```

### Navigation rejected: localization uncertain

AMCL covariance is too high. Options:

1. **Dashboard**: click Set Pose → click robot's actual location on map
2. **Command line**: re-run deploy.sh Step 7
3. **Automatic**: the LLM can invoke the `relocalize` tool (spreads particles + spins robot)

### Clock drift errors

```bash
# Check drift
ssh ubuntu@192.168.50.31 "date" && date

# Force chrony sync
ssh ubuntu@192.168.50.31 "sudo chronyc -a makestep"
```

## Stopping

```bash
# Dashboard: Ctrl+C in the terminal running dashboard_server.py

# Navigation stack:
./stop.sh
# Or: kill $(cat /tmp/turtlebot_launch.pid)
```
