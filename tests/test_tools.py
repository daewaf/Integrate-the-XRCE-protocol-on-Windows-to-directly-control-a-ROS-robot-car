import math
import os
os.environ['ROS_DOMAIN_ID'] = '187'
import unittest
import threading
import time
from tools.robot import create_tools, Robot
import rclpy
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
from rclpy.executors import SingleThreadedExecutor


class FakeRobot:
    def status(self):
        return {'ok': True}
    def stop(self):
        return {'ok': True}
    def run_motion(self, *args):
        return args


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tools = create_tools(FakeRobot())

    def test_names(self):
        self.assertEqual(set(self.tools), {'fishbot_status', 'fishbot_stop', 'fishbot_move', 'fishbot_turn'})

    def test_move_defaults(self):
        self.assertEqual(self.tools['fishbot_move'].invoke({'meters': -.2}), ('move', -.2, .05))

    def test_turn_units(self):
        args = self.tools['fishbot_turn'].invoke({'degrees': -90})
        self.assertAlmostEqual(args[1], -math.pi/2)

    def test_invalid_parameters(self):
        for args in ({}, [], {'meters': 0}, {'meters': float('nan')}, {'meters': True}, {'meters': 11}, {'meters': .1, 'speed': 0}, {'meters': .1, 'unknown': 1}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.tools['fishbot_move'].invoke(args)

    def test_stop(self):
        self.assertTrue(self.tools['fishbot_stop'].invoke({})['ok'])


class NodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()

    @classmethod
    def tearDownClass(cls):
        rclpy.shutdown()

    def setUp(self):
        self.robot = Robot()

    def tearDown(self):
        self.robot.stop()
        self.robot.destroy_node()

    def test_odom_pose_and_not_ready_without_subscriber(self):
        odom = Odometry()
        odom.pose.pose.position.x = 1.25
        odom.pose.pose.orientation.z = math.sin(math.pi/4)
        odom.pose.pose.orientation.w = math.cos(math.pi/4)
        self.robot.on_odom(odom)
        state = self.robot.status()
        self.assertAlmostEqual(state['pose']['yaw'], 90)
        self.assertEqual(state['pose']['x'], 1.25)
        self.assertFalse(state['ready'])

    def test_no_odom_no_motion(self):
        result = self.robot.run_motion('move', .2, .05)
        self.assertFalse(result['ok'])
        self.assertEqual(self.robot.motion, 'idle')

    def test_cancel_generation(self):
        generation = self.robot.generation
        self.robot.stop()
        self.assertGreater(self.robot.generation, generation)

    def test_ros_closed_loop_simulation(self):
        simulator = rclpy.create_node('fishbot_test_simulator')
        publisher = simulator.create_publisher(Odometry, '/odom', 10)
        velocity = [0.0, 0.0]
        pose = [0.0, 0.0, 0.0]

        def command(message):
            velocity[:] = [message.linear.x, message.angular.z]

        subscriber = simulator.create_subscription(Twist, '/cmd_vel', command, 10)

        def tick():
            pose[0] += velocity[0] * math.cos(pose[2]) * .02
            pose[1] += velocity[0] * math.sin(pose[2]) * .02
            pose[2] += velocity[1] * .02
            message = Odometry()
            message.pose.pose.position.x = pose[0]
            message.pose.pose.position.y = pose[1]
            message.pose.pose.orientation.z = math.sin(pose[2]/2)
            message.pose.pose.orientation.w = math.cos(pose[2]/2)
            publisher.publish(message)

        timer = simulator.create_timer(.02, tick)
        executor = SingleThreadedExecutor()
        executor.add_node(simulator)
        executor.add_node(self.robot)
        thread = threading.Thread(target=executor.spin, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not self.robot.status()['ready'] and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(self.robot.status()['ready'])
            self.assertTrue(self.robot.run_motion('move', .05, .1)['ok'])
            self.assertAlmostEqual(pose[0], .05, delta=.006)
            self.assertTrue(self.robot.run_motion('turn', math.radians(15), .3)['ok'])
            self.assertAlmostEqual(math.degrees(pose[2]), 15, delta=1.6)
        finally:
            self.robot.stop()
            executor.shutdown()
            thread.join(timeout=2)
            simulator.destroy_node()


if __name__ == '__main__':
    unittest.main()
