# Technical Report: Architecture & Design Decisions
## CS5335 TurtleBot LLM Navigation — Instructor Meeting 2026-03-19

---

## 1. Current System Architecture

```
                        ┌──────────────────────────────────┐
                        │           User Input             │
                        │   (text / voice / ROS topic)     │
                        └───────────────┬──────────────────┘
                                        │
                    ┌───────────────────▼───────────────────┐
                    │          LLM Planner Node             │
                    │   Claude via OpenRouter (cloud API)    │
                    │                                       │
                    │  • Fast path: regex → skip LLM        │
                    │  • Full path: tool call loop           │
                    │  • Retry w/ exponential backoff        │
                    │  • 7 tools available                   │
                    └───────────────────┬───────────────────┘
                                        │ /tool_cmd (JSON + request_id)
                    ┌───────────────────▼───────────────────┐
                    │         Task Executor Node             │
                    │                                       │
                    │  Tools:                                │
                    │  • navigate_to      • clear_costmap    │
                    │  • get_robot_position • cancel_navigation│
                    │  • speak            • get_nav_status   │
                    │  • relocalize (NEW)                    │
                    │                                       │
                    │  Safety:                               │
                    │  • AMCL covariance monitoring          │
                    │  • Goal pre-validation                 │
                    │  • /system_status (1 Hz health check)  │
                    └───────────────────┬───────────────────┘
                                        │
┌────────────────────┐     ┌────────────▼────────────────────┐
│   RPi4 + Create3   │◄───►│     Nav2 Stack (on laptop)      │
│                    │ DDS  │  AMCL, planner, controller,     │
│  odom, scan, TF   │◄────►│  costmaps, bt_navigator         │
│  (FastDDS Disc.Svr)│     │  (lifecycle: manual activation)  │
└────────────────────┘     └─────────────────────────────────┘
```

**Key numbers:** 99 unit/integration tests passing, 7 LLM tools, 6 semantic map locations, 5 lab sessions completed.

---

## 2. Key Decision: FastDDS Discovery Server + Manual Lifecycle

### Problem
Nav2 lifecycle_manager requires DDS service discovery to transition nodes (configure → activate). FastDDS Discovery Server v2 filters out lifecycle service endpoints entirely (Nav2 #3560, rmw_fastrtps #499). This is a confirmed upstream bug.

### What we tried
| Approach | Result |
|----------|--------|
| SUPER_CLIENT XML profiles | Service endpoints still filtered |
| Custom lifecycle_activator.py node | Same discovery bug |
| Manual `ros2 lifecycle set` from CLI | Works but unreliable (DDS timeouts) |
| Two-process DDS bridge | Adds complexity, no reliability gain |
| CycloneDDS switch | Works, but lab default is FastDDS |

### Current solution
1. Keep lifecycle_manager in launch with `bond_timeout: 0.0` (won't kill nodes on bond failure)
2. deploy.sh manually activates each node with **retry + exponential backoff** (3 attempts, 5s → 10s → 20s)
3. Action server availability (`navigate_to_pose`) as the definitive readiness gate
4. task_executor waits on `nav_to_pose_client.wait_for_server()` instead of `waitUntilNav2Active()`

### Reference
- Nav2 navigation_launch.py uses `use_respawn` + `bond_timeout` for resilience
- KubeROS nav-slam uses action server polling as health check
- All surveyed open-source Nav2 projects use Simple Discovery or CycloneDDS

### Question for instructor
> We understand the lab requires FastDDS + Discovery Server. Given the lifecycle bug, is our manual activation approach acceptable for the final demo? Would it be preferable to run Nav2 on the RPi instead (avoiding the laptop-to-robot DDS dependency for lifecycle services)?

---

## 3. Key Decision: LLM Tool Call Loop (not ROSA/LangChain)

### Our approach
Hand-written OpenAI-compatible tool call loop:
- LLM receives user input + tool definitions
- LLM returns tool calls → we execute → feed results back → loop until done
- Fast path: regex matches simple commands ("go to table 1") and skips the LLM entirely
- Retry with exponential backoff (1s → 2s → 4s, 3 attempts) for transient API errors

### Why not ROSA (NASA JPL)?
ROSA uses LangChain ReAct agents with `@tool` decorators. Functionally equivalent, but:
- Adds LangChain as a heavy dependency (40+ transitive packages)
- Our tool loop is ~100 lines of Python, fully understood by the team
- The fast path (regex → direct execution, no API call) is not available in ROSA

### Reference
- NASA JPL ROSA: LangChain ReAct + @tool pattern (github.com/nasa-jpl/rosa)
- ROS-LLM (Auromix): code generation + regex parsing approach
- Our approach is closest to the OpenAI function calling pattern used by Mike Likes Robots + ROSA examples

### Question for instructor
> Is the hand-written tool loop acceptable, or would using an established framework like ROSA/LangChain be preferred for the final project? We can migrate if needed — the tool definitions are already in OpenAI function calling format.

---

## 4. Key Decision: Clock Sync via Chrony NTP Hierarchy

### Problem
Three independent clocks (laptop, RPi4, Create3). RPi has no battery-backed RTC — clock resets on every reboot. Create3 has its own internal NTP that drifts 5-12 seconds from RPi.

### Previous approach
`ssh date -s` — one-shot manual sync per session. No persistent sync. `transform_tolerance` set to 2-5 seconds to compensate (official default is 0.2).

### Current approach (deploy.sh v2)
```
Laptop (stratum 10, chrony server)
    └──NTP──→ RPi4 (stratum 11, chrony client+server)
                  └──NTP──→ Create3 (chrony client, via web UI config)
```
- `makestep 1 3` on RPi: jump clock if offset > 1s during first 3 updates
- deploy.sh auto-installs chrony on RPi, configures it to point at laptop
- Drift verification after sync (fallback to `date -s` if chrony fails)

### Reference
- Create3 official NTP docs (iroboteducation.github.io/create3_docs/setup/compute-ntp/)
- turtlebot4_setup ships chrony.conf (github.com/turtlebot/turtlebot4_setup)
- Clearpath Robotics NTP guide for multi-machine ROS2
- turtlebot4_robot#8, turtlebot4#404: documented Create3 NTP issues

### Question for instructor
> Once chrony is stable, we plan to reduce `transform_tolerance` from 2-5s back toward the default 0.2s. Is there a recommended tolerance for the lab environment? Also, does the Create3 in the lab already have NTP configured, or do we need to set it via the web interface?

---

## 5. Key Decision: AMCL Localization Recovery

### Problem
If the robot is moved between sessions, or localization degrades during operation, AMCL particles converge to the wrong location. Navigation silently fails. The user sees only a 120-second timeout.

### Current approach
1. **Detection**: Monitor AMCL covariance (`cov[0] + cov[7]` from amcl_pose). Threshold: 1.0 (combined xx + yy).
2. **Pre-validation**: Before sending any Nav2 goal, check localization health. Reject with actionable error if unhealthy.
3. **Recovery**: New `relocalize` tool available to the LLM:
   - Calls `reinitialize_global_localization` service (spreads particles across free space)
   - Commands robot to spin in place ~14s (collect diverse laser scans)
   - Checks if covariance improved
4. **System status**: `/system_status` topic at 1 Hz with localization health, nav status, issues list.

### Reference
- Nav2 AMCL publishes covariance natively (nav2_amcl/amcl_node.cpp)
- Nav2 provides `reinitialize_global_localization` service + BT node
- CMU Q Robotics Lab uses covariance < 0.65 as "localized" threshold
- Nav2 AutoLocalization pattern: spread → spin → backup → spin
- ROS 2 diagnostics framework (ros/diagnostics) for health aggregation
- TurtleBot4 diagnostics package (turtlebot4_diagnostics)

### Question for instructor
> Is the covariance threshold of 1.0 (combined xx+yy) reasonable for our classroom map? Should we also check yaw covariance (cov[35])? For the final demo, should we have a fallback to manually set initial pose via deploy.sh if automatic relocalization fails?

---

## 6. Reliability Improvements Summary

| Improvement | Before | After | Reference |
|---|---|---|---|
| Node crash recovery | None — silent failure | `respawn=True, respawn_delay=2-5s` | Nav2 PR #2910 |
| Lifecycle activation | Single blind attempt + sleep | 3 retries, exponential backoff | KubeROS health pattern |
| LLM API failure | Immediate error | 3 retries, backoff 1→2→4s + jitter | OpenAI SDK pattern |
| Thread safety | Unbounded `threading.Thread` | `ThreadPoolExecutor(max_workers=2)` | Python stdlib best practice |
| Clock sync | `date -s` one-shot | chrony NTP hierarchy | TurtleBot4 official setup |
| Localization loss | 120s timeout, no feedback | Covariance monitoring + auto relocalize | Nav2 global_localization |
| System health | No visibility | `/system_status` 1 Hz JSON | ROS 2 diagnostics framework |
| Goal validation | None — send and hope | Map bounds + localization check | ROSA tool validation |
| Tool result timeout | 120s (= nav timeout) | 135s (nav + 15s DDS buffer) | Timeout mismatch analysis |

---

## 7. Known Limitations & Open Questions

### Architecture
1. **Nav2 runs on laptop, sensors on RPi** — all sensor data traverses Discovery Server. Network hiccups break navigation. Moving Nav2 to RPi would help but may exceed RPi4's compute.
2. **Topic-based RPC** — tool_cmd/tool_result uses pub/sub topics to simulate request-response. Works in practice but not guaranteed delivery. ROS 2 Services would be more correct but require refactoring the test suite (99 tests).

### Practical
3. **Lab WiFi reliability** — the ASUS_98 router's ethernet doesn't bridge to WiFi. We need WiFi for robot communication + a second connection (phone hotspot) for LLM API access.
4. **Create3 power cycle** — some configuration changes require a physical power cycle of the Create3 base, which is difficult to do mid-session.

### For discussion
- What is the expected demo format? Pre-recorded + live? How many trials?
- Should we prioritize Tier 1 (single navigation) reliability or demonstrate the full LLM multi-step capability?
- Is there a preferred map/starting location for the demo?

---

## 8. File Map (for reference)

```
deploy.sh                          — Deployment orchestrator (clock + build + launch + activate)
stop.sh                            — Cleanup script

campus_guide_bot/campus_nav_llm/
├── launch/
│   └── navigation_mode.launch.py  — Main launch (Nav2 + LLM nodes, respawn enabled)
├── config/
│   └── nav2_combined_params.yaml  — Nav2 parameters (AMCL, costmap, planner, controller)
├── semantic/
│   └── semantic_map.json          — 6 named locations with aliases
├── maps/
│   └── my_map.yaml                — Occupancy grid map
├── campus_nav_llm/
│   ├── llm_planner_node.py        — LLM tool call loop + fast path + retry
│   ├── task_executor_node.py      — Tool execution + AMCL monitoring + relocalization
│   ├── odom_tf_publisher.py       — Odometry → TF bridge
│   ├── location_resolver.py       — Semantic map lookup + alias resolution
│   └── ...
└── tests/                         — 99 tests (location, tools, LLM, integration)
```
