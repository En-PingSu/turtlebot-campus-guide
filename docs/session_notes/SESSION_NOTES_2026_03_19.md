# Session Notes — 2026-03-19

## Summary

Major reliability overhaul: replaced Nav2 lifecycle_managers with a persistent
Python lifecycle activator node, fixed multiple dashboard issues, resolved
robot I2C hardware issue, and created architecture documentation.

## Changes (9 files, +1057 / -230 lines)

### 1. Lifecycle Activator (`lifecycle_activator.py`) — NEW/REWRITTEN

**Problem**: `ros2 lifecycle set` CLI creates a new DDS participant per call
(2-3s each × 18 calls = 54s+). FastDDS Discovery Server drops responses from
short-lived participants (rmw_fastrtps #392). Lifecycle managers race with
manual CLI activation (Nav2 #3560).

**Solution**: Single persistent Python node that discovers all 9 lifecycle
services once, then transitions nodes in 5 phases:

| Phase | Action | Why |
|-------|--------|-----|
| 1 | Configure all 9 nodes | Get to inactive state |
| 2 | Activate map_server | Publishes /map |
| 3 | Activate AMCL | Subscribes to /map (must be right after Phase 2) |
| 4 | Reload map via load_map service | transient_local fallback |
| 4.5 | **Publish initial pose** | AMCL needs pose to publish map→odom TF; costmaps block without it |
| 5 | Activate remaining 7 Nav2 nodes | Costmaps can now find map frame |

**Key features**:
- `_get_state()` retries 3× with 5s timeout (FastDDS drops responses)
- `_poll_state()` waits up to 30s for nodes loading plugins
- 3s settling delay after discovery (DDS request/reply matching)
- Sends initial pose before Phase 5 to unblock costmap TF lookups
- Exit code 0/1 for deploy.sh to check

**Performance**: Discovery ~16-22s (one-time), activation ~2-5s. Total ~25-50s
vs 90-180s with CLI approach.

### 2. Launch File (`navigation_mode.launch.py`) — MODIFIED

- **Removed both lifecycle_managers** entirely (localization + navigation)
- Eliminates "Waiting for service..." DDS polling noise
- Removed unused `bond_timeout` launch argument
- 10 nodes launched (was 12)

### 3. Deploy Script (`deploy.sh`) — MAJOR CHANGES

**Step 1 improvements**:
- Robot topic wait increased from 45s to 90s
- Double `ros2 topic list` call per poll (TurtleBot4 docs recommendation)
- Daemon restart at 45s if topics still missing
- Added connectivity check when `--skip-clock` (was skipping entirely)
- Actionable troubleshooting steps in error message

**Step 3 improvements**:
- Aggressive stale process cleanup: kills all Nav2 executables by path pattern
  (`/map_server `, `/bt_navigator `, etc.) — fixes ghost lifecycle_managers
  from previous deploys that were blocking service discovery

**Step 5 rewritten**:
- Replaced 18 CLI calls with single `lifecycle_activator` node invocation
- Passes initial pose (x, y, yaw) as parameters
- 180s timeout with CLI fallback if activator fails

**Step 7 improved**:
- Publishes initial pose 3× with 2s gaps (was fire-and-forget once)
- Verifies AMCL received pose via amcl_pose echo
- (Now partially redundant — Phase 4.5 handles this)

### 4. Dashboard (`dashboard_server.py` + `index.html`) — MULTIPLE FIXES

**New features**:
- OpenRouter API key save/load (`GET/POST /api/apikey`)
- API key passed to deploy subprocess as `OPENROUTER_API_KEY` env var
- Deploy log copy button
- Deploy log panel enlarged (120px → 300px, 11px font)

**Stop button fixes**:
- `start_new_session=True` on Popen — deploy runs in own process group
- `os.killpg(pgid, SIGKILL)` — kills entire process group immediately
- `pkill -9 -f` fallback for orphaned processes
- HTTP `POST /api/deploy-stop` fallback when WebSocket is down
- Stop button always enabled (never disabled)
- Button state restored on WebSocket reconnect via `/api/deploy-status`
- Fixed `NoneType` crash when stop races with deploy thread

**Other fixes**:
- Fixed `Request` type annotation on `save_apikey` endpoint
- Added `import signal` for process group kill
- Deploy button toggles immediately (doesn't wait for WebSocket)

### 5. Stop Script (`stop.sh`) — UPDATED

- Kill patterns match full executable paths (`/map_server `, `/bt_navigator `)
- Added `lifecycle_manager`, `lifecycle_activator`, `odom_tf_publisher`
- Uses SIGKILL (-9) for reliability

### 6. Architecture Diagram (`architecture_diagram.md`) — NEW

Full system architecture documentation for technical meeting:
- System overview with ASCII diagrams
- Deployment flow (9 steps)
- Lifecycle activation detail (key innovation)
- Network topology
- Semantic map locations
- Known issues table
- Test coverage summary

### 7. Setup & Config

- `setup.py`: Added `lifecycle_activator` entry point
- `.gitignore`: Added `.openrouter_key`

## Robot Hardware Fix

**I2C Bus Error**: `turtlebot4_base_node` stuck in infinite I2C error loop,
consuming resources and preventing `create3_republisher` from registering
with Discovery Server. No topics visible despite nodes running.

**Root cause**: I2C bus (`/dev/i2c-3`) communication failure between RPi and
TurtleBot4 PCBA (display/buttons board).

**Fix**: Changed RPi launch from `model=standard` to `model=lite` in
`/etc/ros/humble/turtlebot4.d/standard.launch.py`. Skips `turtlebot4_base_node`
entirely. Loses OLED display and buttons but all navigation functionality
preserved (odometry, LIDAR, Create3 communication all use USB, not I2C).

Backup at: `/etc/ros/humble/turtlebot4.d/standard.launch.py.bak`

## Known Remaining Issues

1. **AMCL initial pose timing**: "Failed to transform initial pose in time" —
   TF timestamps sometimes don't match. AMCL still accepts pose but warns.
   Works on retry. Clock drift is <10ms (not the cause).

2. **Discovery Server service discovery**: First `get_state` call after
   discovery sometimes times out. 3s settling delay helps but doesn't
   fully eliminate. FastDDS request/reply topic matching is fundamentally
   asynchronous (rmw_fastrtps #392).

3. **`planner_server` slow discovery**: Consistently last service discovered
   (30-60s after others). Creates global_costmap sub-node with additional
   DDS endpoints.

4. **DDS topic visibility**: Short-lived CLI participants (`ros2 topic pub`,
   `ros2 topic echo`) often can't see topics under Discovery Server. Persistent
   Python nodes work reliably. Dashboard ROS bridge may need restart after
   deploy.

5. **Step 7 redundant**: Initial pose is now set in Phase 4.5 of
   lifecycle_activator. Step 7 repeats it via CLI (slow due to Discovery
   Server). Consider removing.

## Research References

- [ros2cli #779](https://github.com/ros2/ros2cli/issues/779) — CLI lifecycle calls too slow
- [rmw_fastrtps #392](https://github.com/ros2/rmw_fastrtps/issues/392) — Service discovery race
- [rmw_fastrtps #499](https://github.com/ros2/rmw_fastrtps/issues/499) — CLI tools need SUPER_CLIENT
- [Nav2 #3560](https://github.com/ros-navigation/navigation2/issues/3560) — Discovery Server lifecycle bug
- [Nav2 #3033](https://github.com/ros-navigation/navigation2/issues/3033) — FastDDS hangs lifecycle manager
- [TurtleBot4 #172](https://github.com/turtlebot/turtlebot4/issues/172) — Topics not visible (firewall)
- [TurtleBot4 #473](https://github.com/turtlebot/turtlebot4/issues/473) — RPi-Create3 USB connection
- [TurtleBot4 #657](https://github.com/turtlebot/turtlebot4/issues/657) — odom not publishing
- [turtlebot4_robot #29](https://github.com/turtlebot/turtlebot4_robot/issues/29) — I2C bus error
- [eProsima FastDDS Discovery Server docs](https://fast-dds.docs.eprosima.com/en/latest/fastdds/ros2/discovery_server/ros2_discovery_server.html)
- [TurtleBot4 Discovery Server manual](https://turtlebot.github.io/turtlebot4-user-manual/setup/discovery_server.html)
