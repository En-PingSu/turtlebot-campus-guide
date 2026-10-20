# Session Notes — 2026-04-10

## Summary

Major dashboard improvements session: fixed odom recovery chain with root-cause diagnosis, added semantic map location editor (add/edit/delete with reachability validation), fixed multiple deployment blockers (config.yaml format corruption, dock action type, dashboard not in ROS mode), and added AMCL auto-recovery watchdog to llm_planner.

## Key Accomplishments

### 1. Odom Recovery Chain — Complete Rewrite

**Problem**: The preflight odom fix always blamed Create3, but today's failure was turtlebot4.service stale after 4 weeks. The old chain wasted ~2 min on app restarts that couldn't help.

**Root cause found**: `ROS_SUPER_CLIENT=False` over SSH. The RPi's `/etc/turtlebot4/setup.bash` uses `[ -t 0 ]` to detect terminal — sshpass SSH has no tty, so all `ros2` commands ran as non-super-client and couldn't discover topics.

**Fixes applied**:

| Change | Detail |
|--------|--------|
| `ROS_SUPER_CLIENT=True` override | Added `export ROS_SUPER_CLIENT=True` in all 5 SSH ros2 command locations |
| New `_diagnose_odom_failure()` function | Checks node list + topic list to determine root cause before picking fix |
| Smart diagnosis decision tree | No Create3 nodes → full_recovery; TB4 nodes missing → restart_turtlebot4; DDS stale → restart_turtlebot4; odom specifically dead → restart_create3_app |
| `restart_turtlebot4` action rewritten | Now: restart service → restart daemon on RPi → poll topics → verify odom → chain to next fix if needed |
| `restart_create3_app` action rewritten | Checks topic count first — if 0 Create3 topics, skips straight to full_recovery; polls Create3 webserver instead of blind 40s sleep |
| `full_recovery` action rewritten | Correct order: clean DDS shared memory → reboot Create3 → poll webserver → poll topic registration (up to 90s) → THEN restart TB4 → restart daemon → verify odom |

**Key learnings**:
- turtlebot4.service can go stale after weeks — nodes visible but topics not registered
- `ros2 node list` can show stale/cached nodes that `ros2 node info` can't find
- Always restart ros2 daemon after turtlebot4 service restart

### 2. Preflight Progress Log

Added inline progress log to the preflight panel in the dashboard:
- System messages with `[preflight]` prefix now appear in a scrollable log below the check items
- Color-coded: purple for steps, green for success, red for errors
- Auto-clears on new fix or re-running checks
- No longer need to "check chat for status" — progress visible directly in preflight panel

### 3. Right Panel Scrollability

**Problem**: After preflight checks expand (with log) and deploy log grows, the "Navigate to" section was pushed off-screen with no way to scroll.

**Fix**: Split right panel into scrollable `right-panel-top` (all control panels) and pinned `chat-area` + `input-area` at bottom.

### 4. Dashboard ROS Mode — Critical Fix

**Problem**: Dashboard was running since Apr 9 **without `--ros` flag** (PID 20058, demo mode). All "Navigate to" clicks went through demo handler — robot never received commands.

**Fix**: Killed old process, restarted with `--ros`. The `run.sh` also had `python` (not `python3`), so had to start manually with full env sourcing.

### 5. Dock Action Type Fix

**Problem**: Dock button used `irobot_create_msgs/action/DockServo` which doesn't exist.

**Fix**: Changed to `irobot_create_msgs/action/Dock` (verified via `ros2 action info`). Undock type `irobot_create_msgs/action/Undock` was already correct.

### 6. Semantic Map Location Editor

Added full CRUD for semantic map locations in the dashboard:

**Add Location**:
- Click `+ Add Location` button → click map → fill form (name, description, aliases, facing, area) → Save
- Auto-validates against occupancy grid map: rejects positions on walls, in unknown areas, or too close to obstacles (< robot_radius + safety margin)
- Suggests nearest safe position if validation fails, with one-click "Use suggested position" button
- Saves to `semantic_map.json` (source + install copy) + `config.yaml`

**Edit Location**:
- Right-click any destination button → edit dialog
- Click map while dialog open to reposition
- Same validation on save

**Delete Location**:
- Right-click → Delete button with confirmation
- Removes from `semantic_map.json` and `config.yaml`

**Bug fixed**: `buildDestButtons()` didn't clear old buttons — adding a location duplicated all existing buttons. Fixed with `container.innerHTML = ''`.

### 7. config.yaml Format Corruption — Critical Fix

**Problem**: `_save_semantic_and_config` used `yaml.dump()` which:
1. Removed quotes around string values
2. Expanded inline flow style `{x: 5.19, y: 2.56}` to multi-line
3. Didn't quote keys with spaces: `charging station` instead of `charging_station`
4. Lost underscore consistency: `table3` instead of `table_3`

**Impact**: `deploy.sh` couldn't parse poses → empty x/y/theta → lifecycle_activator crash (`-p initial_pose_y:=` with no value) → AMCL started without initial pose → converged to wrong location → all navigation failed with "failed to create plan"

**Fix**:
- `_save_semantic_and_config` now writes config.yaml manually in inline flow style matching the original format
- Keys normalized: spaces → underscores
- Fixed `semantic_map.json` inconsistencies: `charging station` → `charging_station`, `table3` → `table_3`, `table6` → `table_6`

### 8. AMCL Auto-Recovery Watchdog

**Problem**: AMCL silently stops publishing `map→odom` TF when laptop↔RPi clock drifts. Required manual "Relocalize" click (which spins the robot).

**Solution**: Added `_amcl_watchdog()` timer to `llm_planner_node` (runs every 3s):
- Detects AMCL stale (no update for >15s)
- Auto-syncs RPi clock via `chronyc makestep` (background thread)
- Republishes initial pose at last known (x, y, yaw) with stamp=0 (avoids clock issues)
- 30s cooldown between recovery attempts
- Logs recovery events to event logger

**Advantage over manual relocalize**: No robot movement, invisible recovery, fully automatic, also fixes root cause (clock).

### 9. Chinese Deployment Guide

Created `DEPLOY_GUIDE_CN.md` — complete deployment guide in Chinese covering:
- Environment setup, one-click deploy, dashboard usage
- Semantic map management, common troubleshooting
- Debug commands, deployment checklist

## Architecture Changes

### Odom Diagnosis Decision Tree
```
Odom fails → _diagnose_odom_failure():
  ├── No Create3 nodes          → full_recovery (GUID mismatch)
  ├── Create3 OK, TB4 missing   → restart_turtlebot4 (service stale)
  ├── Both exist, 0 topics      → restart_turtlebot4 (DDS stale)
  └── Topics exist, odom dead   → restart_create3_app (app stuck)
```

### AMCL Watchdog Flow
```
Every 3s:
  ├── AMCL healthy?           → do nothing
  ├── High covariance?        → ignore (let settle)
  └── Not publishing (>15s)?  →
        1. chronyc makestep (background)
        2. Republish initialpose at last known pose
        3. Log event, 30s cooldown
```

### Location Validation
```
Add/Edit location → _validate_location(x, y):
  ├── Out of map bounds?        → reject
  ├── On wall (pixel=0)?        → reject + suggest nearest safe
  ├── Unknown area (pixel=205)? → reject + suggest nearest safe
  ├── Too close (< 0.225m)?     → reject + suggest nearest safe
  └── OK                        → save to semantic_map.json + config.yaml
```

## Files Changed

- `dashboard/dashboard_server.py` — odom diagnosis, recovery chain rewrite, location CRUD API with validation, dock type fix, config.yaml writer fix
- `dashboard/static/index.html` — preflight progress log, right panel scroll, add/edit/delete location UI, fix button labels, chain fix on failure
- `campus_nav_llm/llm_planner_node.py` — AMCL watchdog auto-recovery
- `campus_nav_llm/semantic/semantic_map.json` — key naming fixes (underscores)
- `config.yaml` — restored correct format, all poses with underscored keys
- `DEPLOY_GUIDE_CN.md` — new Chinese deployment guide
- `SESSION_NOTES_2026_04_10.md` — this file
