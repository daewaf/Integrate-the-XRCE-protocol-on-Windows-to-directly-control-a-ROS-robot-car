# FishBot ROS 2 / Ubuntu 控制台

新项目在 WSL Ubuntu 22.04 中运行，ROS 2 Humble 节点直接集成在 Tk 图形界面进程内。
不使用原 C# XRCE agent、本机 TCP8898 或 rosbridge。原项目无需改动。

Windows 运行 `启动ROS2界面.cmd`；Ubuntu 终端运行 `bash start.sh`。需要 WSLg（当前环境已有）。
界面提供四个 JSON 工具：`fishbot_status`、`fishbot_stop`、`fishbot_move`、`fishbot_turn`。
距离、速度及角度单位和旧工具一致；工具定义、参数校验和调用入口在 `tools/robot.py`。
WPF 无法直接运行于 Linux，因此新界面使用 Python / Tk，工具采用同样的名称、描述、JSON Schema、JSON 参数对象格式，未保留 C# 二进制接口。

## ROS 2 与小车

界面内的节点 `fishbot_tool_panel` 发布 `/cmd_vel`（Twist），订阅 `/odom`（Odometry，sensor-data QoS）。
运动使用里程计闭环；运动前要求新鲜里程计和速度订阅者。帧龄超过0.5秒、取消、超时和退出均发零速度。
查询返回的 `ok` 表示调用成功，`ready` 才表示订阅者和里程计满足当前运动条件。
小车没有避障功能，实车测试需自行确保行驶空间。

当前小车使用 micro-ROS 固件，仍需标准 micro-ROS agent 将 XRCE 转换为 ROS 2 DDS。
界面中的“启动 / 检查 micro-ROS 桥”重用 `micro_ros_agent` 或本项目的运行中容器，否则启动本项目专用容器。
使用已有镜像 `microros/micro-ros-agent:humble` 和 Docker host 网络，UDP8888。
退出界面会停车但保留该桥，以免小车会话反复重建。不自动操作其他容器或 Windows agent。
启动标准桥前，先关闭占用 Windows UDP8888 的旧 agent，确保不存在冲突。

WSL2 默认 NAT 网络不保证局域网 UDP8888 可直接进入 WSL。
若小车未出现，检查 WSL 网络模式、Windows/Hyper-V 防火墙及 UDP 转发；普通 `netsh portproxy` 不能转发 UDP。
小车应连接同一局域网，目标地址应是实际能够进入该 WSL UDP8888 的主机地址。
界面可以在已有 ROS 2 `/cmd_vel`、`/odom` 环境中直接使用，不要求小车必须通过本项目启动桥。

## 验证

```bash
source /opt/ros/humble/setup.bash
python3 -m unittest discover -s tests -v
```

测试自动使用 ROS_DOMAIN_ID=187，与默认实车域隔离；不要将实车配置到该测试域。
9 项测试包含参数校验、里程计解析及 ROS 2 仿真闭环前进和转向，已通过；图形窗口启动与退出已验证。
当前环境已具备 ROS 2 Humble、rclpy、消息包、Tk 和 micro-ROS Docker 镜像，WSL 配置为 mirrored 网络。
尚未验证实际小车话题发现与运动。WSL 偶尔提示 systemd 用户会话启动失败，但本次节点和图形测试均可正常运行。
