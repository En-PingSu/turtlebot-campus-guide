# Session 3 — March 13, 2026

## Summary

Attempted to deploy the LLM-guided campus navigation system on the physical
TurtleBot4 at Northeastern University Vancouver. The session focused on
debugging DDS Discovery Server incompatibilities with Nav2 lifecycle management,
and concluded with extensive research into alternative approaches.

## Key Findings

### 1. FastDDS Discovery Server Breaks Nav2 Lifecycle Management

The TurtleBot4 uses FastDDS Discovery Server for ROS2 communication. We
discovered that **Discovery Server v2 filters out service endpoints**, which
completely prevents Nav2 lifecycle managers from discovering `get_state` and
`change_state` services on Nav2 nodes.

This is a **known, unfixed upstream bug** confirmed in:
- Nav2 #3560, #3033
- TurtleBot4 #479, #546

Without lifecycle activation, the entire Nav2 stack (map_server, AMCL,
controller_server, planner_server, etc.) stays in "unconfigured" state and
cannot process navigation goals.

### 2. All Workarounds Failed

| Approach | Result |
|----------|--------|
| SUPER_CLIENT XML profile | Services still not discovered |
| `ROS_SUPER_CLIENT=TRUE` env var | No effect on service discovery |
| `bond_timeout: 0.0` | Lifecycle manager still waits forever |
| Custom `lifecycle_activator.py` node | Same service discovery bug |
| `ros2 lifecycle set --no-daemon` | `ros2 node list` returns empty |
| Nav2 composition mode (`LoadComposableNodes`) | Composition uses DDS service calls to load nodes into container — also blocked |
| Manual `ros2 lifecycle set` commands | Node not found |
| Waiting 5+ minutes for DDS discovery | No change |

### 3. Composition Mode Discovery

We confirmed that Nav2 composition mode (all nodes in a single
`component_container_isolated` process) **works perfectly without Discovery
Server** — lifecycle managers configure and activate nodes via intra-process
communication.

However, `LoadComposableNodes` itself is a launch-system action that makes a
DDS service call from the launch process to the container process. Discovery
Server blocks this call too, so **composition mode cannot be used with
Discovery Server**.

### 4. Open-Source LLM Robot Navigation Research

Surveyed 10+ open-source LLM+robot navigation projects (ROSGPT, RAI, ROSA,
ROS-LLM, TidyBot, etc.). Key insight: **none of them manage Nav2 lifecycle
from the LLM layer**. They all assume Nav2 is already running and active,
then send goals via `BasicNavigator.goToPose()` or topic pub/sub.

Most projects use **Simple Discovery** (standard multicast DDS) and avoid
Discovery Server entirely.

### 5. Our Architecture Is Sound

The codebase architecture (LLM planner → tool calls → task executor →
BasicNavigator) matches the patterns used by successful open-source projects
like ROSGPT and RAI. The blocker is purely the DDS configuration on the robot.

## Bugs Fixed

1. **Race condition in LLM planner**: Added `_processing` guard with
   `_processing_lock` to prevent concurrent request handling when Discovery
   Server delivers duplicate messages.

2. **ROS logger format strings**: Changed `self.get_logger().info("msg: %s", var)`
   to f-strings — `RcutilsLogger` does not support `%s` format.

3. **Missing odom→base_link TF**: Created `odom_tf_publisher.py` to bridge
   `/turtlebot468/odom` (Odometry msg) to TF, since Create3's `create3_repub`
   does not publish this transform.

4. **Create3 clock drift**: Synced Create3 NTP via
   `curl -s -X POST http://192.168.186.2/api/restart-ntpd` after discovering
   odom timestamps were 2.3 years behind.

## New Files Created

- `odom_tf_publisher.py` — Bridges Odometry messages to TF transforms
- `lifecycle_activator.py` — Attempted lifecycle activation via rclpy (unused)
- `nav2_combined_params.yaml` — Merged localization + navigation params
- `activate_nav2.sh` — Manual lifecycle activation script (fails with Discovery Server)
- `fastdds_super_client.xml` — DDS SUPER_CLIENT profile (insufficient)
- `deploy.sh` — Automated deployment script

## Mistakes / Lessons Learned

1. **Assumed DDS services work like topics**: Spent significant time debugging
   lifecycle activation before discovering that Discovery Server fundamentally
   cannot propagate service endpoints. Should have researched this limitation
   upfront before writing workaround code.

2. **Tried too many workarounds before researching**: Built a custom
   `lifecycle_activator.py`, tried composition mode, tried `--no-daemon` CLI
   flags — all suffered from the same root cause. Earlier online research
   would have saved hours.

3. **Did not test composition mode isolation**: Assumed `LoadComposableNodes`
   was intra-process, but it's actually a DDS service call from the launch
   process. Should have tested in a minimal example first (which we eventually
   did, confirming it works without Discovery Server).

4. **Create3 USB link fragility**: The Create3 USB communication link dropped
   during testing, causing stale odom data. We didn't notice until timestamps
   were 50+ minutes old. Should add timestamp staleness monitoring.

5. **Hardcoded Discovery Server assumptions**: The codebase assumed Discovery
   Server throughout (e.g., skipping action server waits, SUPER_CLIENT XML).
   This made it harder to switch approaches. Configuration should be
   environment-driven.

## Resolution: Switch to Simple Discovery

The only viable fix is to reconfigure the robot to use **Simple Discovery**
(standard DDS multicast) instead of Discovery Server. This requires:

1. SSH into robot RPi, edit `/etc/turtlebot4/setup.bash` to remove
   `ROS_DISCOVERY_SERVER` and `FASTRTPS_DEFAULT_PROFILES_FILE`
2. Disable Discovery Server in Create3 webserver (`http://192.168.186.2/ros-config`)
3. Restart `turtlebot4.service`
4. On laptop, unset Discovery Server env vars

This change will make Nav2 lifecycle management, composition mode, and all
ROS2 CLI tools work as expected. Every successful open-source LLM+robot
project uses Simple Discovery or CycloneDDS.

## Next Session TODO

- [ ] Switch robot to Simple Discovery (SSH required)
- [ ] Test Nav2 lifecycle activation with Simple Discovery
- [ ] Set initial pose at charging station and test navigation
- [ ] Test end-to-end LLM command: "take me to table 1"
- [ ] Add navigation timeout to prevent infinite poll loops
- [ ] Add LLM API error handling with user-facing messages
