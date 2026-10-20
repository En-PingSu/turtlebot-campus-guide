# Session Notes — March 16, 2026

## Summary

Attempted to bring up the full Nav2 stack on the laptop for testing on the physical TurtleBot4. Spent the session debugging the FastDDS Discovery Server incompatibility with Nav2 lifecycle managers. Concluded by switching the entire stack (Create3 + RPi + laptop) to CycloneDDS with Simple Discovery — pending Create3 power cycle to confirm.

## Root Cause Identified

**FastDDS Discovery Server v2 filters out lifecycle service endpoints**, preventing Nav2 lifecycle managers from discovering `get_state` and `change_state` services. This is a confirmed upstream bug:

- [Nav2 #3560](https://github.com/ros-navigation/navigation2/issues/3560) — confirmed FastDDS regression
- [rmw_fastrtps #499](https://github.com/ros2/rmw_fastrtps/issues/499) — CLI tools broken with Discovery Server
- [TurtleBot4 #546](https://github.com/turtlebot/turtlebot4/issues/546) — Nav2 doesn't run on local PC

**Fix**: Switch to CycloneDDS (confirmed by Nav2 maintainer Steve Macenski).

## What We Tried (FastDDS)

| Approach | Result |
|----------|--------|
| Lifecycle managers with `autostart: True` | Stuck "waiting for service" |
| Old launch (no lifecycle managers) + `activate_all.sh` | "unknown" state for all nodes |
| `activate_nav2.sh` with `--no-daemon` | "Node not found" |
| `ros2 lifecycle set` via daemon | "Node not found" |
| `SUPER_CLIENT` XML profile | No effect |
| Regular client XML profile | No effect |
| `ROS_SUPER_CLIENT=True/False` env var | No effect |
| Two-process DDS bridge (multiprocessing) | DS subscriber never received data |
| Single-process dual-context bridge | Can't have two DDS domains in one process |
| Long spin time `--spin-time 20` | Found 75 services but none from Nav2 nodes |
| Activating from RPi side | RPi also can't see laptop Nav2 services |

**Key finding**: `ros2 topic list` works (daemon sees topics), `ros2 service list` shows RPi services, but Nav2 lifecycle services are specifically filtered out by Discovery Server.

## CycloneDDS Switch (In Progress)

### Create3 (firmware H.2.6, Humble)
- H.x.x firmware supports both `rmw_fastrtps_cpp` and `rmw_cyclonedds_cpp`
- Changed via webserver (Application tab):
  - RMW_IMPLEMENTATION → `rmw_cyclonedds_cpp`
  - Disabled Fast DDS Discovery Server
- "Restart application" applied but Create3 needs **physical power cycle** to fully switch

### RPi (`/etc/turtlebot4/setup.bash`)
- Changed `RMW_IMPLEMENTATION` to `rmw_cyclonedds_cpp`
- Commented out `ROS_DISCOVERY_SERVER`
- Commented out `FASTRTPS_DEFAULT_PROFILES_FILE`
- Removed `ROS_SUPER_CLIENT` line (not needed for CycloneDDS)
- `CYCLONEDDS_URI` already pointed to `/etc/turtlebot4/cyclonedds_rpi.xml` (includes `usb0` + `wlan0`)

### Laptop (`launch_nav.sh`)
- Set `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`
- Cleared all Discovery Server env vars
- Using new launch file with lifecycle managers (from latest git pull)

### Status
- RPi nodes visible via CycloneDDS ✓
- Create3 nodes NOT visible — needs physical power cycle
- RPi was shut down (`sudo shutdown -h now`) and needs USB power cycle to reboot

## Files Modified

| File | Change |
|------|--------|
| `launch_nav.sh` | Switched to CycloneDDS Simple Discovery |
| `launch_bridge.sh` | NEW — two-process DDS bridge (may not be needed with CycloneDDS) |
| `dds_bridge_mp.py` | NEW — multiprocessing bridge DS↔SD (may not be needed) |
| `fastdds_client.xml` | NEW — regular client FastDDS profile (unused) |
| `bridge_sub.py` | NEW — bridge subscriber experiment (unused) |
| `bridge_topics.sh` | NEW — topic relay experiment (unused) |
| `campus_nav_llm/dds_bridge.py` | NEW — dual-context bridge attempt (unused) |

## RPi Setup (Current State)

```bash
# /etc/turtlebot4/setup.bash
export CYCLONEDDS_URI="/etc/turtlebot4/cyclonedds_rpi.xml"
#export FASTRTPS_DEFAULT_PROFILES_FILE="/etc/turtlebot4/fastdds_rpi.xml"
export ROBOT_NAMESPACE="/turtlebot468"
export ROS_DOMAIN_ID="0"
#export ROS_DISCOVERY_SERVER="127.0.0.1:11811;192.168.50.31:11811;"
export RMW_IMPLEMENTATION="rmw_cyclonedds_cpp"
export TURTLEBOT4_DIAGNOSTICS="1"
export WORKSPACE_SETUP="/opt/ros/humble/setup.bash"
source $WORKSPACE_SETUP
```

## Laptop CycloneDDS Setup Needed

Create `~/CS5335TurtleBot/cyclonedds_pc.xml`:
```xml
<CycloneDDS>
  <Domain>
    <General>
      <DontRoute>true</DontRoute>
    </General>
  </Domain>
</CycloneDDS>
```

Set env vars:
```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=~/CS5335TurtleBot/cyclonedds_pc.xml
```

## Next Session TODO

1. **Power cycle Create3**: Take off dock, hold ⏻ 20s, place back on dock. May need to unplug/replug RPi USB-C cable to reboot RPi.
2. **Verify CycloneDDS**: `timeout 15 ros2 topic hz "/turtlebot468/odom"` on RPi
3. **Test laptop**: Launch Nav2 with CycloneDDS, confirm lifecycle managers auto-activate
4. **If CycloneDDS fails**: Revert to FastDDS and deploy Nav2 to RPi instead
5. **Test full LLM loop**: `ros2 topic pub --once /user_input std_msgs/msg/String '{data: "go to the front door"}'`

## Backup Plan: Restore FastDDS

If CycloneDDS doesn't work after Create3 power cycle:
```bash
# RPi
sudo cp /etc/turtlebot4/setup.bash.bak /etc/turtlebot4/setup.bash
sudo systemctl restart turtlebot4.service

# Create3 webserver: RMW → rmw_fastrtps_cpp, enable Discovery Server
# Then deploy Nav2 to RPi instead of laptop
```

## Key Learnings

1. FastDDS Discovery Server is **fundamentally incompatible** with Nav2 lifecycle management — not a config issue, it's an upstream middleware bug
2. Create3 firmware H.2.6 supports CycloneDDS via webserver config change
3. The `create3_republisher` on the RPi bridges Create3 topics — both sides must use the same RMW
4. `CYCLONEDDS_URI` must be set for the daemon to discover CycloneDDS nodes
5. `FASTRTPS_DEFAULT_PROFILES_FILE` should be commented out when using CycloneDDS
6. Create3 needs physical power cycle (not just "Restart application") to fully switch RMW
