"""ROS 2 节点与四个 JSON 工具，界面与运动控制共享同一节点。"""
import math
import threading
import time
from dataclasses import dataclass

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry


class Robot(Node):
    """订阅里程计，周期发布速度并执行有超时的闭环动作。"""

    def __init__(self):
        super().__init__('fishbot_tool_panel')
        self.lock = threading.RLock()
        self.pose = None
        self.received = 0.0
        self.motion = 'idle'
        self.generation = 0
        self.velocity = (0.0, 0.0)
        self.command_deadline = 0.0
        self.publisher = self.create_publisher(Twist, '/cmd_vel', 10)
        self.subscription = self.create_subscription(Odometry, '/odom', self.on_odom, qos_profile_sensor_data)
        self.timer = self.create_timer(0.05, self.tick)

    def on_odom(self, message):
        p = message.pose.pose.position
        q = message.pose.pose.orientation
        yaw = math.atan2(2 * (q.w*q.z + q.x*q.y), 1 - 2 * (q.y*q.y + q.z*q.z))
        if not all(math.isfinite(v) for v in (p.x, p.y, yaw)):
            return
        with self.lock:
            self.pose = (p.x, p.y, yaw)
            self.received = time.monotonic()

    def tick(self):
        with self.lock:
            # 空闲时不持续覆盖其他 ROS 遥控器的命令。
            if self.motion == 'idle':
                return
            v, w = self.velocity
            if time.monotonic() > self.command_deadline or time.monotonic() - self.received > 0.5:
                v, w = 0.0, 0.0
            self.publish(v, w)

    def publish(self, v, w):
        message = Twist()
        message.linear.x, message.angular.z = float(v), float(w)
        self.publisher.publish(message)

    def stop(self):
        with self.lock:
            self.generation += 1
            self.velocity = (0.0, 0.0)
            self.motion = 'idle'
            self.publish(0, 0)
        return {'ok': True, 'message': '已发布零速度；不等于实车静止确认'}

    def status(self):
        with self.lock:
            age = time.monotonic() - self.received if self.pose else None
            readers = self.publisher.get_subscription_count()
            return {'ok': True, 'ready': age is not None and age < 0.5 and readers > 0,
                    'state': self.motion, 'pose': None if self.pose is None else
                    {'x': self.pose[0], 'y': self.pose[1], 'yaw': math.degrees(self.pose[2])},
                    'odom_age_ms': -1 if age is None else round(age * 1000),
                    'cmd_vel_subscribers': readers}

    def run_motion(self, kind, target, speed):
        with self.lock:
            if self.motion != 'idle':
                return {'ok': False, 'error': '已有运动，请等待或停车'}
            if not self.status()['ready']:
                return {'ok': False, 'error': '小车未就绪：需要新鲜 /odom 和 /cmd_vel 订阅者'}
            self.motion = kind
            self.generation += 1
            generation = self.generation
            start = self.pose
        deadline = time.monotonic() + abs(target) / speed + 10
        previous_yaw = start[2]
        accumulated_yaw = 0.0
        try:
            while time.monotonic() < deadline:
                with self.lock:
                    if generation != self.generation:
                        return {'ok': False, 'error': '动作已取消'}
                    if time.monotonic() - self.received > 0.5:
                        return {'ok': False, 'error': '里程计超时，已停车'}
                    x, y, yaw = self.pose
                    if kind == 'move':
                        traveled = (x-start[0])*math.cos(start[2]) + (y-start[1])*math.sin(start[2])
                        error = target - traveled
                        done = abs(error) <= 0.005
                        self.velocity = (max(-speed, min(speed, error * 2)), 0.0)
                    else:
                        accumulated_yaw += math.atan2(math.sin(yaw-previous_yaw), math.cos(yaw-previous_yaw))
                        previous_yaw = yaw
                        error = target - accumulated_yaw
                        done = abs(error) <= math.radians(1.5)
                        self.velocity = (0.0, max(-speed, min(speed, error * 2)))
                    if done:
                        return {'ok': True, 'message': '动作完成', 'status': self.status()}
                    self.command_deadline = time.monotonic() + 0.2
                time.sleep(0.02)
            return {'ok': False, 'error': '动作超时，已停车'}
        finally:
            with self.lock:
                if generation == self.generation:
                    self.stop()


@dataclass
class AgentTool:
    """沿用名称、描述、参数 Schema 和 JSON 对象调用的工具格式。"""
    name: str
    description: str
    parameters_schema: dict
    handler: object

    def invoke(self, arguments):
        if not isinstance(arguments, dict):
            raise ValueError('参数必须为 JSON 对象')
        properties = self.parameters_schema['properties']
        if set(arguments) - set(properties):
            raise ValueError('存在未知参数')
        for name in self.parameters_schema.get('required', []):
            if name not in arguments:
                raise ValueError('缺少参数：' + name)
        for name, value in arguments.items():
            spec = properties[name]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(name + ' 必须为有限数字')
            if not spec['minimum'] <= value <= spec['maximum'] or (name in ('meters', 'degrees') and value == 0):
                raise ValueError(name + ' 超出范围或为零')
        return self.handler(**arguments)


def create_tools(robot):
    def schema(properties, required):
        return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}

    def number(low, high, default=None):
        result = {'type': 'number', 'minimum': low, 'maximum': high}
        if default is not None:
            result['default'] = default
        return result

    return {
        'fishbot_status': AgentTool('fishbot_status', '查询连接、位姿和运动状态', schema({}, []), robot.status),
        'fishbot_stop': AgentTool('fishbot_stop', '发布零速度并取消运动', schema({}, []), robot.stop),
        'fishbot_move': AgentTool('fishbot_move', '前进或后退指定米数', schema({'meters': number(-10, 10), 'speed': number(.02, .2, .05)}, ['meters']), lambda meters, speed=.05: robot.run_motion('move', meters, speed)),
        'fishbot_turn': AgentTool('fishbot_turn', '正角度左转，负角度右转', schema({'degrees': number(-180, 180), 'angularSpeed': number(.1, 1, .3)}, ['degrees']), lambda degrees, angularSpeed=.3: robot.run_motion('turn', math.radians(degrees), angularSpeed)),
    }
