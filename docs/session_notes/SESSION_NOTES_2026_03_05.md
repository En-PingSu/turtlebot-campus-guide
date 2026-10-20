# Session Notes — March 5, 2026

## TurtleBot4 Campus Guide Bot: Nav2 Bring-up & LLM Planner Debugging

### Project Overview

- **Robot**: TurtleBot4 (Create3 base + RPi4), namespace `turtlebot468`, IP `192.168.50.31`
- **Laptop**: Alienware m15 R7 AMD, Ubuntu 22.04, ROS2 Humble
- **DDS**: FastRTPS with Discovery Server (not multicast)
- **Workspace**: `~/campus_ws` (colcon build); source code at `~/robotic_llm/campus_guide_bot/campus_nav_llm`

---

## Summary

Spent the session bringing up the full Nav2 stack with AMCL localization on the real robot, debugging clock synchronization issues between the three independent clocks (laptop, RPi4, Create3), and fixing the LLM planner's API key loading. By end of session, all Nav2 nodes are active, AMCL is localizing, and the LLM planner issue is diagnosed and fixed (needs one more relaunch to take effect).

---

## Issues Found & Fixed

### 1. AMCL transform_tolerance Too High (15.0s)

**Problem**: AMCL's `transform_tolerance: 15.0` in `localization_params.yaml` caused the `map -> odom` transform to be published at `scan_time + 15 seconds`. This pushed the transform so far into the future that the global costmap couldn't look it up at the actual scan time, producing:

```
Lookup would require extrapolation into the past. Requested time X but the earliest data is at time X+15
```

**Fix**: Changed `transform_tolerance` from `15.0` to `2.0` in:
- `~/campus_ws/src/campus_nav_llm/config/localization_params.yaml` (line 33)
- `~/campus_ws/localization_params.yaml` (backup copy)

The installed file is a symlink chain: `install/ -> build/ -> src/`, so editing the source file is sufficient (no rebuild needed with `--symlink-install`).

### 2. nav2_params.yaml transform_tolerance Too Low (0.2s)

**Problem** (from earlier in session): Default `transform_tolerance: 0.2` in costmaps and servers was too small for the ~2-3s clock offset between laptop and robot. Caused "extrapolation into the past" errors.

**Fix** (done earlier, carried forward): Set `transform_tolerance: 5.0` in `nav2_params.yaml` for:
- `global_costmap` (line ~148)
- `local_costmap` (line ~148)
- `controller_server` DWB plugin (line ~123)
- `behavior_server` (line ~259)

### 3. LLM Planner .env File Not Found (401 API Error)

**Problem**: The `_load_dotenv()` function in `llm_planner_node.py` searches three directories for `.env`:
1. `Path.cwd()` — when launched via `ros2 launch`, this is `~` (no .env there)
2. `Path(__file__).parent.parent` — with `--symlink-install`, Python files are COPIES in build/, not symlinks. So this resolves to `~/campus_ws/build/campus_nav_llm/` (no .env there)
3. `Path.home()` — `~` (no .env there)

The actual `.env` file at `~/robotic_llm/campus_guide_bot/campus_nav_llm/.env` is never found, so `OPENROUTER_API_KEY` defaults to empty string, causing 401 errors.

**Fix**: Copied `.env` to home directory:
```bash
cp ~/robotic_llm/campus_guide_bot/campus_nav_llm/.env ~/.env
```

**Better long-term fix**: Modify `_load_dotenv()` to also search the package's share directory, or pass the API key as a ROS parameter.

### 4. .env File Had Line Break in API Key

**Problem**: The API key in `.env` was split across two lines. The line-by-line parser only read the first half.

**Fix**: Joined into single line.

### 5. Robot DDS State Corruption After Create3 Restart

**Problem**: After restarting `turtlebot4.service` and physically restarting the Create3, `robot_state_publisher` was running (PID visible) but its ROS2 node wasn't visible in `ros2 node list`, and no TF data flowed.

**Fix**: Full robot reboot (`sudo reboot`). After reboot, all data resumed normally.

### 6. Lifecycle Manager Timeouts Over Discovery Server

**Problem**: `ros2 lifecycle set` commands often hang because the Discovery Server routes service responses through the network, and the response times out even though the transition succeeds on the node side.

**Workaround**:
- Run each `ros2 lifecycle set` command individually
- If it hangs >15s, Ctrl+C and check with `ros2 lifecycle get /turtlebot468/<node>`
- The transition usually went through despite the timeout
- Do NOT restart the ros2 daemon mid-activation (it loses track of nodes)

---

## Three-Clock Problem

The TurtleBot4 has THREE independent clocks that must be reasonably synchronized:

| Clock | Source | Used By |
|-------|--------|---------|
| Laptop | System clock (NTP synced) | AMCL (publishes map->odom TF), costmaps, Nav2 nodes |
| RPi4 | `sudo date -s` (no battery-backed RTC) | Lidar scan timestamps |
| Create3 | Internal MCU clock | Odometry, odom->base_link TF |

- RPi4-to-Create3 offset was ~2s (acceptable with `transform_tolerance: 5.0`)
- Laptop-to-robot offset was ~3.6s (causes "extrapolation into the future" warnings but AMCL still works)
- Use `~/check_clock_offset.sh` to measure the RPi4-Create3 offset
- After robot reboot, always set RPi4 clock: `ssh ubuntu@192.168.50.31` then `sudo date -s "YYYY-MM-DD HH:MM:SS" && sudo chronyc makestep`

---

## Helper Scripts Created

All in `~/` (home directory):

| Script | Purpose |
|--------|---------|
| `launch_nav.sh` | Sources workspace, sets DDS env vars, launches `navigation_mode.launch.py` |
| `activate_all.sh` | Waits 15s, then configure+activate all 9 Nav2 lifecycle nodes, publishes initial pose, checks amcl_pose |
| `check_clock_offset.sh` | Compares scan (RPi4) and TF (Create3) timestamps to measure clock offset |
| `activate_nav2.sh` | Earlier version of activate script (superseded by `activate_all.sh`) |

---

## Bring-up Procedure (Quick Reference)

### Prerequisites
- Robot powered on and connected to WiFi (ping 192.168.50.31)
- RPi4 clock set (SSH in, `sudo date -s "..."`)

### Steps

```bash
# Terminal 1: Launch nav stack
~/launch_nav.sh

# Terminal 2: Source environment (MUST do this before any ros2 commands)
source ~/campus_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DISCOVERY_SERVER="192.168.50.31:11811"
export ROS_SUPER_CLIENT=True
ros2 daemon stop && ros2 daemon start
sleep 10

# Activate nodes one at a time (order matters: map_server & amcl first)
ros2 lifecycle set /turtlebot468/map_server configure
ros2 lifecycle set /turtlebot468/map_server activate
ros2 lifecycle set /turtlebot468/amcl activate

# Set initial pose (MUST do before activating planner/controller)
ros2 topic pub --once /turtlebot468/initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  '{header: {frame_id: "map"}, pose: {pose: {position: {x: 0.0, y: 0.0, z: 0.0}, orientation: {w: 1.0}}}}'

# Activate remaining nodes
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

# If any command hangs, Ctrl+C and check state:
ros2 lifecycle get /turtlebot468/<node_name>

# Verify AMCL is working
ros2 topic echo /turtlebot468/amcl_pose --once

# Test LLM planner
ros2 topic pub --once /user_input std_msgs/msg/String '{data: "go to the front door"}'
```

### Important Notes
- The lifecycle managers will auto-configure some nodes. Check state before manually transitioning.
- If a node shows "Unknown transition requested, available ones are: cleanup, activate, shutdown" — it's already configured, just activate it.
- If a node shows "Unknown transition requested, available ones are: deactivate, shutdown" — it's already active.
- `ros2 topic hz` often fails to see topics through Discovery Server. Use `ros2 topic echo --once` instead.
- AMCL publishes `amcl_pose` but `ros2 topic hz` may not detect it. The `map -> odom` transform being present (check with `tf2_echo`) confirms AMCL is working.

---

## Files Modified This Session

| File | Change |
|------|--------|
| `config/localization_params.yaml` | `transform_tolerance`: 15.0 -> 2.0 |
| `config/nav2_params.yaml` | `transform_tolerance`: 0.2 -> 5.0 (multiple sections, done in prior session) |
| `.env` | Fixed line break in API key |
| `~/.env` | NEW — copied .env to home dir so LLM planner can find it at runtime |

---

## Remaining TODO for Next Session

1. **Relaunch to pick up .env fix**: Ctrl+C launch, `~/launch_nav.sh`, activate nodes, test LLM planner with `ros2 topic pub --once /user_input std_msgs/msg/String '{data: "go to the front door"}'`
2. **Fix _load_dotenv() permanently**: Modify to search the package share directory, or pass API key as ROS parameter
3. **Test full LLM navigation loop**: Send command -> LLM calls navigate_to -> robot moves -> LLM confirms arrival
4. **Consider autostart for lifecycle nodes**: Investigate increasing lifecycle manager service timeout to work with Discovery Server, avoiding manual activation
5. **Set proper initial pose**: Current initial pose is (0,0,0) which may not match robot's actual position on the map
