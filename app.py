"""WSLg / Ubuntu 原生图形控制台，直接集成 ROS 2 节点。"""
import json
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

import rclpy
from tools.robot import Robot, create_tools


class Panel:
    def __init__(self, root):
        self.root = root
        self.closing = False
        self.busy = False
        self.events = queue.Queue()
        self.robot = Robot()
        self.tools = create_tools(self.robot)
        self.spin_thread = threading.Thread(target=self.spin, daemon=True)
        self.spin_thread.start()
        root.title('FishBot ROS 2 工具控制台 · Ubuntu')
        root.geometry('900x700')
        root.minsize(760, 600)
        frame = ttk.Frame(root, padding=22)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='FishBot ROS 2 工具控制台', font=('', 21, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='直接发布 /cmd_vel · 订阅 /odom · ROS 2 Humble').pack(anchor='w', pady=(6, 14))
        top = ttk.Frame(frame)
        top.pack(fill='x')
        ttk.Button(top, text='启动 / 检查 micro-ROS 桥', command=self.start_agent).pack(side='left')
        ttk.Button(top, text='查询状态', command=lambda: self.call('fishbot_status', {})).pack(side='left', padx=10)
        ttk.Button(top, text='立即停车', command=lambda: self.call('fishbot_stop', {})).pack(side='right')
        self.status = tk.StringVar(value='尚未查询；请确认小车已接入 ROS 2')
        ttk.Label(frame, textvariable=self.status, wraplength=820).pack(anchor='w', pady=14)
        controls = ttk.Frame(frame)
        controls.pack(fill='x')
        self.entries = {}
        self.motion_buttons = []
        for column, (title, fields, tool) in enumerate([
            ('前进 / 后退', [('meters', '距离（米，±10，非零）', '0.20'), ('speed', '线速度（0.02–0.20 m/s）', '0.05')], 'fishbot_move'),
            ('原地转向', [('degrees', '角度（±180°，非零）', '90'), ('angularSpeed', '角速度（0.1–1.0 rad/s）', '0.30')], 'fishbot_turn')
        ]):
            group = ttk.LabelFrame(controls, text=title, padding=16)
            group.grid(row=0, column=column, sticky='nsew', padx=(0, 8))
            controls.columnconfigure(column, weight=1)
            for name, label, value in fields:
                ttk.Label(group, text=label).pack(anchor='w')
                entry = ttk.Entry(group)
                entry.insert(0, value)
                entry.pack(fill='x', pady=(4, 10))
                self.entries[name] = entry
            button = ttk.Button(group, text='执行' + title, command=lambda t=tool, f=fields: self.move(t, f))
            button.pack(fill='x', pady=5)
            self.motion_buttons.append(button)
        ttk.Label(frame, text='调用结果（状态为最近一次查询；停车与状态查询可在运动期间执行）').pack(anchor='w', pady=(18, 6))
        self.log = tk.Text(frame, wrap='word', height=15)
        self.log.pack(fill='both', expand=True)
        self.write('工具已注册：' + ', '.join(self.tools))
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(80, self.poll)

    def write(self, text):
        self.log.insert('end', text + '\n\n')
        self.log.see('end')
        if int(self.log.index('end-1c').split('.')[0]) > 1500:
            self.log.delete('1.0', '500.0')

    def move(self, name, fields):
        if self.busy:
            return
        try:
            arguments = {key: float(self.entries[key].get()) for key, _, _ in fields}
            # 工具层继续验证范围，UI 仅负责数值解析。
            self.call(name, arguments, motion=True)
        except ValueError as error:
            self.write('输入错误：' + str(error))

    def call(self, name, arguments, motion=False):
        if self.closing:
            return
        if motion:
            self.busy = True
            for button in self.motion_buttons:
                button.configure(state='disabled')
        self.write('> ' + name + ' ' + json.dumps(arguments, ensure_ascii=False))

        def work():
            try:
                result = self.tools[name].invoke(arguments)
            except Exception as error:
                result = {'ok': False, 'error': str(error)}
            self.events.put((name, result, motion))
        threading.Thread(target=work, daemon=True).start()

    def start_agent(self):
        def work():
            try:
                # 重用运行中的已知 agent，不移除或重启已有容器。
                for name in ('micro_ros_agent', 'fishbot_ros2_panel_agent'):
                    check = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', name], capture_output=True, text=True, timeout=10)
                    if check.returncode == 0 and check.stdout.strip() == 'true':
                        self.events.put(('micro_ros_agent', {'ok': True, 'message': '重用容器 ' + name}, False))
                        return
                name = 'fishbot_ros2_panel_agent'
                check = subprocess.run(['docker', 'inspect', name], capture_output=True, timeout=10)
                command = ['docker', 'start', name] if check.returncode == 0 else ['docker', 'run', '-d', '--name', name, '--network', 'host', 'microros/micro-ros-agent:humble', 'udp4', '--port', '8888', '-v4']
                result = subprocess.run(command, capture_output=True, text=True, timeout=30)
                self.events.put(('micro_ros_agent', {'ok': result.returncode == 0, 'message': (result.stdout + result.stderr).strip()}, False))
            except Exception as error:
                self.events.put(('micro_ros_agent', {'ok': False, 'error': str(error)}, False))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        if self.closing:
            return
        while True:
            try:
                name, result, motion = self.events.get_nowait()
            except queue.Empty:
                break
            self.write(json.dumps(result, ensure_ascii=False, indent=2))
            if motion:
                self.busy = False
                for button in self.motion_buttons:
                    button.configure(state='normal')
            if name == 'fishbot_status':
                pose = result.get('pose')
                self.status.set(('小车已就绪' if result.get('ready') else '小车未就绪') + ' | ' + json.dumps(pose, ensure_ascii=False) + ' | odom 帧龄 ' + str(result.get('odom_age_ms')) + ' ms')
        self.root.after(80, self.poll)

    def spin(self):
        try:
            rclpy.spin(self.robot)
        except rclpy.executors.ExternalShutdownException:
            pass

    def close(self):
        self.closing = True
        self.robot.stop()
        rclpy.shutdown()
        self.spin_thread.join(timeout=2)
        self.robot.destroy_node()
        self.root.destroy()


if __name__ == '__main__':
    rclpy.init()
    window = tk.Tk()
    Panel(window)
    window.mainloop()
