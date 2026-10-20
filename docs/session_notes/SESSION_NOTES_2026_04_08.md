# Session Notes — 2026-04-08

## Summary

Extended debugging and optimization session. Diagnosed and fixed multiple systemic issues: ros2 daemon cache bug, ROS logger format crash, AMCL clock mismatch causing silent failures, navigation coordinates on walls/too close to obstacles, and relocalization scattering particles unnecessarily. **First successful autonomous navigation achieved** (robot reached goal). Major dashboard and infrastructure improvements. Remaining issue: AMCL intermittently stops publishing due to laptop↔RPi clock drift.

## Key Accomplishments

### 1. Chrony Time Sync Verification
- Confirmed chrony running on laptop (17+ hours, drift < 1ms)
- RPi reachable (ping ~3ms), clock drift within range
- However, discovered chrony `makestep` in deploy.sh doesn't reliably correct large drifts (2.7s offset found mid-session)
- Manual `sudo chronyc -a makestep` on RPi required before each deploy

### 2. Diagnosis: Empty `ros2 topic list` Under Discovery Server
- **Root cause**: `ros2 daemon` cache becomes stale under FastDDS Discovery Server
- `ros2 node list` works fine (returns 20+ nodes), but `ros2 topic list` returns only 2
- **Fix**: `ros2 daemon stop && ros2 daemon start`
- Wasted ~45 minutes misdiagnosing as Create3 connectivity issue

### 3. ROS Logger Format Bug (Critical Fix)
- **Bug**: `do_relocalize()` used `%s`/`%.0f` format args with ROS2 `get_logger().info()`, which only accepts f-strings
- **Error**: `RcutilsLogger.info() takes 2 positional arguments but 3 were given`
- **Impact**: Relocalization always failed with "internal software error"
- **Fix**: Converted 3 calls to f-strings in `task_executor_node.py` (lines 79, 124, 130)

### 4. AMCL Clock Mismatch — Root Cause Analysis
- **Problem**: AMCL runs on laptop, odom/scan/TF come from RPi. Clock mismatch (40ms to 3s) causes:
  - "Failed to transform initial pose in time (extrapolation into the future/past)"
  - "Message Filter dropping message: timestamp earlier than all data in transform cache"
  - AMCL sets initial pose but then **never publishes amcl_pose or map→odom TF**
- **Diagnosis path**:
  - odom_tf_publisher passes RPi timestamps → AMCL uses laptop clock for lookups → mismatch
  - Tried using laptop clock in odom_tf_publisher → broke scan Message Filter (scan timestamps from RPi don't match laptop TF timestamps)
  - stamp=0 in initial pose → helps initial pose but doesn't fix ongoing scan processing
- **Solution applied**: AMCL `transform_tolerance` increased from 2.0 → 5.0 (matching other Nav2 components)
- **Result**: AMCL now starts publishing after deploy, but can intermittently stop during navigation if clock drifts
- **Long-term fix**: Move AMCL to RPi (same clock as sensors) or ensure sub-100ms chrony sync

### 5. Navigation Coordinate Fixes
Multiple locations had coordinates on walls or too close to obstacles (< robot_radius 0.175m):

| Location | Old Coords | New Coords | Issue |
|----------|-----------|-----------|-------|
| charging_station | (2.0, 1.0) then (0.25, -0.29) | (-0.10, -0.24) | On wall (pixel=0) |
| back_door | (-1.56, 1.06) | (-1.56, 0.86) | 0.141m from wall < 0.175m robot_radius |
| front_door | (5.19, 2.76) | (5.19, 2.56) | 0.141m from wall < 0.175m robot_radius |

- **Critical**: `config.yaml` is the "single source of truth" but was not updated initially — deploy.sh loaded old coords from config.yaml, overriding our fixes
- Created `validate_coordinates.py` script to automatically check all coordinates

### 6. Relocalization Redesign
- **Problem**: `do_relocalize()` called `reinitialize_global_localization` which scatters particles across entire map. 14s spin insufficient for convergence. Each retry made covariance worse (2.8 → 13.2 → 25.0)
- **Fix**: Removed global relocalization entirely. Relocalize now only does spin-to-refine (rotate in place to collect fresh laser data)
- **Rationale**: In a known environment with a known starting position, global relocalization is never needed

### 7. First Successful Navigation!
- After all fixes, robot successfully navigated to a goal: `"Goal succeeded"`
- Second navigation failed due to AMCL stopping (clock drift)

### 8. Dashboard Enhancements
- **Restart ROS2 Daemon** button — one-click fix for stale topic cache
- **System Logs** panel — full-screen log viewer with:
  - Sidebar listing all deploy/lifecycle/event/session logs
  - Tab filters (All/Deploy/Lifecycle/Events/Sessions/Diagnostics)
  - Syntax-highlighted log viewer (errors=red, warnings=orange, steps=blue)
  - JSONL structured rendering for event logs
  - **Diagnostics tab**: real-time system checks (nodes, topics, RPi ping, Discovery Server, clock drift, chrony)
- Map padding fix (90% scale to prevent edge clipping)

### 9. Nav2 Parameter Optimization
Based on open-source project research:

| Parameter | Old | New | Reason |
|-----------|-----|-----|--------|
| `inflation_radius` | 0.45 | 0.80 | Push paths away from walls |
| `cost_scaling_factor` | 4.0 | 2.0 | Smoother cost decay, paths more centered |
| `BaseObstacle.scale` | 0.02 | 0.05 | Controller respects obstacles more |
| `laser_max_range` (AMCL) | 100.0 | 12.0 | Match RPLidar A1 actual max |
| `min_particles` (AMCL) | 200 | 500 | Improve localization reliability |
| `transform_tolerance` (AMCL) | 2.0 | 5.0 | Handle laptop↔RPi clock mismatch |

### 10. Deploy.sh Improvements
- AMCL health check in Step 6 — verifies AMCL is publishing pose before declaring success
- Removed hardcoded INIT_X/Y/THETA — now fully driven by --pose argument
- Coordinate validation script `validate_coordinates.py`

## Architecture Findings

### Clock Synchronization — Root Cause Found and Fixed
- **Root cause**: RPi chrony used `makestep 1 3` (Ubuntu default) — only steps clock for first 3 updates, then switches to gradual slew which takes minutes/hours for 2-3s drift
- **Fix**: Changed RPi chrony to `makestep 0.1 -1` — steps clock immediately if offset > 100ms, on every update forever
- Also added `minpoll 0 maxpoll 2` — chrony queries every 4 seconds instead of 64 seconds
- Also added `rtcsync` — syncs hardware clock for persistence across reboots
- **Result**: Clock offset reduced from 2-3 seconds to < 1ms (verified via `chronyc tracking`)
- **Impact**: Combined with `transform_tolerance: 5.0`, AMCL should never fail due to clock drift again
- TF tree has mixed clocks: `odom→base_link` (RPi clock) and `map→odom` (laptop clock). With < 100ms drift and 5.0s tolerance, this is safe

### config.yaml is the Real Source of Truth
- deploy.sh loads from config.yaml first, falls back to hardcoded values
- Must update config.yaml when changing coordinates, not just deploy.sh/semantic_map.json
- Three places to update coordinates: config.yaml, semantic_map.json (source + build + install copies), deploy.sh

### AMCL Failure Mode
- AMCL can silently stop publishing after initial pose succeeds
- No error messages — just stops updating
- Caused by TF lookup failures due to clock mismatch
- New AMCL health check in deploy.sh catches this at deploy time

## Pending (Next Session)
- **Verify chrony fix**: Confirm `makestep 0.1 -1` keeps drift < 100ms throughout a full session
- **Verify all coordinates**: Drive robot to each location, read actual AMCL coordinates, update semantic_map
- **E2E navigation test**: Full route test (front_door → table_1 → back_door → charging_station)
- **Create3 odom reliability**: Create3 periodically stops publishing odom, requiring app restart
- **AMCL on RPi** (only if chrony fix insufficient): Evaluate moving AMCL to RPi

## Files Changed
- `config.yaml` — updated all known_poses coordinates
- `deploy.sh` — updated coordinates, added AMCL health check, removed hardcoded INIT defaults
- `dashboard/dashboard_server.py` — Restart ROS2 Daemon endpoint, System Logs API (list/read/diagnostics)
- `dashboard/static/index.html` — Restart ROS2 Daemon button, System Logs panel, map padding fix
- `campus_nav_llm/task_executor_node.py` — fixed ROS logger format bug, removed global relocalization, spin-only relocalize
- `campus_nav_llm/lifecycle_activator.py` — initial pose stamp=0 for clock tolerance
- `campus_nav_llm/config/localization_params.yaml` — AMCL transform_tolerance 2.0→5.0
- `campus_nav_llm/config/nav2_combined_params.yaml` — all Nav2 parameter optimizations
- `campus_nav_llm/config/nav2_params.yaml` — inflation/cost scaling updates
- `campus_nav_llm/semantic/semantic_map.json` — coordinate fixes (all copies)
- `validate_coordinates.py` — new coordinate validation script
- `SESSION_NOTES_2026_04_08.md` — this file
