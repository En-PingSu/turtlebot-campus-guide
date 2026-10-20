# Session Notes — March 3, 2026

## TurtleBot4 Campus Guide Bot: Nav2 Integration & Hardware Testing

### Project Overview

- **Robot**: TurtleBot4 (Create3 base + RPi4), namespace `turtlebot468`, IP `192.168.50.31`, user `ubuntu`, password `turtlebot4`
- **Laptop**: Alienware m15 R7 AMD, Ubuntu 22.04, ROS2 Humble
- **Workspace**: `~/campus_ws` — colcon workspace; `~/campus_ws/src/campus_nav_llm` is a symlink → `~/robotic_llm/campus_guide_bot/campus_nav_llm`
- **Second repo**: `~/CS5335TurtleBot` (same code, different remote — keep in sync manually)

---

## What We Did Today (Chronological)

### 1. Copied New SLAM Map & Fixed YAML

The new SLAM map (`my_map.pgm`, 349×406 px) was placed in the package. Updated `my_map.yaml`:

```yaml
image: /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm/maps/my_map.pgm
resolution: 0.05
origin: [-8.1, -8.64, 0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.25
```

**Key change**: Origin went from `[-7.47, -8.74, 1]` → `[-8.1, -8.64, 0]`.

### 2. Remapped Semantic Map Coordinates

Created `semantic/remap_coordinates.py` — uses ORB feature matching between old and new PGM images to compute a rigid transformation. Applied the transform to all 5 locations in `semantic_map.json`. Updated `tests/test_semantic_map.py` with new origin values.

### 3. Created `navigation_mode.launch.py`

Comprehensive all-in-one launch file that runs:
- **Localization**: map_server + AMCL in `turtlebot468` namespace with TF remappings
- **Nav2 stack**: controller_server, smoother_server, planner_server, behavior_server, bt_navigator, waypoint_follower, velocity_smoother — all in `turtlebot468` namespace
- **Two lifecycle managers** with `bond_timeout: 30.0` (default 4.0s was too short)
- **Task executor** (10s delay) and **LLM planner** (15s delay)
- TF remappings: `/tf:=/turtlebot468/tf`, `/tf_static:=/turtlebot468/tf_static` on all Nav2 nodes

### 4. Fixed `task_executor_node.py` — Navigator Namespace

Replaced `TurtleBot4Navigator` (hardcodes `namespace=''`) with `BasicNavigator(namespace=ns)`:
```python
from nav2_simple_commander.robot_navigator import BasicNavigator
navigator = BasicNavigator(namespace=ns)
navigator.waitUntilNav2Active(navigator="bt_navigator", localizer="amcl")
```
Also added `_make_pose_stamped()` helper to build PoseStamped goals manually (replacing `getPoseStamped`/`startToPose`).

### 5. Fixed `nav2_params.yaml` Bug

`behavior_server.use_sim_time` was incorrectly set to `true`. Changed to `False`.

### 6. Added `localization_params.yaml` to Package

Was missing from the package source directory. Copied it to `config/localization_params.yaml`. Required a **clean rebuild** because colcon's symlink-install caches glob results:
```bash
rm -rf ~/campus_ws/build/campus_nav_llm ~/campus_ws/install/campus_nav_llm
cd ~/campus_ws && colcon build --symlink-install --packages-select campus_nav_llm
```

### 7. Hardware Testing — Clock Issues

The RPi has no battery-backed RTC. After every reboot the clock resets to ~2023.

**Fix the RPi clock** (must type the date manually — don't use `$(date)` as it evaluates the wrong local clock):
```bash
ssh ubuntu@192.168.50.31
sudo date -s "2026-03-03 17:15:00"
sudo chronyc makestep
```

**Why it matters**: AMCL drops all laser scans when timestamps differ by years ("the timestamp on the message is earlier than all the data in the transform cache").

### 8. DDS / Discovery Server Configuration (THE BIG BREAKTHROUGH)

#### The Problem
The TurtleBot4 uses **FastRTPS with Discovery Server** (configured in `/etc/turtlebot4/setup.bash`). The laptop must match.

#### What We Tried (and Failed)
1. **CycloneDDS on laptop**: Lifecycle managers worked, but couldn't see robot's TF/scan (different DDS = no communication)
2. **CycloneDDS on robot**: Added to `/etc/turtlebot4/setup.bash` and `.bashrc` — but the `turtlebot4.service` systemd unit was already running with FastRTPS, causing the interactive shell (CycloneDDS) to not see robot's own nodes

#### The Working Solution
**Laptop must use FastRTPS + Discovery Server + Super Client**:
```bash
source ~/campus_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DISCOVERY_SERVER="192.168.50.31:11811"
export ROS_SUPER_CLIENT=True
ros2 launch campus_nav_llm navigation_mode.launch.py
```

**Robot must use FastRTPS** (the default — `/etc/turtlebot4/setup.bash`):
```
export RMW_IMPLEMENTATION="rmw_fastrtps_cpp"
export ROS_DISCOVERY_SERVER="127.0.0.1:11811;192.168.50.31:11811;"
```

#### Robot's `/etc/turtlebot4/setup.bash` (correct state):
```bash
export CYCLONEDDS_URI="/etc/turtlebot4/cyclonedds_rpi.xml"
export FASTRTPS_DEFAULT_PROFILES_FILE="/etc/turtlebot4/fastdds_rpi.xml"
export ROBOT_NAMESPACE="/turtlebot468"
export ROS_DOMAIN_ID="0"
export ROS_DISCOVERY_SERVER="127.0.0.1:11811;192.168.50.31:11811;"
export RMW_IMPLEMENTATION="rmw_fastrtps_cpp"
export TURTLEBOT4_DIAGNOSTICS="1"
export WORKSPACE_SETUP="/opt/ros/humble/setup.bash"
[ -t 0 ] && export ROS_SUPER_CLIENT=True || export ROS_SUPER_CLIENT=False
source $WORKSPACE_SETUP
```

### 9. Lifecycle Manager Timeout Workaround — Manual Node Activation

The lifecycle managers' `change_state` service calls time out due to FastRTPS Discovery Server latency (all service discovery goes through the network, even for local laptop-to-laptop calls). This causes the lifecycle managers to get stuck for 10+ minutes.

**Workaround**: Manually activate nodes from a separate terminal. First, restart the `ros2` daemon (it caches old DDS settings):

```bash
ros2 daemon stop
ros2 daemon start
ros2 node list   # Verify you can see all /turtlebot468/* nodes
```

Then manually transition each node. Some may already be configured by the lifecycle manager (you'll see "Unknown transition - configure", just skip to activate):

```bash
ros2 lifecycle set /turtlebot468/map_server configure
ros2 lifecycle set /turtlebot468/map_server activate
ros2 lifecycle set /turtlebot468/amcl configure
ros2 lifecycle set /turtlebot468/amcl activate
ros2 lifecycle set /turtlebot468/controller_server configure
ros2 lifecycle set /turtlebot468/controller_server activate
ros2 lifecycle set /turtlebot468/smoother_server configure
ros2 lifecycle set /turtlebot468/smoother_server activate
ros2 lifecycle set /turtlebot468/planner_server configure
ros2 lifecycle set /turtlebot468/planner_server activate
ros2 lifecycle set /turtlebot468/behavior_server configure
ros2 lifecycle set /turtlebot468/behavior_server activate
ros2 lifecycle set /turtlebot468/bt_navigator configure
ros2 lifecycle set /turtlebot468/bt_navigator activate
ros2 lifecycle set /turtlebot468/waypoint_follower configure
ros2 lifecycle set /turtlebot468/waypoint_follower activate
ros2 lifecycle set /turtlebot468/velocity_smoother configure
ros2 lifecycle set /turtlebot468/velocity_smoother activate
```

**Status at end of session**: map_server, amcl, controller_server, smoother_server, and planner_server were all successfully activated manually. The planner_server's global_costmap was receiving TF but showed a ~5s clock drift ("extrapolation into the past"). Remaining nodes (behavior_server, bt_navigator, waypoint_follower, velocity_smoother) still needed activation.

---

## Current State (End of Session)

### What's Working
- **Discovery Server connection**: Laptop ↔ Robot communication via FastRTPS Discovery Server ✅
- **TF flowing** at 20Hz from robot to laptop ✅
- **Scan data flowing** at ~8Hz from robot to laptop ✅
- **Map loaded correctly** (349×406, origin [-8.1, -8.64, 0]) ✅
- **LLM Planner** starts and reports ready ✅
- **All robot nodes visible** via `ros2 node list` (after daemon restart) ✅
- **Manual lifecycle transitions work** — nodes configure and activate instantly ✅
- **Nav2 nodes partially activated**: map_server, amcl, controller_server, smoother_server, planner_server ✅

### Known Issues / Next Steps
1. **Finish activating remaining nodes**: behavior_server, bt_navigator, waypoint_follower, velocity_smoother (use manual lifecycle commands above)
2. **~5s clock drift**: planner_server shows "extrapolation into the past" with ~5s offset between requested TF time and earliest available data. May need to re-sync clocks or increase `transform_tolerance`.
3. **Verify AMCL publishes `amcl_pose`**: Once all nodes are active, check `ros2 topic hz /turtlebot468/amcl_pose`. If 0Hz, AMCL isn't processing scans (check scan timestamps match TF timestamps).
4. **Test navigation**: Send a goal via the LLM planner or directly via `ros2 topic pub /turtlebot468/goal_pose ...`
5. **Lifecycle manager timeout root cause**: All Discovery Server traffic (including local service calls) routes through the robot's RPi, adding network latency. Future fix: use a local FastDDS XML profile that separates local discovery from remote Discovery Server, or run Nav2 without namespace and use topic remappings.
6. **Robot clock resets on every reboot**: Must manually set clock after each reboot.
7. **Robot `.bashrc` cleanup**: We removed the CycloneDDS export from `/etc/turtlebot4/setup.bash`, but should also run `sed -i '/rmw_cyclonedds_cpp/d' ~/.bashrc` on the robot to clean up the `.bashrc` change.

---

## Quick Start for Next Session

### Step 1: Fix Robot Clock (every reboot)
```bash
ssh ubuntu@192.168.50.31
# password: turtlebot4
sudo date -s "YYYY-MM-DD HH:MM:SS"   # Type YOUR laptop's current time manually
sudo chronyc makestep
```

### Step 2: Verify Robot Service is Running
```bash
# Still on robot SSH:
source /etc/turtlebot4/setup.bash
ros2 topic hz /turtlebot468/scan    # Should show ~8Hz
ros2 topic hz /turtlebot468/tf      # Should show ~20Hz
```

If no data: `sudo systemctl restart turtlebot4.service`, wait 30s, retry.

### Step 3: Launch on Laptop
```bash
source ~/campus_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DISCOVERY_SERVER="192.168.50.31:11811"
export ROS_SUPER_CLIENT=True
ros2 launch campus_nav_llm navigation_mode.launch.py
```

### Step 4: Manually Activate Nodes (new terminal, same exports)
The lifecycle managers are too slow due to Discovery Server latency. Use manual activation:
```bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DISCOVERY_SERVER="192.168.50.31:11811"
export ROS_SUPER_CLIENT=True

# IMPORTANT: restart daemon first so it discovers nodes via Discovery Server
ros2 daemon stop && ros2 daemon start

# Wait a few seconds, then verify nodes are visible
ros2 node list | grep turtlebot468

# Activate all Nav2 nodes (skip configure if already configured)
for node in map_server amcl controller_server smoother_server planner_server behavior_server bt_navigator waypoint_follower velocity_smoother; do
  echo "--- Configuring $node ---"
  ros2 lifecycle set /turtlebot468/$node configure 2>&1
  echo "--- Activating $node ---"
  ros2 lifecycle set /turtlebot468/$node activate 2>&1
done
```

### Step 5: Verify Everything
```bash
# Same terminal with exports
ros2 topic hz /turtlebot468/scan       # ~8Hz = robot scan data flowing
ros2 topic hz /turtlebot468/amcl_pose  # >0Hz = AMCL localization working
ros2 topic hz /turtlebot468/tf         # ~20Hz = TF data flowing
```

---

## Files Modified (in `robotic_llm/campus_guide_bot/campus_nav_llm/`)

| File | Change |
|------|--------|
| `maps/my_map.pgm` | Replaced with new SLAM map |
| `maps/my_map.yaml` | New origin [-8.1, -8.64, 0], absolute path |
| `semantic/semantic_map.json` | Remapped coordinates via ORB matching |
| `semantic/remap_coordinates.py` | NEW — coordinate transformation tool |
| `config/nav2_params.yaml` | Fixed behavior_server use_sim_time: False |
| `config/localization_params.yaml` | NEW — copied into package (was missing) |
| `campus_nav_llm/task_executor_node.py` | BasicNavigator(namespace=ns) instead of TurtleBot4Navigator |
| `launch/navigation_mode.launch.py` | NEW — comprehensive all-in-one launch file |
| `tests/test_semantic_map.py` | Updated origin values to match new map |

## Build Command
```bash
rm -rf ~/campus_ws/build/campus_nav_llm ~/campus_ws/install/campus_nav_llm
cd ~/campus_ws && colcon build --symlink-install --packages-select campus_nav_llm
```
**Note**: Clean build required when adding new files because colcon caches glob results.

---

## Key Lessons Learned

1. **TurtleBot4 uses FastRTPS Discovery Server** — not simple multicast. The laptop MUST set `ROS_DISCOVERY_SERVER` and `ROS_SUPER_CLIENT=True`.
2. **Never mix DDS implementations** — CycloneDDS on laptop + FastRTPS on robot = no communication.
3. **Robot systemd service ignores `.bashrc`** — environment changes must go in `/etc/turtlebot4/setup.bash` and the service must be restarted.
4. **RPi clock resets on reboot** — always fix with `sudo date -s` + `sudo chronyc makestep` before launching.
5. **`TurtleBot4Navigator` hardcodes `namespace=''`** — use `BasicNavigator(namespace=ns)` instead.
6. **colcon symlink-install caches globs** — new files require `rm -rf build/ install/` for the package before rebuilding.
7. **Lifecycle `change_state` timeouts block the lifecycle managers** — the Discovery Server routes ALL service calls (even local ones) through the network, causing timeouts. Workaround: manually activate nodes via `ros2 lifecycle set`.
8. **`ros2 daemon` caches DDS settings** — after changing `RMW_IMPLEMENTATION` or `ROS_DISCOVERY_SERVER`, always run `ros2 daemon stop && ros2 daemon start` before using `ros2` CLI tools.
9. **Robot's `.bashrc` vs `/etc/turtlebot4/setup.bash`** — `.bashrc` only affects interactive SSH shells. The `turtlebot4.service` systemd unit sources `/etc/turtlebot4/setup.bash`. Never put DDS changes only in `.bashrc`.
