"""Generate technical report as a Word document for instructor meeting."""
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

for section in doc.sections:
    section.top_margin = Inches(0.8)
    section.bottom_margin = Inches(0.8)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)

style = doc.styles["Normal"]
style.font.name = "Times New Roman"
style.font.size = Pt(11)
style.paragraph_format.space_after = Pt(4)
style.paragraph_format.line_spacing = 1.15

# Title
title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run("Technical Report: Architecture & Design Decisions")
run.bold = True
run.font.size = Pt(15)

subtitle = doc.add_paragraph()
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = subtitle.add_run("CS5335 TurtleBot LLM Navigation \u2014 Instructor Meeting 2026-03-19")
run.font.size = Pt(11)
run.italic = True

doc.add_paragraph()

# ── 1. Architecture ──
doc.add_heading("1. Current System Architecture", level=1)

doc.add_paragraph(
    "The system has three layers: a cloud-hosted LLM (Claude via OpenRouter) "
    "acts as the planner, a Task Executor node on the laptop dispatches tool "
    "calls to Nav2, and the TurtleBot4 hardware (RPi4 + Create3) provides "
    "sensor data over FastDDS Discovery Server."
)

doc.add_paragraph(
    "User input (text, voice, or ROS topic) goes to the LLM Planner, which "
    "either fast-paths simple commands via regex or runs a full tool call loop "
    "with the LLM. The Task Executor receives tool commands over the /tool_cmd "
    "topic and executes them: navigate_to, get_robot_position, speak, "
    "cancel_navigation, clear_costmap, get_navigation_status, and relocalize "
    "(7 tools total). It also monitors AMCL covariance for localization health "
    "and publishes system status at 1 Hz."
)

doc.add_paragraph(
    "Nav2 (AMCL, planner, controller, costmaps, bt_navigator) runs on the "
    "laptop and communicates with the robot\u2019s sensors through FastDDS "
    "Discovery Server. All custom nodes have respawn enabled."
)

p = doc.add_paragraph()
run = p.add_run("Key numbers: ")
run.bold = True
p.add_run("99 unit/integration tests passing, 7 LLM tools, 6 semantic map locations, 5 lab sessions.")

# ── 2. FastDDS ──
doc.add_heading("2. FastDDS Discovery Server + Manual Lifecycle", level=1)

p = doc.add_paragraph()
run = p.add_run("Problem: ")
run.bold = True
p.add_run(
    "Nav2 lifecycle_manager needs DDS service discovery to transition nodes "
    "(configure \u2192 activate). FastDDS Discovery Server v2 filters out "
    "lifecycle service endpoints entirely. This is a confirmed upstream bug "
    "(Nav2 #3560, rmw_fastrtps #499)."
)

p = doc.add_paragraph()
run = p.add_run("What we tried: ")
run.bold = True
p.add_run(
    "SUPER_CLIENT XML profiles (endpoints still filtered), custom "
    "lifecycle_activator.py node (same bug), manual ros2 lifecycle set "
    "from CLI (works but DDS timeouts make it unreliable), a two-process "
    "DDS bridge (adds complexity without reliability gain), and a full "
    "CycloneDDS switch (works but lab default is FastDDS)."
)

p = doc.add_paragraph()
run = p.add_run("Current solution: ")
run.bold = True
p.add_run(
    "(1) Keep lifecycle_manager with bond_timeout: 0.0 so it won\u2019t kill "
    "nodes on bond failure. (2) deploy.sh manually activates each node with "
    "retry + exponential backoff (3 attempts, delay 5s \u2192 10s \u2192 20s). "
    "(3) Action server availability (navigate_to_pose) as the definitive "
    "readiness gate. (4) task_executor waits on nav_to_pose_client."
    "wait_for_server() instead of waitUntilNav2Active()."
)

doc.add_paragraph(
    "References: Nav2 navigation_launch.py (use_respawn + bond_timeout), "
    "KubeROS nav-slam (action server health check). All surveyed open-source "
    "Nav2 projects use Simple Discovery or CycloneDDS."
)

p = doc.add_paragraph()
run = p.add_run("Question: ")
run.bold = True
run.italic = True
p.add_run(
    "Given the lifecycle bug, is our manual activation approach acceptable "
    "for the final demo? Would running Nav2 on the RPi be preferable?"
)

# ── 3. LLM ──
doc.add_heading("3. LLM Tool Call Loop (not ROSA/LangChain)", level=1)

p = doc.add_paragraph()
run = p.add_run("Our approach: ")
run.bold = True
p.add_run(
    "Hand-written OpenAI-compatible tool call loop (~100 lines). The LLM "
    "receives user input + tool definitions, returns tool calls, we execute "
    "them, feed results back, and loop until done. A regex fast path skips "
    "the LLM entirely for simple commands like \u201cgo to table 1.\u201d Retry with "
    "exponential backoff (1s \u2192 2s \u2192 4s, 3 attempts) for transient API errors."
)

p = doc.add_paragraph()
run = p.add_run("Why not ROSA? ")
run.bold = True
p.add_run(
    "NASA JPL\u2019s ROSA uses LangChain ReAct agents with @tool decorators. "
    "Functionally equivalent to our approach, but adds LangChain as a heavy "
    "dependency (40+ transitive packages). Our loop is small, the team fully "
    "understands it, and the fast path (regex \u2192 direct execution without API "
    "call) is not available in ROSA."
)

doc.add_paragraph(
    "References: NASA JPL ROSA (github.com/nasa-jpl/rosa), ROS-LLM/Auromix "
    "(code generation + regex parsing), Mike Likes Robots (ROSA + Claude + Gazebo)."
)

p = doc.add_paragraph()
run = p.add_run("Question: ")
run.bold = True
run.italic = True
p.add_run(
    "Is the hand-written tool loop acceptable, or would using ROSA/LangChain "
    "be preferred? We can migrate if needed."
)

# ── 4. Clock ──
doc.add_heading("4. Clock Sync via Chrony NTP Hierarchy", level=1)

p = doc.add_paragraph()
run = p.add_run("Problem: ")
run.bold = True
p.add_run(
    "Three independent clocks (laptop, RPi4, Create3). The RPi has no "
    "battery-backed RTC, so its clock resets on every reboot. The Create3 has "
    "its own internal NTP that drifts 5\u201312 seconds from the RPi."
)

p = doc.add_paragraph()
run = p.add_run("Previous approach: ")
run.bold = True
p.add_run(
    "One-shot ssh date -s per session. No persistent sync. We set "
    "transform_tolerance to 2\u20135 seconds to compensate (the official default "
    "is 0.2)."
)

p = doc.add_paragraph()
run = p.add_run("Current approach: ")
run.bold = True
p.add_run(
    "Chrony NTP hierarchy. The laptop serves as stratum 10, the RPi syncs "
    "from the laptop (stratum 11) and also serves time to the Create3. "
    "deploy.sh auto-installs and configures chrony on the RPi, uses "
    "makestep 1 3 (jump clock if offset >1s during first 3 updates), and "
    "verifies drift after sync. Falls back to date -s if chrony fails."
)

doc.add_paragraph(
    "References: Create3 official NTP docs (iroboteducation.github.io), "
    "turtlebot4_setup chrony.conf (github.com/turtlebot/turtlebot4_setup), "
    "Clearpath Robotics NTP guide, turtlebot4_robot#8 and turtlebot4#404."
)

p = doc.add_paragraph()
run = p.add_run("Question: ")
run.bold = True
run.italic = True
p.add_run(
    "Once chrony is stable, we plan to reduce transform_tolerance back toward "
    "0.2s. What tolerance is recommended for the lab? Does the Create3 already "
    "have NTP configured?"
)

# ── 5. AMCL ──
doc.add_heading("5. AMCL Localization Recovery", level=1)

p = doc.add_paragraph()
run = p.add_run("Problem: ")
run.bold = True
p.add_run(
    "If the robot is moved between sessions or localization degrades during "
    "operation, AMCL particles converge to the wrong location. Navigation "
    "silently fails with a 120-second timeout."
)

p = doc.add_paragraph()
run = p.add_run("Current approach: ")
run.bold = True
p.add_run(
    "(1) Detection: monitor AMCL covariance (cov[0] + cov[7] from amcl_pose, "
    "threshold 1.0). (2) Pre-validation: reject navigation goals with an "
    "actionable error if localization is unhealthy. (3) Recovery: a new "
    "relocalize tool that calls Nav2\u2019s reinitialize_global_localization "
    "service (spreads particles across free space), then spins the robot in "
    "place for ~14 seconds to collect laser data, and checks if covariance "
    "improved. (4) /system_status topic at 1 Hz with localization health."
)

doc.add_paragraph(
    "References: Nav2 AMCL covariance (amcl_node.cpp), Nav2 "
    "reinitialize_global_localization service + BT node, CMU Q Robotics Lab "
    "covariance threshold (~0.5\u20130.65), Nav2 AutoLocalization BT pattern, "
    "ROS 2 diagnostics framework, TurtleBot4 diagnostics package."
)

p = doc.add_paragraph()
run = p.add_run("Question: ")
run.bold = True
run.italic = True
p.add_run(
    "Is the covariance threshold of 1.0 (combined xx+yy) reasonable for our "
    "classroom? Should we check yaw covariance too? Should we have a manual "
    "fallback for the demo?"
)

# ── 6. Summary table ──
doc.add_heading("6. Reliability Improvements Summary", level=1)

table = doc.add_table(rows=10, cols=4, style="Light Grid Accent 1")
headers = ["Improvement", "Before", "After", "Reference"]
for i, h in enumerate(headers):
    table.rows[0].cells[i].text = h

rows_data = [
    ["Node crash recovery", "Silent failure", "respawn=True, delay 2\u20135s", "Nav2 PR #2910"],
    ["Lifecycle activation", "Single blind attempt", "3 retries, exp. backoff", "KubeROS pattern"],
    ["LLM API failure", "Immediate error", "3 retries, 1\u21922\u21924s + jitter", "OpenAI SDK pattern"],
    ["Thread safety", "Unbounded threads", "ThreadPoolExecutor(2)", "Python stdlib"],
    ["Clock sync", "date -s one-shot", "Chrony NTP hierarchy", "TurtleBot4 setup"],
    ["Localization loss", "120s timeout", "Covariance + relocalize", "Nav2 global_loc"],
    ["System health", "No visibility", "/system_status 1 Hz", "ROS 2 diagnostics"],
    ["Goal validation", "Send and hope", "Map bounds + loc check", "ROSA validation"],
    ["Tool result timeout", "120s (= nav timeout)", "135s (+15s DDS buffer)", "Timeout analysis"],
]
for r, data in enumerate(rows_data):
    for c, val in enumerate(data):
        table.rows[r + 1].cells[c].text = val

# ── 7. Limitations ──
doc.add_heading("7. Known Limitations & Open Questions", level=1)

doc.add_heading("Architecture", level=2)
doc.add_paragraph(
    "Nav2 runs on the laptop while sensors are on the RPi. All sensor data "
    "traverses Discovery Server. Network hiccups break navigation. Moving "
    "Nav2 to the RPi would reduce this dependency but may exceed its compute.",
    style="List Bullet"
)
doc.add_paragraph(
    "The tool_cmd/tool_result communication uses pub/sub topics to simulate "
    "request-response. This works in practice but is not guaranteed delivery. "
    "ROS 2 Services would be more correct but would require refactoring the "
    "test suite (99 tests).",
    style="List Bullet"
)

doc.add_heading("Practical", level=2)
doc.add_paragraph(
    "The ASUS_98 router\u2019s ethernet does not bridge to WiFi. We need WiFi "
    "for robot communication plus a second connection (phone hotspot) for "
    "LLM API access.",
    style="List Bullet"
)
doc.add_paragraph(
    "Some Create3 configuration changes require a physical power cycle, "
    "which is difficult mid-session.",
    style="List Bullet"
)

doc.add_heading("For discussion", level=2)
doc.add_paragraph("What is the expected demo format? Pre-recorded + live? How many trials?", style="List Bullet")
doc.add_paragraph("Should we prioritize Tier 1 (single nav) reliability or full LLM multi-step?", style="List Bullet")
doc.add_paragraph("Is there a preferred map or starting location for the demo?", style="List Bullet")

# ── 8. File map ──
doc.add_heading("8. File Map", level=1)

files = [
    ("deploy.sh", "Deployment orchestrator (clock + build + launch + activate)"),
    ("navigation_mode.launch.py", "Main launch file (Nav2 + LLM nodes, respawn)"),
    ("nav2_combined_params.yaml", "Nav2 parameters (AMCL, costmap, planner, controller)"),
    ("semantic_map.json", "6 named locations with aliases"),
    ("llm_planner_node.py", "LLM tool call loop + fast path + retry"),
    ("task_executor_node.py", "Tool execution + AMCL monitoring + relocalization"),
    ("odom_tf_publisher.py", "Odometry \u2192 TF bridge"),
    ("location_resolver.py", "Semantic map lookup + alias resolution"),
    ("tests/", "99 tests (location, tools, LLM, integration)"),
]

table2 = doc.add_table(rows=len(files) + 1, cols=2, style="Light Grid Accent 1")
table2.rows[0].cells[0].text = "File"
table2.rows[0].cells[1].text = "Purpose"
for i, (f, desc) in enumerate(files):
    table2.rows[i + 1].cells[0].text = f
    table2.rows[i + 1].cells[1].text = desc

output = r"C:\Users\chntw\Documents\robotic\final\v3\CS5335TurtleBot\Technical_Report_Meeting.docx"
doc.save(output)
print(f"Saved to {output}")
