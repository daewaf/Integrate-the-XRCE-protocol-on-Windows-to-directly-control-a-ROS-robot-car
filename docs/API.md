# FishBot 控制接口文档

版本：1.0（2026-10-30）
适用：`xrce_csharp_agent`（纯 C# XRCE-DDS agent）

## 1. 连接方式

| 项目 | 值 |
|---|---|
| 协议 | TCP |
| 地址 | `127.0.0.1`（本机） |
| 端口 | `8898` |
| 编码 | UTF-8 |
| 格式 | 一行一条命令，以 `\n` 结尾 |
| 响应 | 一行，以 `\n` 结尾 |

一条 TCP 连接可以连续发送多条命令。`forward` / `turn` 是**阻塞式**的：
命令返回时运动已经结束（或失败），调用方不需要轮询。

前提：agent 已启动，且小车已连接。

## 2. 命令一览

| 命令 | 作用 | 阻塞 |
|---|---|---|
| `forward <米> [速度]` | 前进/后退固定距离（闭环） | 是 |
| `turn <角度> [角速度]` | 原地旋转固定角度（闭环） | 是 |
| `speed <线速度> <角速度>` | 设置后续命令的默认速度 | 否 |
| `stop` | 立即停车并取消当前动作 | 否 |
| `status` | 查询状态（JSON） | 否 |
| `status text` | 查询状态（旧版文本） | 否 |
| `<线速度> <角速度> <秒>` | 开环速度控制（兼容旧接口） | 否 |

## 3. 闭环运动命令

### 3.1 `forward <米> [速度]`

按里程计（odom）位移闭环前进或后退。

| 参数 | 类型 | 默认 | 范围 | 说明 |
|---|---|---|---|---|
| 米 | float | — | -10 ~ 10 | 正数前进，负数后退 |
| 速度 | float | 0.05 | 0.02 ~ 0.20 | m/s |

示例：

```text
forward 0.50            → 前进 0.5 m（默认 0.05 m/s）
forward -0.20 0.10      → 后退 0.2 m（0.10 m/s）
```

成功响应：

```text
DONE forward 0.5m traveled=0.497m pose=0.497,0.002,0.3
```

字段：

| 字段 | 含义 |
|---|---|
| `forward 0.5m` | 请求值 |
| `traveled=0.497m` | 实际位移（沿起始朝向投影） |
| `pose=x,y,yaw` | 结束位姿（米、米、度） |

停止条件：位移误差 ≤ **5 mm**，或超时。

### 3.2 `turn <角度> [角速度]`

按 odom 的 yaw 闭环原地旋转。

| 参数 | 类型 | 默认 | 范围 | 说明 |
|---|---|---|---|---|
| 角度 | float | — | -720 ~ 720 | 正数左转，负数右转，单位度 |
| 角速度 | float | 0.3 | 0.1 ~ 1.0 | rad/s |

示例：

```text
turn 90                 → 左转 90°
turn -45 0.5            → 右转 45°（0.5 rad/s）
```

成功响应：

```text
DONE turn 90deg yaw=89.2 pose=0.010,0.000,89.2
```

停止条件：角度误差 ≤ **1.5°**，或超时。

### 3.3 `speed <线速度> <角速度>`

设置后续 `forward` / `turn` 未显式指定速度时的默认值。

| 参数 | 范围 | 说明 |
|---|---|---|
| 线速度 | 0.02 ~ 0.20 | m/s，自动取绝对值 |
| 角速度 | 0.1 ~ 1.0 | rad/s，自动取绝对值 |

响应：`OK speed 0.04 0.5`

### 3.4 `stop`

取消正在执行的 `forward` / `turn`，并立即输出零速度。

响应：`OK stopped`

### 3.5 `<线速度> <角速度> <秒>`

兼容旧接口的开环控制：按固定速度运行指定秒数。

```text
0.05 0 0.5      → 前进 0.05 m/s，持续 0.5 s
0 0.3 0.5       → 左转 0.3 rad/s，持续 0.5 s
0 0 0.05        → 立即停车
```

响应：`OK 0.05 0 0.5`

注意：闭环动作执行期间，开环命令返回 `ERR busy`。

## 4. 状态查询 `status`

返回一行 JSON：

```json
{
  "ok": true,
  "state": "idle",
  "pose": {"x": 0.125, "y": -0.030, "yaw": 12.4},
  "odom_age_ms": 35,
  "speed": {"linear": 0.05, "angular": 0.3},
  "sessions": 1,
  "active": 1,
  "cmd_vel_reader": true
}
```

| 字段 | 类型 | 含义 |
|---|---|---|
| `ok` | bool | 固定 true |
| `state` | string | `idle` / `forward` / `turn` |
| `pose` | object/null | 当前 odom 位姿；无数据时 null |
| `pose.x/y` | float | 米 |
| `pose.yaw` | float | 度 |
| `odom_age_ms` | int | 距上一帧 odom 的毫秒数；-1 表示从未收到 |
| `speed` | object | 当前默认速度 |
| `sessions` | int | 已知会话数 |
| `active` | int | 5 秒内有数据的会话数 |
| `cmd_vel_reader` | bool | 是否存在 cmd_vel 订阅端点 |

判断小车是否可用：

```text
sessions ≥ 1
active ≥ 1
cmd_vel_reader = true
odom_age_ms 在 0 ~ 200 之间
```

## 5. 错误响应

| 响应 | 含义 | 处理 |
|---|---|---|
| `ERR busy` | 已有闭环动作在执行 | 等当前动作完成，或先 `stop` |
| `ERR no odom` | 2 秒内没有有效 odom | 检查小车连接/上位机 IP |
| `ERR timeout` | 动作超时 | 检查地面/打滑，重新执行 |
| `ERR stopped` | 动作被 `stop` 取消 | 正常现象 |
| `ERR usage: ...` | 参数格式错误 | 检查命令格式 |
| `ERR distance must be non-zero` | forward 距离为 0 | 传非零距离 |
| `ERR angle must be non-zero` | turn 角度为 0 | 传非零角度 |

超时时间 = `距离/速度 + 5 秒`（转向同理）。

## 6. 调用示例

### Python

```python
import socket

def send(cmd: str) -> str:
    with socket.create_connection(("127.0.0.1", 8898), timeout=15) as s:
        s.sendall((cmd + "\n").encode())
        return s.makefile().readline().strip()

print(send("speed 0.05 0.3"))
print(send("forward 0.50"))
print(send("turn 90"))
print(send("status"))
```

### C#

```csharp
using System.Net.Sockets;

static string Send(string cmd)
{
    using var client = new TcpClient("127.0.0.1", 8898);
    using var stream = client.GetStream();
    using var writer = new StreamWriter(stream) { AutoFlush = true };
    using var reader = new StreamReader(stream);
    writer.WriteLine(cmd);
    return reader.ReadLine() ?? "";
}

Console.WriteLine(Send("forward 0.50"));
Console.WriteLine(Send("turn 90"));
```

### PowerShell

```powershell
$c = New-Object System.Net.Sockets.TcpClient('127.0.0.1',8898)
$s = $c.GetStream()
$b = [Text.Encoding]::ASCII.GetBytes("forward 0.50`n")
$s.Write($b,0,$b.Length)
$buf = New-Object byte[] 512
$n = $s.Read($buf,0,512)
[Text.Encoding]::ASCII.GetString($buf,0,$n)
$c.Close()
```

## 7. 精度与限制

- 位置精度：约 **±5 mm**（闭环停止条件），实际受轮子打滑、地面影响。
- 角度精度：约 **±1.5°**（闭环停止条件）。
- 里程计为纯编码器推算，长时间/长距离会累积漂移。
- 没有雷达，不做避障；调用方需确保行驶区域安全。
- 同一时间只允许一个闭环动作；并发请求返回 `ERR busy`。
- 控制口只绑 `127.0.0.1`，其他机器不能直接访问。

## 8. 兼容性

旧接口 `<线速度> <角速度> <秒>` 继续可用；新增的 `forward` / `turn` / `speed` / `stop` / `status` 不破坏旧调用。
