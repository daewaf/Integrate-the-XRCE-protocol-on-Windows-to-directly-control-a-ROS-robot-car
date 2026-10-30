# FishBot 纯 C# XRCE-DDS Agent

用 C# / .NET 8 重写的 FishBot 最小 XRCE-DDS agent。不依赖 ROS2、WSL 或第三方 NuGet 包。

## 环境

- Windows 10/11
- .NET SDK 8（本机已安装 8.0.303）
- 主控板 WiFi 与电脑同网；上位机 IP = 电脑 WLAN 地址，端口 8888

## 构建与自检

```powershell
cd "C:\Users\kw188\Desktop\ros小车\xrce_csharp_agent"
dotnet build -c Release
dotnet run -c Release -- --selftest
```

## 运行

```powershell
# agent + WASD 遥控（一个进程）
dotnet run -c Release

# 只运行 agent
dotnet run -c Release -- --agent-only

# 启动检查
dotnet run -c Release -- --check
```

按键：W 前进、S 后退、A 左转、D 右转、空格停、X 退出。
按住方向键持续运动，松开立即停止（轮询按键物理状态，不依赖键盘连发）。
遥控同时读取物理按键状态与终端按键事件，并在终端打印 `[KEY]`；
若物理按键状态不可用，按住方向键的终端连发也能驱动，松开约 1 秒内自动停止。

## 控制接口

其他程序可通过本机 TCP `127.0.0.1:8898` 控制小车：

```text
forward 0.50 0.05    # 前进 0.5m（闭环）
turn 90 0.3          # 左转 90°（闭环）
status               # JSON 状态
stop                 # 立即停车
```

完整协议、响应格式与调用示例见 [docs/API.md](docs/API.md)。

### VS Code

1. 安装扩展 **C# Dev Kit**（会自动带上 C# 扩展）。
2. `文件 → 打开文件夹`，选择本项目目录（不要只打开 .csproj）。
3. 首次加载时如果提示安装调试资产，选 **Yes**。
4. 按 **F5**，选择 `FishBot: agent + WASD`。
5. 在下方 **集成终端** 里点击一下，再按 W/A/S/D。

配置位于 `.vscode/launch.json`，另有 `agent only`、`status`、`selftest` 三个调试配置。

## 实车验证（2026-10-28）

| 项目 | 结果 |
|---|---|
| 握手与实体创建 | CREATE_CLIENT / CREATE / STATUS 正常 |
| odom 解析 | 实时输出 x / y / yaw |
| 前进 | 0.05 m/s × 0.6 s，实测 +2.5 cm |
| 左转 | 0.3 rad/s × 0.6 s，实测 +9.4° |
| 右转 | -0.3 rad/s × 0.6 s，实测 -6.7° |
| 后退 | -0.05 m/s × 0.6 s，实测 -2.9 cm |
| 合成链路 | CREATE → READ_DATA → DATA 全通过（0.05 m/s） |
| 编译 | 0 警告 0 错误；`--selftest` 6 项通过 |

## 单文件发布

```powershell
dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true
```

## 结构

```
Xrce/Frame.cs         消息头/子消息编解码
Xrce/Cdr.cs           CDR 读写、Twist、Odometry
Xrce/Agent.cs         UDP agent、会话、实体、心跳、DATA 下发
Tools/ControlServer.cs 本地 TCP 8898 控制口
Tools/Teleop.cs       WASD 遥控
Program.cs            入口与 --selftest
```

协议细节见 `docs/protocol_notes.md`。
