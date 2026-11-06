using System.Globalization;
using System.Text.Json;
using System.Net;
using System.Net.Sockets;
using FishBotToolPanel.Tools;

// 使用临时回环端口模拟协议，不连接默认控制口或实际小车。
int passed = 0;
void Check(bool condition, string name)
{
    if (!condition) throw new InvalidOperationException($"FAIL {name}");
    Console.WriteLine($"PASS {name}");
    passed++;
}

async Task RunServerTest(Func<FishBotClient, Task> test, params (string Command, string? Response)[] exchanges)
{
    using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
    var listener = new TcpListener(IPAddress.Loopback, 0);
    listener.Start();
    int port = ((IPEndPoint)listener.LocalEndpoint).Port;
    var server = Task.Run(async () =>
    {
        foreach (var exchange in exchanges)
        {
            using var peer = await listener.AcceptTcpClientAsync(deadline.Token);
            using var stream = peer.GetStream();
            using var reader = new StreamReader(stream);
            using var writer = new StreamWriter(stream) { AutoFlush = true };
            string? line = await reader.ReadLineAsync(deadline.Token);
            Check(line == exchange.Command, $"协议命令 {exchange.Command}");
            if (exchange.Response is not null) await writer.WriteLineAsync(exchange.Response);
            else if (exchange.Command.StartsWith("forward", StringComparison.Ordinal))
            {
                // 不返回运动响应，让客户端超时或取消；随后接受独立停车连接。
                using var stopPeer = await listener.AcceptTcpClientAsync(deadline.Token);
                using var stopStream = stopPeer.GetStream();
                using var stopReader = new StreamReader(stopStream);
                using var stopWriter = new StreamWriter(stopStream) { AutoFlush = true };
                Check(await stopReader.ReadLineAsync(deadline.Token) == "stop", "独立连接发送停车");
                await stopWriter.WriteLineAsync("OK stopped");
            }
        }
    });
    try
    {
        await test(new FishBotClient(port, TimeSpan.FromMilliseconds(500)));
        await server.WaitAsync(deadline.Token);
    }
    finally
    {
        deadline.Cancel();
        listener.Stop();
        try { await server; } catch (OperationCanceledException) { }
    }
}

await RunServerTest(async client =>
{
    var result = await client.GetStatusAsync();
    Check(result.Ok && result.Status is not null, "解析状态 JSON");
}, ("status", "{\"ok\":true,\"state\":\"idle\",\"pose\":null}"));

CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("fr-FR");
await RunServerTest(async client => Check((await client.MoveAsync(0.25, 0.05)).Ok, "运动完成"), ("forward 0.25 0.05", "DONE forward 0.25m"));
await RunServerTest(async client => Check((await client.TurnAsync(-90, 0.3)).Ok, "转向完成"), ("turn -90 0.3", "DONE turn -90deg"));
await RunServerTest(async client => Check((await client.StopAsync()).Ok, "停车确认"), ("stop", "OK stopped"));
await RunServerTest(async client => Check(!(await client.MoveAsync(0.1)).Ok, "服务端 ERR 保留为失败"), ("forward 0.1 0.05", "ERR no odom"));
await RunServerTest(async client => Check(!(await client.GetStatusAsync()).Ok, "非法状态 JSON 返回失败"), ("status", "not-json"));
await RunServerTest(async client => Check(!(await client.StopAsync()).Ok, "服务器断连返回失败"), ("stop", null));
await RunServerTest(async client =>
{
    var result = await client.MoveAsync(0.1);
    Check(!result.Ok && result.StopConfirmed == true, "运动超时后停车确认");
}, ("forward 0.1 0.05", null));
await RunServerTest(async client =>
{
    using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(100));
    var result = await client.MoveAsync(0.1, 0.05, cts.Token);
    Check(!result.Ok && result.StopConfirmed == true, "运动取消后停车确认");
}, ("forward 0.1 0.05", null));

var unusedListener = new TcpListener(IPAddress.Loopback, 0);
unusedListener.Start();
int unusedPort = ((IPEndPoint)unusedListener.LocalEndpoint).Port;
unusedListener.Stop();
var disconnected = new FishBotClient(unusedPort, TimeSpan.FromMilliseconds(200));
Check(!(await disconnected.GetStatusAsync()).Ok, "连接失败可诊断");

foreach (double invalid in new[] { 0, double.NaN, double.PositiveInfinity, 11 })
{
    try
    {
        var result = await disconnected.MoveAsync(invalid);
        Check(!result.Ok && result.StopConfirmed is null, $"非法距离在联网前被拒绝 {invalid}");
    }
    catch (ArgumentException)
    {
        Check(true, $"拒绝非法距离 {invalid}");
    }
}
try
{
    var result = await disconnected.TurnAsync(181);
    Check(!result.Ok && result.StopConfirmed is null, "超出单次转向范围在联网前被拒绝");
}
catch (ArgumentException)
{
    Check(true, "拒绝超出单次转向范围");
}
foreach (double invalidSpeed in new[] { 0, -0.05, 0.21, double.NaN })
{
    var result = await disconnected.MoveAsync(0.1, invalidSpeed);
    Check(!result.Ok && result.StopConfirmed is null, $"非法线速度在联网前被拒绝 {invalidSpeed}");
}
foreach (double invalidSpeed in new[] { 0, -0.3, 1.1, double.PositiveInfinity })
{
    var result = await disconnected.TurnAsync(90, invalidSpeed);
    Check(!result.Ok && result.StopConfirmed is null, $"非法角速度在联网前被拒绝 {invalidSpeed}");
}
using (var cancelled = new CancellationTokenSource())
{
    cancelled.Cancel();
    var result = await disconnected.MoveAsync(0.1, cancellationToken: cancelled.Token);
    Check(!result.Ok && result.StopConfirmed is null, "预先取消不发送运动或停车命令");
}
ToolSet tools = FishBotTools.AllTools;
Check(tools.Tools.Count == 4, "仅注册四个小车工具");
Check(tools.Tools.Select(tool => tool.Name).Order().SequenceEqual(new[] { "fishbot_move", "fishbot_status", "fishbot_stop", "fishbot_turn" }), "工具名称保持一致");
using (JsonDocument definitions = JsonDocument.Parse(tools.GetToolDefinitionsJson()))
{
    Check(definitions.RootElement.GetArrayLength() == 4, "导出四个 JSON 工具定义");
}
foreach (IAgentTool tool in tools.Tools)
{
    using JsonDocument schema = JsonDocument.Parse(tool.ParametersSchema);
    Check(!schema.RootElement.GetProperty("properties").TryGetProperty("cancellationToken", out _), $"{tool.Name} 不将取消令牌暴露为JSON参数");
    using var cts = new CancellationTokenSource();
    cts.Cancel();
    JsonElement toolArguments = JsonSerializer.SerializeToElement(tool.Name switch
    {
        "fishbot_move" => (object)new { meters = 0.2 },
        "fishbot_turn" => new { degrees = 90 },
        _ => new { }
    });
    object? result = await tool.InvokeAsync(toolArguments, cts.Token);
    Check(result is FishBotResult { Ok: false, StopConfirmed: null }, $"{tool.Name} JSON调用及取消令牌传递");
}
IAgentTool moveTool = tools.Tools.Single(tool => tool.Name == "fishbot_move");
foreach (string invalidJson in new[] { "[]", "{}", "{\"meters\":0.2,\"unexpected\":1}" })
{
    try
    {
        using JsonDocument document = JsonDocument.Parse(invalidJson);
        await moveTool.InvokeAsync(document.RootElement);
        throw new InvalidOperationException("参数错误未被拒绝。");
    }
    catch (ArgumentException)
    {
        Check(true, $"JSON参数校验 {invalidJson}");
    }
}
Console.WriteLine($"完成：{passed} 项检查通过。");
