# Critical Bug Fixes: Robot Interactions & Communication

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix critical and high-severity bugs in robot communication, LLM integration, and navigation safety checks before next real-robot test session.

**Architecture:** Targeted fixes across 7 files — no structural changes. Fixes fall into 3 categories: (1) broken feedback loop in external ros_llm chatgpt node, (2) missing safety checks in campus_nav_llm nodes, (3) unsafe patterns in external robot nodes.

**Tech Stack:** ROS 2 Humble, Python 3, OpenAI API, nav2_simple_commander

---

### Task 1: Fix function call response discarded as "null" (chatgpt.py)

**Files:**
- Modify: `campus_guide_bot/external/ros_llm/llm_model/llm_model/chatgpt.py:271-298`

The LLM never sees robot action results — every function call result is hardcoded to `"null"`.

- [ ] **Step 1: Fix `function_call_response_callback` to use actual response**

Replace lines 271-298 with:
```python
def function_call_response_callback(self, future):
    try:
        response = future.result()
        response_text = response.response_text
        self.get_logger().info(
            f"Response from ChatGPT_function_call_service: {response_text}"
        )
    except Exception as e:
        response_text = f"Error calling robot function: {e}"
        self.get_logger().error(f"ChatGPT function call service failed: {e}")

    self.add_message_to_history(
        role="function",
        name=self.function_name,
        content=str(response_text),
    )
    # Generate chat completion
    second_chatgpt_response = self.generate_chatgpt_response(config.chat_history)
    # Get response information
    message, text, function_call, function_flag = self.get_response_information(
        second_chatgpt_response
    )
    self.publish_string(text, self.llm_feedback_publisher)
```

- [ ] **Step 2: Fix race condition in `function_name` storage**

Replace lines 254-269:
```python
def function_call(self, function_call_input):
    function_call_input_str = json.dumps(function_call_input)
    function_name = function_call_input["name"]
    self.function_call_requst.request_text = function_call_input_str
    self.get_logger().info(
        f"Request for ChatGPT_function_call_service: {self.function_call_requst.request_text}"
    )
    future = self.function_call_client.call_async(self.function_call_requst)
    # Capture function_name in closure to avoid race condition
    future.add_done_callback(
        lambda f: self._handle_function_response(f, function_name)
    )

def _handle_function_response(self, future, function_name):
    try:
        response = future.result()
        response_text = response.response_text
        self.get_logger().info(
            f"Response from ChatGPT_function_call_service: {response_text}"
        )
    except Exception as e:
        response_text = f"Error calling robot function: {e}"
        self.get_logger().error(f"ChatGPT function call service failed: {e}")

    self.add_message_to_history(
        role="function",
        name=function_name,
        content=str(response_text),
    )
    second_chatgpt_response = self.generate_chatgpt_response(config.chat_history)
    message, text, function_call, function_flag = self.get_response_information(
        second_chatgpt_response
    )
    self.publish_string(text, self.llm_feedback_publisher)
```

- [ ] **Step 3: Uncommment service wait**

Uncomment the wait_for_service block (lines 93-96) and add timeout:
```python
if not self.function_call_client.wait_for_service(timeout_sec=10.0):
    self.get_logger().warn(
        "ChatGPT Function Call Server not available after 10s — "
        "function calls will fail until robot node starts"
    )
self.function_call_requst = ChatGPT.Request()
self.get_logger().info("ChatGPT Function Call client initialized")
```

- [ ] **Step 4: Commit**

### Task 2: Fix unchecked wait_for_server() in task_executor_node.py

**Files:**
- Modify: `campus_guide_bot/campus_nav_llm/campus_nav_llm/task_executor_node.py:414-417`

- [ ] **Step 1: Check return value and raise on failure**

Replace lines 414-417:
```python
self.get_logger().info("Waiting for navigate_to_pose action server...")
if not navigator.nav_to_pose_client.wait_for_server(timeout_sec=120.0):
    self.get_logger().error(
        "navigate_to_pose action server not available after 120s"
    )
    raise RuntimeError("Nav2 action server not ready — is deploy.sh still running?")
self.get_logger().info("navigate_to_pose action server is available")
```

- [ ] **Step 2: Same fix in llm_planner_node.py (lines 444-453)**

Replace lines 444-453:
```python
navigator = BasicNavigator(namespace=ns)
self.get_logger().info("Waiting for navigate_to_pose action server...")
server_ready = False
for attempt in range(4):  # 4 x 30s = 120s total
    if navigator.nav_to_pose_client.wait_for_server(timeout_sec=30.0):
        server_ready = True
        break
    self.get_logger().info(
        "  Action server not yet available (attempt %d/4)...", attempt + 1
    )
if not server_ready:
    self.get_logger().error(
        "navigate_to_pose action server not available after 120s — "
        "navigation will not work"
    )
    raise RuntimeError("Nav2 action server not ready — is deploy.sh still running?")
self.get_logger().info("Action server available")
```

- [ ] **Step 3: Add ThreadPoolExecutor shutdown to both nodes**

task_executor_node.py main():
```python
finally:
    node._thread_pool.shutdown(wait=False)
    node.destroy_node()
    rclpy.shutdown()
```

llm_planner_node.py main():
```python
finally:
    node._thread_pool.shutdown(wait=False)
    node.destroy_node()
    rclpy.shutdown()
```

- [ ] **Step 4: Commit**

### Task 3: Fix unsafe getattr() in all robot nodes

**Files:**
- Modify: `campus_guide_bot/external/ros_llm/llm_robot/llm_robot/turtle_robot.py:65-77`
- Modify: `campus_guide_bot/external/ros_llm/llm_robot/llm_robot/multi_robot.py:82-94`
- Modify: `campus_guide_bot/external/ros_llm/llm_robot/llm_robot/arx5_arm_robot.py:65-77`

- [ ] **Step 1: Fix all three `function_call_callback` methods**

Same pattern for all three files:
```python
def function_call_callback(self, request, response):
    try:
        req = json.loads(request.request_text)
        function_name = req["name"]
        function_args = json.loads(req["arguments"])
    except (json.JSONDecodeError, KeyError) as e:
        self.get_logger().error(f"Invalid function call request: {e}")
        response.response_text = f"Invalid request format: {e}"
        return response

    func_obj = getattr(self, function_name, None)
    if func_obj is None or not callable(func_obj):
        self.get_logger().error(f"Unknown function: {function_name}")
        response.response_text = f"Unknown function: {function_name}"
        return response

    try:
        function_execution_result = func_obj(**function_args)
    except Exception as error:
        self.get_logger().info(f"Failed to call function: {error}")
        response.response_text = str(error)
    else:
        response.response_text = str(function_execution_result)
    return response
```

- [ ] **Step 2: Commit**

### Task 4: Fix OS command injection in arx5_arm_robot.py

**Files:**
- Modify: `campus_guide_bot/external/ros_llm/llm_robot/llm_robot/arx5_arm_robot.py:79-98`

- [ ] **Step 1: Replace os.system() with direct ROS publisher**

```python
def publish_target_pose(self, **kwargs):
    x_value = float(kwargs.get("x", 0.2))
    y_value = float(kwargs.get("y", 0.2))
    z_value = float(kwargs.get("z", 0.2))
    roll_value = float(kwargs.get("roll", 0.2))
    pitch_value = float(kwargs.get("pitch", 0.2))
    yaw_value = float(kwargs.get("yaw", 0.2))

    msg = Float64MultiArray()
    msg.data = [x_value, y_value, z_value, roll_value, pitch_value, yaw_value]
    self.target_pose_publisher.publish(msg)
    self.get_logger().info(f"Published target pose: {msg.data}")
    return str(msg.data)
```

- [ ] **Step 2: Commit**

### Task 5: Fix multi_robot.py publisher key mismatch

**Files:**
- Modify: `campus_guide_bot/external/ros_llm/llm_robot/llm_robot/multi_robot.py:46-64,140-168`

- [ ] **Step 1: Use consistent key for empty robot_name**

In `__init__`, replace empty-string handling:
```python
for robot_name in config.multi_robots_name:
    pub_name = robot_name if robot_name else "default"
    if robot_name == "":
        self.pose_publishers[pub_name] = self.create_publisher(Pose, "/pose", 10)
        self.cmd_vel_publishers[pub_name] = self.create_publisher(Twist, "/cmd_vel", 10)
    else:
        self.pose_publishers[pub_name] = self.create_publisher(Pose, f"/{robot_name}/pose", 10)
        self.cmd_vel_publishers[pub_name] = self.create_publisher(Twist, f"/{robot_name}/cmd_vel", 10)
```

In `publish_cmd_vel`, fix the key mapping:
```python
# Set default robot name for empty string
if robot_name == "":
    robot_name = "default"

# Create publisher for new robot if not exist
if robot_name not in self.cmd_vel_publishers:
    self.cmd_vel_publishers[robot_name] = self.create_publisher(
        Twist, f"/{robot_name}/cmd_vel", 10
    )
```

- [ ] **Step 2: Commit**

### Task 6: Fix DDS bridge silent exception swallowing

**Files:**
- Modify: `campus_guide_bot/campus_nav_llm/campus_nav_llm/dds_bridge.py:102-112`

- [ ] **Step 1: Add exception logging**

```python
def spin_sd():
    try:
        sd_exec.spin()
    except Exception as e:
        print(f"[Bridge] SD executor error: {e}")
        import traceback
        traceback.print_exc()

def spin_ds():
    try:
        ds_exec.spin()
    except Exception as e:
        print(f"[Bridge] DS executor error: {e}")
        import traceback
        traceback.print_exc()
```

- [ ] **Step 2: Commit**

### Task 7: Fix turtle_robot.py async service call not waiting

**Files:**
- Modify: `campus_guide_bot/external/ros_llm/llm_robot/llm_robot/turtle_robot.py:102-114`

- [ ] **Step 1: Wait for service response**

```python
def reset_turtlesim(self, **kwargs):
    empty_req = Empty.Request()
    try:
        future = self.reset_client.call_async(empty_req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
        if future.result() is not None:
            return "Reset turtlesim successfully"
        else:
            return "Reset turtlesim timed out"
    except Exception as error:
        self.get_logger().info(f"Failed to reset turtlesim: {error}")
        return str(error)
```

- [ ] **Step 2: Commit**
