# FishBot 独立四工具控制台

独立 WPF / .NET 8 项目。仅包含四个小车工具及其调用界面；XRCE agent 作为另一个进程单独运行。
不依赖 XingqiaoSdkTest 项目、模型服务或 API Key，无第三方 NuGet 包。

## 使用

1. 双击 `启动XRCE.cmd`，保持该终端运行。此脚本运行相邻的 `xrce_csharp_agent` 项目；如果已启动 agent，不要重复运行。
2. 双击 `启动界面.cmd`，或运行 `bin/Release/net8.0-windows/FishBotToolPanel.exe`。
3. 点击“查询状态”，查看 agent 连通性、小车连接、里程计位姿和当前运动状态。
4. 填写距离与速度后点击“执行位移”，或填写转角与角速度后点击“执行转向”。运动期间仍可查询状态、点击“立即停车”。

默认控制端点为 `127.0.0.1:8898`。界面不启动、不退出 XRCE agent。
每个动作等待 agent 返回完成或失败；工具在超时、取消或通信异常时另建连接尝试停车。
关闭窗口时取消本窗口正在等待的运动，并等待停车尝试完成，最长增加约两秒。
停车确认表示 agent 已接受停车请求，不是传感器测得的静止状态。

## 四个工具

| 工具名 | 参数 | 功能 |
|---|---|---|
| `fishbot_status` | 无 | 查询连接、位姿及运动状态 |
| `fishbot_stop` | 无 | 停车并取消当前闭环动作 |
| `fishbot_move` | `meters`、`speed=0.05` | 正距离前进、负距离后退，范围 ±10 米、非零；速度 0.02–0.20 米/秒 |
| `fishbot_turn` | `degrees`、`angularSpeed=0.3` | 正角度左转、负角度右转，范围 ±180 度、非零；角速度 0.1–1.0 弧度/秒 |

单次转角限制对应当前 XRCE 实现；更大转角应拆成多个动作。小车本身没有避障功能。
查询结果 `Ok=true` 仅表示协议调用成功；`active`、`cmd_vel_reader`、`odom_age_ms` 才用于判断小车是否就绪。
界面的连接、位姿信息为最近一次查询快照，不会自动刷新。

## 工具格式

`Tools/` 保留参考目录中的 `IAgentTool` 属性及 `InvokeAsync(JsonElement, CancellationToken)` 契约，
并采用同样的 `AgentTool(Delegate, name)`、`ToolSet`、`FishBotTools.AllTools`、`Description` 元数据和 JSON Schema 方式组织。
界面自身也通过此工具接口调用，不绕过工具层。

独立版本的 `AgentTool` 仅支持这四个工具所需的 double 参数和 `Task<FishBotResult>` 返回类型。
为避免绑定模型 SDK，没有复制原项目的 OpenAI 专用转换方法；`GetToolDefinitionsJson()` 可导出名称、说明和参数 Schema。
日后接入原模型项目时，可直接沿用其 `AgentTool` / `ToolSet` 实现并调整命名空间。

```csharp
using System.Text.Json;
using FishBotToolPanel.Tools;

ToolSet tools = FishBotTools.AllTools;
IAgentTool status = tools.Tools.Single(tool => tool.Name == "fishbot_status");
using JsonDocument arguments = JsonDocument.Parse("{}");
object? result = await status.InvokeAsync(arguments.RootElement, CancellationToken.None);
```

`FishBotResult` 包含 `Ok`、`Response`、`Error`、`Status`、`StopConfirmed`。
无效参数、连接错误和服务端失败返回明确结果；JSON 形状错误或缺少必填参数由工具适配层抛出参数异常，界面捕获显示。

## 构建与测试

需要 .NET 8 SDK；已构建程序需要 .NET 8 Windows Desktop Runtime。

```powershell
dotnet build .\FishBotToolPanel.csproj -c Release
dotnet run --project .\tests\FishBotToolPanel.Tests.csproj -c Release
```

离线测试使用临时回环端口，检查 TCP 协议、参数校验、错误处理、取消/超时补偿停车、工具定义和 JSON 调用，不连接默认控制口或实车。
项目采用内置 Windows 控件；规范资料位于 `docs/csharp-wpf-standard/`。使用 .NET 8 是为了直接适配当前已安装的 SDK 与桌面运行时。
