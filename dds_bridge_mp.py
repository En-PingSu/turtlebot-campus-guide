#!/usr/bin/env python3
"""Two-process DDS Bridge: Discovery Server <-> Simple Discovery.

Process 1 (DS): subscribes to robot topics via Discovery Server
Process 2 (SD): publishes to Simple Discovery for local Nav2 nodes

Uses multiprocessing with spawn to ensure each process gets clean DDS init.
"""
import os
import sys
import signal
import multiprocessing as mp
import time
from pathlib import Path

# Read config from config.yaml (single source of truth)
_CONFIG_FILE = Path(__file__).parent / "config.yaml"
_ROBOT_IP = "192.168.50.31"
_DISCOVERY_PORT = "11811"
NS = "turtlebot468"

try:
    import yaml
    if _CONFIG_FILE.exists():
        _cfg = yaml.safe_load(_CONFIG_FILE.read_text())
        _ROBOT_IP = str(_cfg.get("robot", {}).get("ip", _ROBOT_IP))
        _DISCOVERY_PORT = str(_cfg.get("dds", {}).get("discovery_port", _DISCOVERY_PORT))
        NS = str(_cfg.get("robot", {}).get("namespace", NS))
except ImportError:
    pass

_DISCOVERY_SERVER = f"{_ROBOT_IP}:{_DISCOVERY_PORT}"


def ds_subscriber(queue):
    """Runs in Discovery Server domain."""
    os.environ["ROS_DISCOVERY_SERVER"] = _DISCOVERY_SERVER
    os.environ["ROS_SUPER_CLIENT"] = "False"
    os.environ.pop("FASTRTPS_DEFAULT_PROFILES_FILE", None)

    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from rclpy.serialization import serialize_message
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import LaserScan
    from tf2_msgs.msg import TFMessage

    SENSOR_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
    RELIABLE_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
    TF_STATIC_QOS = QoSProfile(
        depth=10, reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )

    rclpy.init()
    node = Node("bridge_ds_sub")
    count = [0]

    def make_cb(topic, msg_type):
        def cb(msg):
            try:
                data = serialize_message(msg)
                queue.put_nowait((topic, msg_type.__module__ + ":" + msg_type.__name__, data))
                count[0] += 1
                if count[0] % 200 == 0:
                    node.get_logger().info(f"DS->queue: {count[0]} msgs")
            except Exception:
                pass
        return cb

    bridges = [
        (f"/{NS}/odom", Odometry, SENSOR_QOS),
        (f"/{NS}/scan", LaserScan, SENSOR_QOS),
        (f"/{NS}/tf", TFMessage, RELIABLE_QOS),
        (f"/{NS}/tf_static", TFMessage, TF_STATIC_QOS),
    ]
    for topic, msg_type, qos in bridges:
        node.create_subscription(msg_type, topic, make_cb(topic, msg_type), qos)
        node.get_logger().info(f"DS subscribed: {topic}")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


def sd_publisher(queue):
    """Runs in Simple Discovery domain."""
    os.environ.pop("ROS_DISCOVERY_SERVER", None)
    os.environ.pop("ROS_SUPER_CLIENT", None)
    os.environ.pop("FASTRTPS_DEFAULT_PROFILES_FILE", None)

    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from rclpy.serialization import deserialize_message
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import LaserScan
    from tf2_msgs.msg import TFMessage
    from geometry_msgs.msg import TransformStamped
    from tf2_ros import TransformBroadcaster

    SENSOR_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
    RELIABLE_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
    TF_STATIC_QOS = QoSProfile(
        depth=10, reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )

    rclpy.init()
    node = Node("bridge_sd_pub")
    tf_broadcaster = TransformBroadcaster(node)

    TYPE_MAP = {
        "nav_msgs.msg._odometry:Odometry": Odometry,
        "sensor_msgs.msg._laser_scan:LaserScan": LaserScan,
        "tf2_msgs.msg._tf_message:TFMessage": TFMessage,
    }

    pubs = {}
    qos_map = {
        f"/{NS}/odom": SENSOR_QOS,
        f"/{NS}/scan": SENSOR_QOS,
        f"/{NS}/tf": RELIABLE_QOS,
        f"/{NS}/tf_static": TF_STATIC_QOS,
    }

    count = [0]

    def publish_odom_tf(odom_msg):
        t = TransformStamped()
        t.header = odom_msg.header
        t.child_frame_id = odom_msg.child_frame_id or "base_link"
        t.transform.translation.x = odom_msg.pose.pose.position.x
        t.transform.translation.y = odom_msg.pose.pose.position.y
        t.transform.translation.z = odom_msg.pose.pose.position.z
        t.transform.rotation = odom_msg.pose.pose.orientation
        tf_broadcaster.sendTransform(t)

    node.get_logger().info("SD publisher ready, waiting for messages...")

    while rclpy.ok():
        try:
            topic, type_key, data = queue.get(timeout=0.05)
        except Exception:
            rclpy.spin_once(node, timeout_sec=0.01)
            continue

        msg_type = TYPE_MAP.get(type_key)
        if msg_type is None:
            continue

        msg = deserialize_message(data, msg_type)

        if topic not in pubs:
            qos = qos_map.get(topic, RELIABLE_QOS)
            pubs[topic] = node.create_publisher(msg_type, topic, qos)
            node.get_logger().info(f"SD publishing: {topic}")

        pubs[topic].publish(msg)

        if "odom" in topic and msg_type == Odometry:
            publish_odom_tf(msg)

        count[0] += 1
        if count[0] % 200 == 0:
            node.get_logger().info(f"SD published: {count[0]} msgs")

        rclpy.spin_once(node, timeout_sec=0)

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    mp.set_start_method("spawn")
    queue = mp.Queue(maxsize=500)

    ds_proc = mp.Process(target=ds_subscriber, args=(queue,))
    sd_proc = mp.Process(target=sd_publisher, args=(queue,))

    ds_proc.start()
    sd_proc.start()

    print(f"[Bridge] DS subscriber PID={ds_proc.pid}, SD publisher PID={sd_proc.pid}")
    print("[Bridge] Running. Ctrl+C to stop.")

    def shutdown(*_):
        ds_proc.terminate()
        sd_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    while True:
        if not ds_proc.is_alive() or not sd_proc.is_alive():
            print("[Bridge] A subprocess died, exiting.")
            shutdown()
        time.sleep(5)
