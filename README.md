# 纯 Python XRCE-DDS Agent（Windows 直连 FishBot）

不依赖 WSL、不依赖 ROS2，直接在主控板和 Windows 之间实现 XRCE-DDS 协议转换。

## 当前状态（已在真实 FishBot 上验证）

| 模块 | 状态 |
|---|---|
| 消息帧 / 子消息编解码 | ✅ 单测通过 |
| CDR 与 Twist 序列化 | ✅ 单测通过 |
| CREATE_CLIENT 握手与 STATUS_AGENT | ✅ 真实主控板通过 |
| CREATE / DELETE → STATUS | ✅ 真实主控板通过 |
| INFO / HEARTBEAT / ACKNACK / TIMESTAMP_REPLY | ✅ 会话稳定，无重建 |
| `/cmd_vel` 下发（DATA） | ✅ 实车前后左右均生效 |
| `/odom` 解析 | ✅ x/y/yaw 实时解析 |

实测（2026-10-25）：前进 0.05 m/s × 0.4 s → odom x +1.6 cm；左转 0.3 rad/s × 0.4 s → yaw +6.5°；右转与后退同样生效，会话 DELETE 次数为 0。

## 快速开始（Windows，无需 WSL/ROS2）

```powershell
cd "C:\Users\kw188\Desktop\ros小车\xrce_windows_agent"
python start_fishbot.py          # 一键：后台 agent + 前台 WASD 遥控
```

`start_fishbot.py` 会打印本机 IP、后台启动 agent、等 8898 控制口就绪后进入 WASD，
退出（X / Ctrl+C）时自动关闭 agent。`python start_fishbot.py --check` 只做启动检查。

也可以分开手动运行：

```powershell
python -m unittest discover -s tests -v     # 7 项单测
python -m xrce.agent --host 0.0.0.0 --port 8888
```

另开一个终端遥控：

```powershell
python tools\teleop_wasd.py
```

或单条指令：

```powershell
python tools\send_cmd.py 0.05 0 0.4      # 前进约 2 cm
python tools\send_cmd.py 0 0.3 0.4       # 左转
python tools\send_cmd.py 0 -0.3 0.4      # 右转
python tools\send_cmd.py -0.05 0 0.4     # 后退
```

主控板配置：WiFi 与电脑同一网络；上位机 IP = 电脑当前 WLAN 地址（本次 `10.251.213.107`）；端口 8888。

## 关键协议要点（抓包确认）

1. `GET_INFO`（预会话，session 0x80）的 INFO 应答：`BaseObjectReply = 00 00`。
2. `GET_INFO`（会话内，session 0x81）的 INFO 应答：`BaseObjectReply = 00 01`
   —— 这一字节不对，客户端会在 4–20 秒后删除全部实体并重建。
3. `STATUS_AGENT` payload 固定 11 字节：`00 00 "XRCE" 01 00 01 0F 00`。
4. stream 0 的消息序列号恒为 0；可靠流用 0x80，STATUS 回在同一条流上。
5. `DELETE` 必须回 `STATUS OK`；`TIMESTAMP` 必须回 24 字节 `TIMESTAMP_REPLY`。
6. `/cmd_vel` 的 DataReader 为 `0x0006`，通过主动 `DATA`(0x09) 下发 48 字节 Twist CDR。

## 自测

```powershell
python tools\selftest_client.py 127.0.0.1 8888
```

期望输出：agent 解析出 `client_key`/`session_id`，并回 STATUS_AGENT（25 字节）。

## 文件

```
xrce/
  frame.py     消息头、子消息、ID 常量
  cdr.py       CDR 读写、Twist 序列化
  agent.py     UDP agent 主体
tools/
  selftest_client.py   本地握手指令
  decode_hex.py        解析任意十六进制报文
docs/
  protocol_notes.md    协议字段与字节示例
  omg_spec_extract.txt OMG 规范文本（输入资料）
tests/
  test_codec.py
```

## 已知风险

1. 规范 B.1 的 CREATE_CLIENT 长度（26）与字段合计（14/22）不一致，真实布局以抓包为准。
2. 若客户端使用可靠流（streamId 128），需要实现 HEARTBEAT/ACKNACK。
3. 部分 micro-ROS 客户端会发送 READ_DATA 轮询而非被动接收 DATA。
