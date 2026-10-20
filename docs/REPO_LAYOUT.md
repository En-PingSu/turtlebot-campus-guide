# CS5335TurtleBot

Speech- and LLM-guided TurtleBot system on ROS 2.  
This project connects speech/web input, LLM reasoning, ROS service/function calls, and robot navigation execution.

---

## 1. System Goal

`CS5335TurtleBot` implements an embodied AI pipeline for TurtleBot-like platforms:

- Accept human commands (speech/text)
- Convert natural language to structured robot actions via LLM
- Execute actions through ROS 2 interfaces and navigation stack
- Provide operational scripts for bringup, bridging, deployment, and shutdown

---

## 2. Technical Stack

- **ROS 2** (project appears aligned with Humble-era tooling)
- **Python** (primary implementation language)
- **DDS middleware config** (CycloneDDS/FastDDS XML files present)
- **Web/UI components** for speech interaction and dashboard
- **ROS-LLM integration** under `campus_guide_bot/external/ros_llm`

---

## 3. Repository Layout (Top-Level)

```text
.
├── README.md
├── STARTUP_GUIDE.md
├── config.yaml
├── dds_bridge_mp.py
├── cyclonedds_pc.xml
├── fastdds_client.xml
├── fastdds_super_client.xml
├── dashboard/
├── speech_web_ui/
├── campus_guide_bot/
│   └── external/ros_llm/
├── activate_all.sh
├── activate_nav2.sh
├── launch_bridge.sh
├── launch_nav.sh
├── check_clock_offset.sh
├── deploy.sh
└── stop.sh
```

### Notable directories/files

- `campus_guide_bot/`: core project workspace for robot-side logic/integration
- `campus_guide_bot/external/ros_llm/`: imported/adapted ROS-LLM framework modules
- `speech_web_ui/`: speech/text-facing web frontend layer
- `dashboard/`: dashboard/monitoring layer
- `dds_bridge_mp.py`: multiprocess bridge process for runtime communication
- `config.yaml`: configuration entry point for runtime parameters
- `*_dds*.xml`: DDS transport/discovery behavior profiles
- `activate_*`, `launch_*`, `deploy.sh`, `stop.sh`: operational scripts

---

## 4. ROS-LLM Integration Details

Inside `campus_guide_bot/external/ros_llm/`:

- **`llm_model`**  
  LLM node/service orchestration (ChatGPT-like service callback flow, history handling)

- **`llm_interfaces`**  
  Custom ROS interface definitions used by LLM/robot nodes

- **`llm_robot`**  
  Robot function-call adapter pattern (map named function calls to actual robot behaviors)

- **`llm_config`**  
  User/model behavior configuration (prompting, generation params, function schema bindings)

- **`llm_bringup`**  
  Launch integration for ROS-LLM-related nodes

### Execution pattern

1. User command enters system (speech/text)
2. LLM node parses intent and selects action/function
3. Action is sent through ROS interfaces (service/topic)
4. Robot/nav subsystem executes and returns status/feedback
5. UI/dashboard reflects runtime state

---

## 5. Runtime Bringup (Recommended Sequence)

> Exact commands can vary by environment. The scripts in this repo are the source of truth.

### Step A — Environment activation

```bash
bash activate_all.sh
```

or nav-focused setup:

```bash
bash activate_nav2.sh
```

### Step B — Communication bridge

```bash
bash launch_bridge.sh
```

### Step C — Navigation stack

```bash
bash launch_nav.sh
```

### Step D — UI / interaction

Start your speech UI/dashboard components as required by your local setup.

### Step E — Shutdown

```bash
bash stop.sh
```

---

## 6. Configuration Surfaces

### 6.1 Main project config

- `config.yaml`: primary knobs for runtime behavior and integration settings

### 6.2 DDS transport settings

- `cyclonedds_pc.xml`
- `fastdds_client.xml`
- `fastdds_super_client.xml`

Use these to tune discovery and network behavior depending on single-machine vs multi-machine deployment.

### 6.3 LLM and robot behavior config

Under `campus_guide_bot/external/ros_llm/llm_config/`:
- Model prompt/behavior parameters
- Function schema definitions
- User-specific generation controls

---

## 7. Network + Time Synchronization Notes

Robotics + DDS setups are sensitive to host clock drift and network environment.

Use:

```bash
bash check_clock_offset.sh
```

to detect offset issues that may impact message timing, sync, or action validity.

---

## 8. Development and Debugging Workflow

1. Bring up stack in strict order (activate → bridge → nav → UI)
2. Verify ROS graph (nodes/services/topics visible)
3. Send a minimal command through UI
4. Check that command reaches LLM layer
5. Validate function-call mapping to robot action
6. Confirm execution feedback path to UI/dashboard

If behavior is inconsistent:
- stop all processes with `stop.sh`
- relaunch cleanly
- inspect DDS profile and network domain settings

---

## 9. Common Failure Modes

### LLM responds but robot does not move
- Function schema and robot function implementation mismatch
- Service names or namespaces inconsistent
- Navigation stack not fully active

### Navigation active but no command routing
- Bridge not running or misconfigured
- UI publishing/request path not connected to LLM service node

### Intermittent communication
- DDS discovery/profile mismatch
- Clock skew across hosts
- Mixed environment variables between terminals

---

## 10. Included Project Documentation

- `STARTUP_GUIDE.md`: environment-specific bringup instructions
- `SESSION_NOTES_*.md`: iterative progress/debug notes
- `technical_report_meeting.md`, `midterm_report.md`: project reporting artifacts

---

## 11. External Reference

Top-level README historically referenced:

- `campus_guide_bot/external/ros_llm`

That subtree contains the underlying ROS-LLM conceptual model used by this project.

---

## 12. License

Add/confirm license information for this repository (currently unspecified at top-level).# CS5335TurtleBot
Speech and LLM guided Turtlebot

Reference repository under campus_guide_bot/external/ros_LLM
