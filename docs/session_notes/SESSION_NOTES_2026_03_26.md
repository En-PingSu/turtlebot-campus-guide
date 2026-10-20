# Session Notes — 2026-03-26

## Summary

Comprehensive codebase bug audit, fixed 13 critical/high-severity bugs across 15 files,
and debugged FastDDS Discovery Server connectivity for laptop-only testing.

## Bug Audit & Fixes (15 files changed)

### Round 1: Critical Bugs (7 files)

| File | Bug Fixed |
|------|-----------|
| **chatgpt.py** | Function call response was discarded as `"null"` — LLM never saw robot action results. Fixed to use actual `response.response_text`. Also fixed race condition in `function_name` instance variable (captured in closure). Restored commented-out service wait with 10s timeout. |
| **task_executor_node.py** | `wait_for_server()` return value unchecked — node continued even if Nav2 was down. Now raises `RuntimeError`. Added `ThreadPoolExecutor.shutdown()` on exit. |
| **llm_planner_node.py** | Same `wait_for_server()` fix — raises on failure. Added `ThreadPoolExecutor.shutdown()`. Fixed `get_logger().info()` using printf-style `%d` args (ROS2 Humble uses f-strings). |
| **turtle_robot.py** | `getattr()` without default crashes on LLM-hallucinated function names. Added `None` default + callable check. JSON parsing wrapped in try/except. `reset_turtlesim()` now waits for service response. |
| **multi_robot.py** | Same `getattr()` fix. Publisher dict key mismatch — empty string stored as `""` but looked up as `"default"`. Unified to `"default"` throughout. |
| **arx5_arm_robot.py** | Same `getattr()` fix. `os.system()` command injection replaced with direct `self.target_pose_publisher.publish()`. Removed unused `import os`. |
| **dds_bridge.py** | Exceptions silently swallowed with bare `except: pass`. Now logs with traceback. Hardcoded namespace replaced with `os.environ.get("ROBOT_NAMESPACE", "turtlebot468")`. |

### Round 2: Configuration & Communication Bugs (8 files)

| File | Bug Fixed |
|------|-----------|
| **llm_planner_node.py** | Shallow copy race in conversation history — `list()` replaced with `copy.deepcopy()` to prevent concurrent thread corruption via `ThreadPoolExecutor`. |
| **launch_nav.sh** | Hardcoded `192.168.50.31` replaced with config.yaml reader (same pattern as deploy.sh). |
| **bridge_topics.sh** | Same — reads IP/port from config.yaml. Also uses `$SCRIPT_DIR` for paths. |
| **stop.sh** | Same — reads IP, namespace, and port from config.yaml. |
| **check_clock_offset.sh** | Same — reads from config.yaml. |
| **dds_bridge_mp.py** | Reads IP, port, and namespace from config.yaml via PyYAML. |
| **user_config.py** | `chat_history_max_length` changed from 4000 to 50 — was compared against message count (`len()`), not tokens. History grew unbounded. |
| **deploy.sh** | Line 173 overwrote `ROS_DISCOVERY_SERVER` unconditionally. Changed to `${ROS_DISCOVERY_SERVER:-${ROBOT_IP}:${DISCOVERY_PORT}}` so callers can override. Also fixed line 438-440: `tr -d '[:space:]'` to strip newlines from verification variables (bash syntax error). |

## Testing

- **99 unit tests pass** (0 failures) after all changes
- All Python files pass syntax check (`ast.parse` / `py_compile`)
- All shell scripts pass `bash -n` syntax check

## FastDDS Discovery Server Debugging

### Problem
`lifecycle_activator` waited 90s and discovered 0 of 9 lifecycle services,
even though all 9 Nav2 nodes were running on the laptop.

### Root Cause
The Discovery Server runs on the RPi at `192.168.50.31:11811`. The RPi was
unreachable (powered off since 03/16). Without a broker, no DDS participants
can discover each other — even on the same machine.

### Solution
Start a local Discovery Server on the laptop for testing:

```bash
# Terminal 1 (leave running):
fastdds discovery --server-id 0 --udp-address 127.0.0.1 --udp-port 11811

# All other terminals:
export ROS_DISCOVERY_SERVER="127.0.0.1:11811"
```

The GUID prefix `44.53.00.5f.45.50.52.4f.53.49.4d.41` (from `--server-id 0`)
matches the existing XML profiles, so no XML changes needed.

### Verification
With local Discovery Server:
- All 9 lifecycle services discovered
- Phases 1-4.5 of lifecycle_activator all succeed
- map_server activated, map loaded, AMCL received map + initial pose
- Phase 5 (costmap activation) blocks on missing `odom→base_link` TF — expected without robot

### deploy.sh Fix
deploy.sh line 173 previously hardcoded `ROS_DISCOVERY_SERVER` from config.yaml,
ignoring any value set by the caller. Fixed to use `${ROS_DISCOVERY_SERVER:-default}`
so a local Discovery Server can be used for testing.

## Files Modified

| File | Lines Changed |
|------|--------------|
| `chatgpt.py` | +25 / -15 |
| `task_executor_node.py` | +6 / -2 |
| `llm_planner_node.py` | +14 / -5 |
| `turtle_robot.py` | +16 / -8 |
| `multi_robot.py` | +16 / -10 |
| `arx5_arm_robot.py` | +13 / -10 |
| `dds_bridge.py` | +8 / -4 |
| `dds_bridge_mp.py` | +18 / -2 |
| `user_config.py` | +3 / -2 |
| `launch_nav.sh` | +13 / -3 |
| `bridge_topics.sh` | +13 / -4 |
| `stop.sh` | +16 / -5 |
| `check_clock_offset.sh` | +13 / -3 |
| `deploy.sh` | +4 / -3 |
| `docs/superpowers/plans/2026-03-26-critical-bug-fixes.md` | NEW |

## Known Remaining Issues

1. **RPi still down** — needs USB-C unplug/replug to boot
2. **RPi still on CycloneDDS** — needs `turtlebot4-setup` to restore FastDDS + Discovery Server
3. **No robot E2E testing yet** — Phase 2 code still unvalidated on hardware
4. **TF timeout without robot** — costmap nodes block on `odom→base_link` (expected)
5. **Lifecycle discovery under Discovery Server** — works with persistent participant
   (`lifecycle_activator`), but only when a Discovery Server is actually running

## Next Session

1. Boot RPi (USB-C unplug/replug)
2. Restore FastDDS + Discovery Server on RPi via `turtlebot4-setup`
3. Power cycle Create3 (undock, hold power 20s, redock)
4. Run `./deploy.sh --pose charging_station` (RPi Discovery Server)
5. Test navigation: "go to front_door"
6. Test LLM loop: "take me to the table closest to the door"
7. For laptop-only testing: `fastdds discovery --server-id 0 --udp-address 127.0.0.1 --udp-port 11811`
