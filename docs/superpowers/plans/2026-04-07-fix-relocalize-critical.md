# Fix Critical Relocalization Issues — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the 14-second ROS executor blocking in `_do_relocalize` and consolidate the duplicate implementations into a single shared method with cancellation support.

**Architecture:** Extract relocalization into a single `_do_relocalize` method on `TaskExecutorNode` / `LLMPlannerNode` that uses a ROS2 timer for cmd_vel publishing (following Nav2's `TimedBehavior` pattern) instead of a blocking `time.sleep` loop. The timer runs on the ROS executor thread (interleaved with AMCL callbacks), while the `ThreadPoolExecutor` worker waits on a `threading.Event`. Cancellation is supported via the existing `_cancel_requested` flag.

**Tech Stack:** ROS2 Humble (rclpy), Python 3.10, threading.Event, rclpy timers

**Reference:** Nav2 `nav2_behaviors/plugins/spin.cpp` uses `onRun()` + `onCycleUpdate()` state machine to keep the executor free. We adapt this to Python using `create_timer()` + `threading.Event`.

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `campus_nav_llm/task_executor_node.py:40-43` | Add `_RELOC_TICK_PERIOD` constant |
| Modify | `campus_nav_llm/task_executor_node.py:344-357` | Add `cancel_check` param to `_relocalize` |
| Modify | `campus_nav_llm/task_executor_node.py:502-545` | Replace blocking `_do_relocalize` with timer-based |
| Modify | `campus_nav_llm/llm_planner_node.py:479-487` | Wire cancel_check into relocalize callback |
| Modify | `campus_nav_llm/llm_planner_node.py:528-566` | **Delete** duplicate `_do_relocalize`, reuse TaskExecutorNode's |
| Modify | `campus_nav_llm/llm_planner_node.py:589-623` | Pass cancel_check through `_local_tool_executor` |
| Create | `campus_nav_llm/tests/test_relocalize.py` | Tests for relocalization logic |

---

### Task 1: Add tests for relocalization callback pattern

**Files:**
- Create: `campus_nav_llm/tests/test_relocalize.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for relocalization — timer-based, non-blocking, cancellable."""
import threading
import time
import pytest

from campus_nav_llm.task_executor_node import TaskExecutorCore


@pytest.fixture
def executor(sample_semantic_map):
    return TaskExecutorCore(sample_semantic_map, navigator=None)


class TestRelocalize:
    """Test the relocalize tool dispatch."""

    def test_relocalize_no_callback(self, executor):
        """Without ROS context, relocalize returns error."""
        result = executor.execute("relocalize", {})
        assert result["status"] == "error"
        assert "not available" in result["error"]

    def test_relocalize_with_callback(self, executor):
        """With a callback set, relocalize delegates to it."""
        executor._relocalize_callback = lambda **kw: {"status": "success", "localization": {"healthy": True}}
        result = executor.execute("relocalize", {})
        assert result["status"] == "success"

    def test_relocalize_callback_exception(self, executor):
        """Exception in callback is caught and returned as error."""
        def bad_callback(**kw):
            raise RuntimeError("service down")
        executor._relocalize_callback = bad_callback
        result = executor.execute("relocalize", {})
        assert result["status"] == "error"
        assert "service down" in result["error"]

    def test_relocalize_cancel_check_passed(self, executor):
        """cancel_check kwarg is forwarded to the callback."""
        received = {}
        def capture_callback(**kwargs):
            received.update(kwargs)
            return {"status": "success", "localization": {"healthy": True}}
        executor._relocalize_callback = capture_callback
        cancel_fn = lambda: False
        result = executor._relocalize({"_cancel_check": cancel_fn})
        assert "cancel_check" in received
        assert received["cancel_check"] is cancel_fn
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python -m pytest tests/test_relocalize.py -v`
Expected: First 3 tests PASS (existing callback pattern works), last test FAILS (cancel_check not forwarded yet)

- [ ] **Step 3: Commit**

```bash
git add campus_guide_bot/campus_nav_llm/tests/test_relocalize.py
git commit -m "test: add relocalization callback tests with cancel_check forwarding"
```

---

### Task 2: Add cancel_check support to TaskExecutorCore._relocalize

**Files:**
- Modify: `campus_nav_llm/task_executor_node.py:344-357`

- [ ] **Step 1: Update `_relocalize` to forward cancel_check**

Replace `task_executor_node.py` lines 344-357 with:

```python
    def _relocalize(self, inp: dict) -> dict:
        """Trigger global relocalization: spread particles + spin to collect data.

        Ref: Nav2 reinitialize_global_localization service;
        Nav2 AutoLocalization BT pattern (spread particles → spin → backup → spin).

        The optional _cancel_check key in inp is forwarded to the callback
        so the spin phase can be interrupted by the user.
        """
        if self._relocalize_callback is None:
            return {"status": "error", "error": "Relocalization not available (no ROS context)"}

        try:
            kwargs = {}
            if "_cancel_check" in inp:
                kwargs["cancel_check"] = inp["_cancel_check"]
            result = self._relocalize_callback(**kwargs)
            return result
        except Exception as e:
            return {"status": "error", "error": str(e)}
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python -m pytest tests/test_relocalize.py -v`
Expected: All 4 tests PASS

- [ ] **Step 3: Commit**

```bash
git add campus_guide_bot/campus_nav_llm/campus_nav_llm/task_executor_node.py
git commit -m "feat: forward cancel_check to relocalize callback for cancellation support"
```

---

### Task 3: Replace blocking _do_relocalize in TaskExecutorNode with timer-based approach

This is the core fix. We replace the `time.sleep(0.1)` loop with a `create_timer()` that publishes cmd_vel on the ROS executor thread, while the ThreadPoolExecutor worker waits on `threading.Event`.

**Files:**
- Modify: `campus_nav_llm/task_executor_node.py:40-43` (add constant)
- Modify: `campus_nav_llm/task_executor_node.py:446-453` (wire callback with cancel_check)
- Modify: `campus_nav_llm/task_executor_node.py:502-545` (replace _do_relocalize)

- [ ] **Step 1: Add timer tick constant**

After line 43 in `task_executor_node.py`, add:

```python
_RELOC_TICK_PERIOD = 0.1  # seconds — cmd_vel publish rate during spin (10 Hz)
```

- [ ] **Step 2: Replace the blocking _do_relocalize in TaskExecutorNode**

Replace the `_do_relocalize` method (lines 502-545 inside `create_ros_node`) with the timer-based version:

```python
        def _do_relocalize(self, cancel_check=None) -> dict:
            """Call global_localization service then spin in place using a ROS timer.

            Ref: Nav2 TimedBehavior pattern — onRun() + onCycleUpdate() state machine.
            The timer publishes cmd_vel on the ROS executor thread, keeping it free
            for AMCL subscription callbacks. The ThreadPoolExecutor worker waits on
            a threading.Event, not time.sleep.

            Args:
                cancel_check: Optional callable returning True to abort spin early.
            """
            self.get_logger().info("Relocalization: calling reinitialize_global_localization...")

            # Phase 1: Call the global localization service (spread AMCL particles)
            if not self._global_loc_client.wait_for_service(timeout_sec=5.0):
                return {"status": "error",
                        "error": "global_localization service not available (AMCL may not be active)"}

            future = self._global_loc_client.call_async(Empty.Request())
            # Use rclpy spin_until_future_complete — keeps executor processing callbacks
            import rclpy
            rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
            if not future.done() or future.result() is None:
                return {"status": "error", "error": "global_localization service timed out"}

            self.get_logger().info("Global localization triggered — particles spread")
            self.get_logger().info(
                "Spinning in place for %.0fs to collect laser data...",
                RELOCALIZE_SPIN_DURATION,
            )

            # Phase 2: Timer-based spin (Nav2 TimedBehavior pattern)
            # Timer runs on executor thread → AMCL callbacks still fire
            # Worker thread waits on Event → does not block executor
            spin_done = threading.Event()
            spin_result = {"cancelled": False}

            twist = Twist()
            twist.angular.z = RELOCALIZE_SPIN_SPEED
            spin_start = time.monotonic()

            def _spin_tick():
                elapsed = time.monotonic() - spin_start

                # Check cancellation
                if cancel_check is not None and cancel_check():
                    self._cmd_vel_pub.publish(Twist())  # stop
                    spin_result["cancelled"] = True
                    spin_timer.cancel()
                    spin_done.set()
                    return

                # Check completion
                if elapsed >= RELOCALIZE_SPIN_DURATION:
                    self._cmd_vel_pub.publish(Twist())  # stop
                    spin_timer.cancel()
                    spin_done.set()
                    return

                # Publish spin command
                self._cmd_vel_pub.publish(twist)

            spin_timer = self.create_timer(_RELOC_TICK_PERIOD, _spin_tick)

            # Block only the ThreadPoolExecutor worker, not the ROS executor
            spin_done.wait(timeout=RELOCALIZE_SPIN_DURATION + 5.0)

            # Safety: ensure timer is cleaned up
            if not spin_done.is_set():
                spin_timer.cancel()
                self._cmd_vel_pub.publish(Twist())

            # Destroy the one-shot timer to avoid resource leaks
            self.destroy_timer(spin_timer)

            if spin_result["cancelled"]:
                self.get_logger().info("Relocalization cancelled by user")
                return {"status": "cancelled"}

            # Check if localization improved
            health = self.executor_core.get_localization_health()
            if health["healthy"]:
                self.get_logger().info(
                    "Relocalization succeeded (covariance: %.4f)",
                    health.get("covariance_xy", -1),
                )
                return {"status": "success", "localization": health}
            else:
                self.get_logger().warn(
                    "Relocalization finished but localization still unhealthy: %s",
                    health.get("reason", ""),
                )
                return {
                    "status": "partial",
                    "localization": health,
                    "hint": "Try setting initial pose manually via RViz2 or deploy.sh",
                }
```

- [ ] **Step 3: Update the callback wiring (line ~453) to match new signature**

The existing line:
```python
self.executor_core._relocalize_callback = self._do_relocalize
```
No change needed — the callback now accepts `**kwargs` including `cancel_check`.

- [ ] **Step 4: Verify build/import works**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python -c "from campus_nav_llm.task_executor_node import TaskExecutorCore, RELOCALIZE_SPIN_SPEED, _RELOC_TICK_PERIOD; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Run existing tests**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python -m pytest tests/ -v`
Expected: All tests PASS (existing functionality unchanged)

- [ ] **Step 6: Commit**

```bash
git add campus_guide_bot/campus_nav_llm/campus_nav_llm/task_executor_node.py
git commit -m "feat: replace blocking relocalize spin with timer-based pattern (Nav2 TimedBehavior)

Timer publishes cmd_vel on ROS executor thread, keeping it free for AMCL
callbacks. ThreadPoolExecutor worker waits on threading.Event, not sleep.
Adds cancellation support via cancel_check callback."
```

---

### Task 4: Consolidate — remove duplicate _do_relocalize from LLMPlannerNode

**Files:**
- Modify: `campus_nav_llm/llm_planner_node.py:479-487` (callback wiring)
- Modify: `campus_nav_llm/llm_planner_node.py:528-566` (delete duplicate method)
- Modify: `campus_nav_llm/llm_planner_node.py:589-623` (pass cancel_check via _local_tool_executor)

- [ ] **Step 1: Delete the duplicate _do_relocalize from LLMPlannerNode**

Remove the entire `_do_relocalize` method from `llm_planner_node.py` (lines 528-566). This was a copy-paste of TaskExecutorNode's version.

- [ ] **Step 2: Update callback wiring to delegate to the TaskExecutorNode's method**

In `LLMPlannerNode.__init__`, the relocalization setup (around lines 479-487) currently creates its own service client, cmd_vel publisher, and wires `self._do_relocalize`. Replace with delegation to `TaskExecutorNode._do_relocalize` through the node reference.

Replace lines 479-487:
```python
        # Relocalization: wire up global_localization service + cmd_vel
        # Ref: Nav2 reinitialize_global_localization service
        from geometry_msgs.msg import Twist
        from std_srvs.srv import Empty as EmptySrv
        global_loc_srv = f"/{ns}/reinitialize_global_localization" if ns else "/reinitialize_global_localization"
        self._global_loc_client = self.create_client(EmptySrv, global_loc_srv)
        cmd_vel_topic = f"/{ns}/cmd_vel" if ns else "/cmd_vel"
        self._cmd_vel_pub = self.create_publisher(Twist, cmd_vel_topic, 10)
        self.executor_core._relocalize_callback = self._do_relocalize
```

With:
```python
        # Relocalization: create ROS resources needed by the shared _do_relocalize
        # Ref: Nav2 reinitialize_global_localization service
        from geometry_msgs.msg import Twist
        from std_srvs.srv import Empty as EmptySrv
        global_loc_srv = f"/{ns}/reinitialize_global_localization" if ns else "/reinitialize_global_localization"
        self._global_loc_client = self.create_client(EmptySrv, global_loc_srv)
        cmd_vel_topic = f"/{ns}/cmd_vel" if ns else "/cmd_vel"
        self._cmd_vel_pub = self.create_publisher(Twist, cmd_vel_topic, 10)
        self.executor_core._relocalize_callback = self._do_relocalize
```

Then add the shared `_do_relocalize` method on `LLMPlannerNode` that reuses the same timer-based pattern. Since `LLMPlannerNode` and `TaskExecutorNode` are both `rclpy.Node` subclasses with identical ROS resources (`_global_loc_client`, `_cmd_vel_pub`, `executor_core`), we extract the core logic into a **module-level function** that accepts the node as parameter:

Add this function to `task_executor_node.py` after the `_RELOC_TICK_PERIOD` constant (new lines after ~44):

```python
def do_relocalize(node, cancel_check=None) -> dict:
    """Non-blocking relocalization: global_localization service + timer-based spin.

    Ref: Nav2 TimedBehavior pattern — timer publishes cmd_vel on the ROS
    executor thread, keeping it free for AMCL callbacks. The calling thread
    (ThreadPoolExecutor worker) waits on threading.Event.

    Args:
        node: ROS node with ._global_loc_client, ._cmd_vel_pub, .executor_core
        cancel_check: Optional callable returning True to abort spin early.

    Returns:
        dict with status key ("success", "partial", "cancelled", or "error").
    """
    from geometry_msgs.msg import Twist
    from std_srvs.srv import Empty as EmptySrv
    import rclpy

    node.get_logger().info("Relocalization: calling reinitialize_global_localization...")

    # Phase 1: Call the global localization service (spread AMCL particles)
    if not node._global_loc_client.wait_for_service(timeout_sec=5.0):
        return {"status": "error",
                "error": "global_localization service not available (AMCL may not be active)"}

    future = node._global_loc_client.call_async(EmptySrv.Request())
    rclpy.spin_until_future_complete(node, future, timeout_sec=10.0)
    if not future.done() or future.result() is None:
        return {"status": "error", "error": "global_localization service timed out"}

    node.get_logger().info("Global localization triggered — particles spread")
    node.get_logger().info(
        "Spinning in place for %.0fs to collect laser data...",
        RELOCALIZE_SPIN_DURATION,
    )

    # Phase 2: Timer-based spin (Nav2 TimedBehavior pattern)
    spin_done = threading.Event()
    spin_result = {"cancelled": False}

    twist = Twist()
    twist.angular.z = RELOCALIZE_SPIN_SPEED
    spin_start = time.monotonic()

    def _spin_tick():
        elapsed = time.monotonic() - spin_start

        if cancel_check is not None and cancel_check():
            node._cmd_vel_pub.publish(Twist())
            spin_result["cancelled"] = True
            spin_timer.cancel()
            spin_done.set()
            return

        if elapsed >= RELOCALIZE_SPIN_DURATION:
            node._cmd_vel_pub.publish(Twist())
            spin_timer.cancel()
            spin_done.set()
            return

        node._cmd_vel_pub.publish(twist)

    spin_timer = node.create_timer(_RELOC_TICK_PERIOD, _spin_tick)
    spin_done.wait(timeout=RELOCALIZE_SPIN_DURATION + 5.0)

    if not spin_done.is_set():
        spin_timer.cancel()
        node._cmd_vel_pub.publish(Twist())

    node.destroy_timer(spin_timer)

    if spin_result["cancelled"]:
        node.get_logger().info("Relocalization cancelled by user")
        return {"status": "cancelled"}

    health = node.executor_core.get_localization_health()
    if health["healthy"]:
        node.get_logger().info(
            "Relocalization succeeded (covariance: %.4f)",
            health.get("covariance_xy", -1),
        )
        return {"status": "success", "localization": health}
    else:
        node.get_logger().warn(
            "Relocalization finished but localization still unhealthy: %s",
            health.get("reason", ""),
        )
        return {
            "status": "partial",
            "localization": health,
            "hint": "Try setting initial pose manually via RViz2 or deploy.sh",
        }
```

Then in **both** `TaskExecutorNode._do_relocalize` and `LLMPlannerNode._do_relocalize`, replace with a one-liner:

```python
        def _do_relocalize(self, cancel_check=None) -> dict:
            return do_relocalize(self, cancel_check=cancel_check)
```

- [ ] **Step 3: Update LLMPlannerNode._local_tool_executor to pass cancel_check**

In `llm_planner_node.py`, modify `_local_tool_executor` (around line 589) to inject `_cancel_check` into tool_input for relocalize:

Find:
```python
    # Direct in-process execution — the core fix
    result = self.executor_core.execute(tool_name, tool_input, request_id)
```

Replace with:
```python
    # Inject cancel_check for relocalize tool
    if tool_name == "relocalize":
        tool_input = dict(tool_input) if tool_input else {}
        tool_input["_cancel_check"] = lambda: self._cancel_requested

    # Direct in-process execution — the core fix
    result = self.executor_core.execute(tool_name, tool_input, request_id)
```

- [ ] **Step 4: Remove stale imports from llm_planner_node.py**

Remove the now-unused import on line 534 (inside the deleted `_do_relocalize`):
```python
from campus_nav_llm.task_executor_node import RELOCALIZE_SPIN_SPEED, RELOCALIZE_SPIN_DURATION
```

- [ ] **Step 5: Verify import works**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python -c "from campus_nav_llm.task_executor_node import do_relocalize; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Run all tests**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add campus_guide_bot/campus_nav_llm/campus_nav_llm/task_executor_node.py campus_guide_bot/campus_nav_llm/campus_nav_llm/llm_planner_node.py
git commit -m "refactor: consolidate duplicate _do_relocalize into shared do_relocalize()

Extract timer-based relocalization into module-level do_relocalize(node)
in task_executor_node.py. Both LLMPlannerNode and TaskExecutorNode now
delegate to it. Eliminates code duplication (Critical issue #2).
LLMPlannerNode passes _cancel_requested via cancel_check kwarg."
```

---

### Task 5: Add integration-level test for cancel_check propagation

**Files:**
- Modify: `campus_nav_llm/tests/test_relocalize.py`

- [ ] **Step 1: Add cancel propagation test**

Append to `test_relocalize.py`:

```python
class TestRelocalizeCancellation:
    """Test that cancellation propagates through the full dispatch chain."""

    def test_cancel_check_injected_for_relocalize(self, executor):
        """When _cancel_check is in tool_input, it's forwarded to callback."""
        received_kwargs = {}

        def mock_callback(**kwargs):
            received_kwargs.update(kwargs)
            return {"status": "success", "localization": {"healthy": True}}

        executor._relocalize_callback = mock_callback
        cancel_fn = lambda: True

        result = executor.execute("relocalize", {"_cancel_check": cancel_fn})
        assert "cancel_check" in received_kwargs
        assert received_kwargs["cancel_check"]() is True
        assert result["status"] == "success"

    def test_relocalize_without_cancel_check(self, executor):
        """Without _cancel_check, callback receives no cancel_check kwarg."""
        received_kwargs = {}

        def mock_callback(**kwargs):
            received_kwargs.update(kwargs)
            return {"status": "success", "localization": {"healthy": True}}

        executor._relocalize_callback = mock_callback
        result = executor.execute("relocalize", {})
        assert "cancel_check" not in received_kwargs
        assert result["status"] == "success"
```

- [ ] **Step 2: Run all tests**

Run: `cd /home/khouryloaner/CS5335TurtleBot/campus_guide_bot/campus_nav_llm && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add campus_guide_bot/campus_nav_llm/tests/test_relocalize.py
git commit -m "test: add cancel_check propagation tests for relocalize dispatch"
```

---

## Self-Review

**Spec coverage:**
- Critical #1 (blocking executor): Fixed by timer-based spin in `do_relocalize()` (Task 3/4) ✓
- Critical #2 (duplicate code): Fixed by extracting `do_relocalize()` module-level function (Task 4) ✓
- Cancellation support: Added via `cancel_check` kwarg threaded through `_relocalize` → callback (Tasks 2-4) ✓
- Test coverage: New tests for callback dispatch, cancel_check forwarding, exception handling (Tasks 1, 5) ✓

**Placeholder scan:** No TBDs, TODOs, or vague instructions. All code blocks are complete.

**Type consistency:** `cancel_check` is consistently `Optional[Callable[[], bool]]` throughout. `do_relocalize(node, cancel_check)` signature matches all call sites. `_cancel_check` key name is consistent in `inp` dict.

**Risk assessment:**
- `rclpy.spin_until_future_complete` may conflict with an already-spinning executor. In our architecture, this is called from a `ThreadPoolExecutor` worker, not the main executor thread. The Nav2 `BasicNavigator` uses the same pattern (spin_until_future_complete from worker threads), so this is safe.
- `create_timer` / `destroy_timer` from a non-executor thread: rclpy allows this — timers are scheduled on the executor regardless of creation thread.
