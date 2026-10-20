# Quality Reporting System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent structured logging and an automated quality report generator so that every deployment session produces a reviewable Markdown report with navigation success rates, LLM performance, localization health trends, and tool execution traces.

**Architecture:** A new `event_logger.py` module writes JSONL (one JSON object per line) files to `~/.campus_nav_logs/`. It is imported by `llm_planner_node.py` and `task_executor_node.py` with zero ROS dependency (pure Python). A standalone `gen_quality_report.py` script reads the JSONL files and produces a Markdown report. No changes to the ROS node lifecycle or topic structure.

**Tech Stack:** Python stdlib only (`json`, `logging`, `pathlib`, `datetime`). No new dependencies.

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `campus_nav_llm/campus_nav_llm/event_logger.py` | JSONL event writer — append-only, thread-safe, auto-rotating by session |
| Create | `campus_nav_llm/tests/test_event_logger.py` | Tests for event_logger |
| Modify | `campus_nav_llm/campus_nav_llm/task_executor_node.py:269-280` | Log tool execution events |
| Modify | `campus_nav_llm/campus_nav_llm/llm_planner_node.py:595-646` | Log session events (input, reply, errors) |
| Create | `gen_quality_report.py` (repo root) | Read JSONL → produce Markdown quality report |
| Create | `campus_nav_llm/tests/test_quality_report.py` | Tests for report generator |

---

### Task 1: Create event_logger module with JSONL writer

**Files:**
- Create: `campus_nav_llm/campus_nav_llm/event_logger.py`
- Create: `campus_nav_llm/tests/test_event_logger.py`

- [ ] **Step 1: Write the failing tests**

Create `campus_nav_llm/tests/test_event_logger.py`:

```python
"""Tests for JSONL event logger."""
import json
import os
import tempfile
import threading

import pytest


class TestEventLogger:
    """Test EventLogger JSONL file writing."""

    def test_log_event_creates_file(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        logger = EventLogger(log_dir=str(tmp_path))
        logger.log("tool_exec", {"tool": "speak", "status": "ok"})
        logger.close()

        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        assert "events" in files[0].name

    def test_log_event_writes_valid_jsonl(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        logger = EventLogger(log_dir=str(tmp_path))
        logger.log("tool_exec", {"tool": "navigate_to", "target": "desk_1"})
        logger.log("nav_result", {"status": "arrived", "elapsed_s": 12.5})
        logger.close()

        files = list(tmp_path.glob("*.jsonl"))
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 2

        event1 = json.loads(lines[0])
        assert event1["event"] == "tool_exec"
        assert event1["data"]["tool"] == "navigate_to"
        assert "ts" in event1
        assert "session_id" in event1

        event2 = json.loads(lines[1])
        assert event2["event"] == "nav_result"
        assert event2["data"]["elapsed_s"] == 12.5

    def test_log_is_thread_safe(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        logger = EventLogger(log_dir=str(tmp_path))

        def write_batch(prefix):
            for i in range(50):
                logger.log("test", {"i": f"{prefix}_{i}"})

        threads = [threading.Thread(target=write_batch, args=(f"t{t}",)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        logger.close()

        files = list(tmp_path.glob("*.jsonl"))
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 200
        for line in lines:
            json.loads(line)  # must be valid JSON

    def test_session_id_is_consistent(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        logger = EventLogger(log_dir=str(tmp_path))
        logger.log("a", {})
        logger.log("b", {})
        logger.close()

        files = list(tmp_path.glob("*.jsonl"))
        lines = files[0].read_text().strip().split("\n")
        id1 = json.loads(lines[0])["session_id"]
        id2 = json.loads(lines[1])["session_id"]
        assert id1 == id2
        assert len(id1) == 8  # short session id

    def test_close_flushes(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        logger = EventLogger(log_dir=str(tmp_path))
        logger.log("flush_test", {"x": 1})
        logger.close()

        files = list(tmp_path.glob("*.jsonl"))
        content = files[0].read_text()
        assert "flush_test" in content

    def test_log_after_close_does_not_crash(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        logger = EventLogger(log_dir=str(tmp_path))
        logger.close()
        logger.log("after_close", {})  # should not raise


class TestGetLogger:
    """Test module-level get_logger singleton."""

    def test_get_logger_returns_same_instance(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        # Direct instantiation (not singleton) for isolation
        a = EventLogger(log_dir=str(tmp_path))
        b = EventLogger(log_dir=str(tmp_path))
        # Different instances, different sessions
        assert a.session_id != b.session_id
        a.close()
        b.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python3 -m pytest tests/test_event_logger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'campus_nav_llm.event_logger'`

- [ ] **Step 3: Implement event_logger.py**

Create `campus_nav_llm/campus_nav_llm/event_logger.py`:

```python
"""JSONL event logger for quality reporting.

Appends structured JSON events (one per line) to a session log file.
Thread-safe, no ROS dependency, pure Python stdlib.

Usage:
    from campus_nav_llm.event_logger import EventLogger
    _evt = EventLogger()
    _evt.log("tool_exec", {"tool": "navigate_to", "target": "desk_1"})
"""
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Default log directory — outside the workspace, survives git clean
_DEFAULT_LOG_DIR = Path.home() / ".campus_nav_logs"


class EventLogger:
    """Append-only JSONL event writer.

    Each event line: {"ts": ISO8601, "session_id": str, "event": str, "data": dict}
    """

    def __init__(self, log_dir: str | None = None):
        self._dir = Path(log_dir) if log_dir else _DEFAULT_LOG_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

        self.session_id = uuid.uuid4().hex[:8]
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._path = self._dir / f"events_{ts}_{self.session_id}.jsonl"

        self._lock = threading.Lock()
        self._file = open(self._path, "a", encoding="utf-8")
        self._closed = False

    def log(self, event: str, data: dict) -> None:
        """Append one event to the JSONL file. Thread-safe."""
        if self._closed:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "session_id": self.session_id,
            "event": event,
            "data": data,
        }
        line = json.dumps(record, default=str) + "\n"
        with self._lock:
            if not self._closed:
                self._file.write(line)
                self._file.flush()

    def close(self) -> None:
        """Flush and close the log file."""
        with self._lock:
            if not self._closed:
                self._closed = True
                self._file.flush()
                self._file.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python3 -m pytest tests/test_event_logger.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Run full test suite for regressions**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python3 -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/khouryloaner/CS5335TurtleBot && git add campus_guide_bot/campus_nav_llm/campus_nav_llm/event_logger.py campus_guide_bot/campus_nav_llm/tests/test_event_logger.py
git commit -m "feat: add JSONL event logger for quality reporting

Thread-safe append-only writer. Each event is one JSON line with
timestamp, session_id, event type, and data dict. Logs to
~/.campus_nav_logs/ outside the workspace."
```

---

### Task 2: Integrate event_logger into TaskExecutorCore.execute

Hook into the tool dispatch method to log every tool execution with timing.

**Files:**
- Modify: `campus_nav_llm/campus_nav_llm/task_executor_node.py:148,269-280`

- [ ] **Step 1: Add event_logger import and instance to TaskExecutorCore.__init__**

In `task_executor_node.py`, add import at the top (after line 22):

```python
from campus_nav_llm.event_logger import EventLogger
```

In `TaskExecutorCore.__init__` (after line 187, after `self._dispatch = {...}`), add:

```python
        self._evt = EventLogger()
```

- [ ] **Step 2: Wrap execute() to log tool events with timing**

Replace `task_executor_node.py` `execute` method (lines 269-280) with:

```python
    def execute(self, tool_name: str, tool_input: dict, request_id: str = "") -> dict:
        """Execute a tool call and return the result dict."""
        handler = self._dispatch.get(tool_name)
        if not handler:
            result = {"error": f"Unknown tool: {tool_name}", "request_id": request_id}
            self._evt.log("tool_error", {"tool": tool_name, "error": result["error"], "request_id": request_id})
            return result
        t0 = time.monotonic()
        try:
            result = handler(tool_input)
            result["request_id"] = request_id
            elapsed = round(time.monotonic() - t0, 3)
            self._evt.log("tool_exec", {
                "tool": tool_name,
                "input": {k: v for k, v in (tool_input or {}).items() if not k.startswith("_")},
                "status": result.get("status", result.get("error", "ok")),
                "elapsed_s": elapsed,
                "request_id": request_id,
            })
            return result
        except Exception as e:
            elapsed = round(time.monotonic() - t0, 3)
            logger.error("Tool %s failed: %s", tool_name, e)
            self._evt.log("tool_error", {
                "tool": tool_name,
                "error": str(e),
                "elapsed_s": elapsed,
                "request_id": request_id,
            })
            return {"error": str(e), "request_id": request_id}
```

- [ ] **Step 3: Run all tests**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python3 -m pytest tests/ -v`
Expected: All tests PASS (event_logger writes are side-effect only, tests use `navigator=None`)

- [ ] **Step 4: Commit**

```bash
cd /home/khouryloaner/CS5335TurtleBot && git add campus_guide_bot/campus_nav_llm/campus_nav_llm/task_executor_node.py
git commit -m "feat: log tool executions to JSONL with timing

Every tool call writes event type, input (excluding internal keys),
status, and elapsed_s to the session JSONL file."
```

---

### Task 3: Integrate event_logger into LLMPlannerNode._handle_input

Log user inputs, LLM replies, errors, and session lifecycle.

**Files:**
- Modify: `campus_nav_llm/campus_nav_llm/llm_planner_node.py:595-646`

- [ ] **Step 1: Add event_logger to LLMPlannerNode**

In `llm_planner_node.py`, the `LLMPlannerNode` class is defined inside `create_ros_node()`. At the end of `__init__` (after line 507, `self.get_logger().info("LLM Planner ready...")`), add:

```python
            from campus_nav_llm.event_logger import EventLogger
            self._evt = self.executor_core._evt  # share the same session log
            self._evt.log("session_start", {
                "node": "llm_planner",
                "namespace": ns,
            })
```

- [ ] **Step 2: Add logging to _handle_input**

In `_handle_input` (starting at line 595), add event logging. Replace the method body:

```python
        def _handle_input(self, user_input):
            """Process user input with guaranteed reply.

            Ref: ROSA (NASA JPL) — every tool returns a string, never None.
                 OpenAI docs — return errors as tool results, not exceptions.
                 LangChain — handle_tool_error=True catches all tool failures.
            Every code path MUST publish to /robot_reply.
            """
            reply = None
            t0 = __import__("time").monotonic()
            path_type = "unknown"
            try:
                self.get_logger().info("Processing: %s", user_input)
                self._cancel_requested = False
                self._evt.log("user_input", {"text": user_input})

                # Try fast path first (simple commands skip LLM)
                fast = self.planner.try_fast_path(user_input)
                if fast:
                    tool_name, tool_input = fast
                    path_type = "fast"
                    self.get_logger().info(
                        "Fast path: %s(%s)", tool_name, tool_input
                    )
                    result = self._local_tool_executor(tool_name, tool_input)
                    reply = self._format_fast_reply(tool_name, result)

                    # Update conversation history so LLM has context of fast-path commands
                    with self.planner._lock:
                        self.planner.conversation_history.append(
                            {"role": "user", "content": user_input}
                        )
                        self.planner.conversation_history.append(
                            {"role": "assistant", "content": reply}
                        )
                        self.planner._trim_history()
                else:
                    # Full LLM tool loop
                    path_type = "llm"
                    reply = self.planner.run_tool_loop(
                        user_input, self._local_tool_executor,
                        cancel_check=lambda: self._cancel_requested,
                    )
            except Exception as e:
                # Guaranteed error reply — never swallow exceptions silently
                path_type = "error"
                reply = f"Sorry, something went wrong: {e}"
                self.get_logger().error("_handle_input error: %s", e)
                self._evt.log("handle_error", {"input": user_input, "error": str(e)})
            finally:
                # ALWAYS publish a reply — this is the guaranteed-return pattern
                if reply is None:
                    reply = "Sorry, I couldn't process that command."
                self.pub_reply.publish(String(data=reply))
                self.get_logger().info("Reply: %s", reply[:100])
                elapsed = round(__import__("time").monotonic() - t0, 3)
                self._evt.log("interaction", {
                    "input": user_input,
                    "reply": reply[:200],
                    "path": path_type,
                    "elapsed_s": elapsed,
                })
                with self._processing_lock:
                    self._processing = False
                    self._cancel_requested = False
```

- [ ] **Step 3: Run all tests**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python3 -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd /home/khouryloaner/CS5335TurtleBot && git add campus_guide_bot/campus_nav_llm/campus_nav_llm/llm_planner_node.py
git commit -m "feat: log user interactions and session events to JSONL

Logs user_input, interaction (with path type, elapsed), handle_error,
and session_start events. Shares EventLogger instance with TaskExecutorCore."
```

---

### Task 4: Create quality report generator

A standalone script that reads JSONL event files and produces a Markdown quality report.

**Files:**
- Create: `gen_quality_report.py` (repo root)
- Create: `campus_nav_llm/tests/test_quality_report.py`

- [ ] **Step 1: Write failing tests**

Create `campus_nav_llm/tests/test_quality_report.py`:

```python
"""Tests for quality report generator."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

# gen_quality_report.py is at repo root, add to path
REPO_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _write_events(tmp_path, events):
    """Helper: write events to a JSONL file."""
    f = tmp_path / "events_test.jsonl"
    lines = [json.dumps(e) for e in events]
    f.write_text("\n".join(lines) + "\n")
    return f


class TestReportGeneration:

    def test_empty_log_produces_report(self, tmp_path):
        from gen_quality_report import generate_report
        _write_events(tmp_path, [])
        report = generate_report(str(tmp_path))
        assert "# Quality Report" in report
        assert "No events" in report

    def test_tool_exec_summary(self, tmp_path):
        from gen_quality_report import generate_report
        events = [
            {"ts": "2026-04-07T10:00:00.000Z", "session_id": "abc", "event": "tool_exec",
             "data": {"tool": "navigate_to", "status": "arrived", "elapsed_s": 8.5, "request_id": "r1"}},
            {"ts": "2026-04-07T10:01:00.000Z", "session_id": "abc", "event": "tool_exec",
             "data": {"tool": "navigate_to", "status": "arrived", "elapsed_s": 12.0, "request_id": "r2"}},
            {"ts": "2026-04-07T10:02:00.000Z", "session_id": "abc", "event": "tool_exec",
             "data": {"tool": "speak", "status": "spoken", "elapsed_s": 0.01, "request_id": "r3"}},
        ]
        _write_events(tmp_path, events)
        report = generate_report(str(tmp_path))
        assert "navigate_to" in report
        assert "2/2" in report or "100%" in report  # success rate
        assert "speak" in report

    def test_interaction_summary(self, tmp_path):
        from gen_quality_report import generate_report
        events = [
            {"ts": "2026-04-07T10:00:00.000Z", "session_id": "abc", "event": "interaction",
             "data": {"input": "go to desk", "reply": "Arrived at desk_1.", "path": "fast", "elapsed_s": 9.0}},
            {"ts": "2026-04-07T10:01:00.000Z", "session_id": "abc", "event": "interaction",
             "data": {"input": "where am I", "reply": "You are at desk_1.", "path": "llm", "elapsed_s": 2.5}},
        ]
        _write_events(tmp_path, events)
        report = generate_report(str(tmp_path))
        assert "fast" in report.lower() or "Fast" in report
        assert "llm" in report.lower() or "LLM" in report

    def test_error_section(self, tmp_path):
        from gen_quality_report import generate_report
        events = [
            {"ts": "2026-04-07T10:00:00.000Z", "session_id": "abc", "event": "tool_error",
             "data": {"tool": "navigate_to", "error": "Localization uncertain", "elapsed_s": 0.1, "request_id": "r1"}},
            {"ts": "2026-04-07T10:01:00.000Z", "session_id": "abc", "event": "handle_error",
             "data": {"input": "fly", "error": "Unknown tool"}},
        ]
        _write_events(tmp_path, events)
        report = generate_report(str(tmp_path))
        assert "Error" in report or "error" in report
        assert "Localization uncertain" in report

    def test_navigation_stats(self, tmp_path):
        from gen_quality_report import generate_report
        events = [
            {"ts": "2026-04-07T10:00:00.000Z", "session_id": "abc", "event": "tool_exec",
             "data": {"tool": "navigate_to", "status": "arrived", "elapsed_s": 15.0,
                      "input": {"location_name": "desk_1"}, "request_id": "r1"}},
            {"ts": "2026-04-07T10:02:00.000Z", "session_id": "abc", "event": "tool_exec",
             "data": {"tool": "navigate_to", "status": "rejected", "elapsed_s": 0.5,
                      "input": {"location_name": "nowhere"}, "request_id": "r2"}},
        ]
        _write_events(tmp_path, events)
        report = generate_report(str(tmp_path))
        assert "1" in report  # 1 success
        assert "desk_1" in report or "arrived" in report

    def test_multiple_sessions(self, tmp_path):
        from gen_quality_report import generate_report
        f1 = tmp_path / "events_s1.jsonl"
        f2 = tmp_path / "events_s2.jsonl"
        f1.write_text(json.dumps({"ts": "2026-04-07T10:00:00.000Z", "session_id": "s1",
                                   "event": "tool_exec", "data": {"tool": "speak", "status": "ok", "elapsed_s": 0.01, "request_id": "r1"}}) + "\n")
        f2.write_text(json.dumps({"ts": "2026-04-07T11:00:00.000Z", "session_id": "s2",
                                   "event": "tool_exec", "data": {"tool": "speak", "status": "ok", "elapsed_s": 0.02, "request_id": "r2"}}) + "\n")
        report = generate_report(str(tmp_path))
        assert "s1" in report or "s2" in report or "2 session" in report.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python3 -m pytest tests/test_quality_report.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement gen_quality_report.py**

Create `/home/khouryloaner/CS5335TurtleBot/gen_quality_report.py`:

```python
#!/usr/bin/env python3
"""Generate a Markdown quality report from JSONL event logs.

Reads all *.jsonl files from ~/.campus_nav_logs/ (or specified directory)
and produces a summary report with:
  - Session overview
  - Tool execution stats (count, success rate, avg time)
  - Navigation performance (success/fail, avg time per location)
  - Interaction summary (fast path vs LLM, avg response time)
  - Error log

Usage:
    python3 gen_quality_report.py                    # default log dir
    python3 gen_quality_report.py /path/to/logs      # custom log dir
    python3 gen_quality_report.py --latest            # most recent session only
"""
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_DEFAULT_LOG_DIR = Path.home() / ".campus_nav_logs"


def _load_events(log_dir: str, latest_only: bool = False) -> list[dict]:
    """Load all events from JSONL files in log_dir."""
    p = Path(log_dir)
    if not p.exists():
        return []
    files = sorted(p.glob("*.jsonl"))
    if latest_only and files:
        files = [files[-1]]
    events = []
    for f in files:
        for line in f.read_text().strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def generate_report(log_dir: str, latest_only: bool = False) -> str:
    """Generate Markdown quality report from JSONL events."""
    events = _load_events(log_dir, latest_only)
    lines = ["# Quality Report", ""]

    if not events:
        lines.append("**No events found.** Run the robot to generate data.")
        return "\n".join(lines)

    # --- Session overview ---
    sessions = defaultdict(list)
    for e in events:
        sessions[e.get("session_id", "unknown")].append(e)

    lines.append(f"**Sessions:** {len(sessions)}  ")
    for sid, sevts in sessions.items():
        ts_list = [e["ts"] for e in sevts if "ts" in e]
        t0 = min(ts_list) if ts_list else "?"
        t1 = max(ts_list) if ts_list else "?"
        lines.append(f"- `{sid}`: {len(sevts)} events ({t0[:19]} — {t1[:19]})")
    lines.append("")

    # --- Tool execution stats ---
    tool_execs = [e for e in events if e["event"] == "tool_exec"]
    tool_errors = [e for e in events if e["event"] == "tool_error"]

    lines.append("## Tool Execution Summary")
    lines.append("")

    if tool_execs or tool_errors:
        # Group by tool name
        by_tool = defaultdict(lambda: {"success": 0, "fail": 0, "times": []})
        for e in tool_execs:
            d = e["data"]
            tool = d.get("tool", "unknown")
            status = d.get("status", "")
            elapsed = d.get("elapsed_s", 0)
            by_tool[tool]["times"].append(elapsed)
            if status in ("arrived", "spoken", "ok", "success", "cleared", "cancelled", "no_navigation_active", "partial"):
                by_tool[tool]["success"] += 1
            else:
                by_tool[tool]["fail"] += 1

        for e in tool_errors:
            d = e["data"]
            tool = d.get("tool", "unknown")
            by_tool[tool]["fail"] += 1
            elapsed = d.get("elapsed_s", 0)
            if elapsed:
                by_tool[tool]["times"].append(elapsed)

        lines.append("| Tool | Calls | Success | Fail | Rate | Avg Time |")
        lines.append("|------|-------|---------|------|------|----------|")
        for tool, stats in sorted(by_tool.items()):
            total = stats["success"] + stats["fail"]
            rate = f"{stats['success']}/{total}" if total else "—"
            pct = f" ({100 * stats['success'] / total:.0f}%)" if total else ""
            avg_t = f"{sum(stats['times']) / len(stats['times']):.2f}s" if stats["times"] else "—"
            lines.append(f"| {tool} | {total} | {stats['success']} | {stats['fail']} | {rate}{pct} | {avg_t} |")
        lines.append("")
    else:
        lines.append("No tool executions recorded.")
        lines.append("")

    # --- Navigation performance ---
    nav_execs = [e for e in tool_execs if e["data"].get("tool") == "navigate_to"]
    if nav_execs:
        lines.append("## Navigation Performance")
        lines.append("")
        by_target = defaultdict(lambda: {"arrived": 0, "failed": 0, "times": []})
        for e in nav_execs:
            d = e["data"]
            target = d.get("input", {}).get("location_name", "unknown") if isinstance(d.get("input"), dict) else "unknown"
            elapsed = d.get("elapsed_s", 0)
            if d.get("status") == "arrived":
                by_target[target]["arrived"] += 1
                by_target[target]["times"].append(elapsed)
            else:
                by_target[target]["failed"] += 1

        lines.append("| Target | Arrived | Failed | Avg Time |")
        lines.append("|--------|---------|--------|----------|")
        for target, stats in sorted(by_target.items()):
            avg_t = f"{sum(stats['times']) / len(stats['times']):.1f}s" if stats["times"] else "—"
            lines.append(f"| {target} | {stats['arrived']} | {stats['failed']} | {avg_t} |")
        lines.append("")

    # --- Interaction summary ---
    interactions = [e for e in events if e["event"] == "interaction"]
    if interactions:
        lines.append("## Interaction Summary")
        lines.append("")
        by_path = defaultdict(lambda: {"count": 0, "times": []})
        for e in interactions:
            d = e["data"]
            path = d.get("path", "unknown")
            by_path[path]["count"] += 1
            by_path[path]["times"].append(d.get("elapsed_s", 0))

        total_i = sum(v["count"] for v in by_path.values())
        lines.append(f"**Total interactions:** {total_i}  ")
        lines.append("")
        lines.append("| Path | Count | Avg Response Time |")
        lines.append("|------|-------|-------------------|")
        for path, stats in sorted(by_path.items()):
            avg_t = f"{sum(stats['times']) / len(stats['times']):.2f}s" if stats["times"] else "—"
            lines.append(f"| {path} | {stats['count']} | {avg_t} |")
        lines.append("")

    # --- Errors ---
    all_errors = tool_errors + [e for e in events if e["event"] == "handle_error"]
    if all_errors:
        lines.append("## Errors")
        lines.append("")
        lines.append("| Time | Type | Detail |")
        lines.append("|------|------|--------|")
        for e in all_errors:
            ts = e.get("ts", "?")[:19]
            d = e["data"]
            etype = e["event"]
            detail = d.get("error", "")
            tool = d.get("tool", d.get("input", ""))
            lines.append(f"| {ts} | {etype} | **{tool}**: {detail} |")
        lines.append("")

    # --- Footer ---
    lines.append("---")
    lines.append(f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} from `{log_dir}`*")

    return "\n".join(lines)


def main():
    latest_only = "--latest" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    log_dir = args[0] if args else str(_DEFAULT_LOG_DIR)

    report = generate_report(log_dir, latest_only=latest_only)
    print(report)

    # Also write to file
    out = Path(log_dir) / "quality_report.md"
    out.write_text(report)
    print(f"\nReport saved to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python3 -m pytest tests/test_quality_report.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Run full suite**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python3 -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/khouryloaner/CS5335TurtleBot && git add gen_quality_report.py campus_guide_bot/campus_nav_llm/tests/test_quality_report.py
git commit -m "feat: add quality report generator from JSONL event logs

Reads *.jsonl from ~/.campus_nav_logs/, produces Markdown report with:
- Session overview
- Tool execution stats (count, success rate, avg time)
- Navigation performance by target location
- Interaction summary (fast path vs LLM)
- Error log with timestamps"
```

---

### Task 5: Add pytest JUnit XML output to test commands

**Files:**
- Modify: `campus_nav_llm/setup.cfg` or add `pytest.ini`

- [ ] **Step 1: Check if pytest config exists**

Run: `ls /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm/setup.cfg /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm/pytest.ini /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm/pyproject.toml 2>/dev/null`

- [ ] **Step 2: Create or update pytest config with JUnit XML**

Create `campus_nav_llm/pytest.ini`:

```ini
[pytest]
addopts = --junitxml=test-results.xml -v
testpaths = tests
```

- [ ] **Step 3: Run tests and verify XML output**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python3 -m pytest tests/ -v`
Then verify: `ls -la /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm/test-results.xml`
Expected: XML file exists with test results

- [ ] **Step 4: Add test-results.xml to .gitignore**

Append to `/home/khouryloaner/CS5335TurtleBot/.gitignore`:

```
test-results.xml
```

- [ ] **Step 5: Commit**

```bash
cd /home/khouryloaner/CS5335TurtleBot && git add campus_guide_bot/campus_nav_llm/pytest.ini .gitignore
git commit -m "feat: add pytest JUnit XML output for test reporting

Pytest now generates test-results.xml automatically. Added to .gitignore."
```

---

## Self-Review

**Spec coverage:**
- P0: Python logging FileHandler → replaced with JSONL EventLogger (simpler, more useful for reports) ✓
- P0: /system_status and /tool_result write to JSONL → tool_exec events in execute() ✓
- P1: Navigation session summary → gen_quality_report.py Navigation Performance table ✓
- P1: pytest JUnit XML → Task 5 ✓
- P2: Aggregation script → gen_quality_report.py ✓
- P2: deploy.sh timing → deferred (lower priority, deploy.sh already has step markers)

**Placeholder scan:** No TBDs, TODOs, or vague steps. All code complete.

**Type consistency:** `EventLogger.log(event, data)` signature used consistently everywhere. `generate_report(log_dir)` matches all test calls. `tool_exec`, `tool_error`, `interaction`, `handle_error`, `session_start` event names are consistent between writer (Tasks 2-3) and reader (Task 4).
