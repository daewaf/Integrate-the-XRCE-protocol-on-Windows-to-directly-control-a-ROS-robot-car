using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;

namespace FishBotXrceAgent.Tools;

/// <summary>
/// 终端 WASD 遥控。双通道检测按键：
/// 1. GetAsyncKeyState 读取物理按键（按住/松开）
/// 2. Console.KeyAvailable 读取终端按键事件（兼容物理按键状态不可用的环境）
/// 1 秒内既没有按键事件、也没有物理按键按下时自动停车。
/// </summary>
public static class Teleop
{
    [DllImport("user32.dll")]
    private static extern short GetAsyncKeyState(int vKey);

    private const int VkW = 0x57, VkA = 0x41, VkS = 0x53, VkD = 0x44, VkSpace = 0x20, VkX = 0x58;
    private const double Speed = 0.05, Turn = 0.3;
    private const int RefreshMs = 100;
    private const int KeyTimeoutMs = 1000;

    private static bool Down(int vk) => (GetAsyncKeyState(vk) & 0x8000) != 0;

    public static async Task<int> RunAsync(int controlPort, CancellationToken token)
    {
        using var client = new TcpClient();
        await client.ConnectAsync(IPAddress.Loopback, controlPort, token);
        await using var stream = client.GetStream();
        using var writer = new StreamWriter(stream) { AutoFlush = true };

        Console.WriteLine("W 前进  S 后退  A 左转  D 右转  空格停  X 退出");
        Console.WriteLine("（按住方向键持续运动，松开约 1 秒内停止）");
        Console.WriteLine("（按键时会打印 [KEY]，便于确认终端是否收到按键）");

        double v = 0, w = 0;
        long lastSend = 0;
        long lastKeyMs = Environment.TickCount64;
        var wasMoving = false;
        var startMs = Environment.TickCount64;
        var lastLoggedChar = '\0';
        long lastLogMs = 0;
        var lastPhysicalDir = '\0';

        try
        {
            while (!token.IsCancellationRequested)
            {
                var now = Environment.TickCount64;

                // 通道 2：终端按键事件
                try
                {
                    while (Console.KeyAvailable)
                    {
                        var ch = char.ToLower(Console.ReadKey(true).KeyChar);
                        if (ch != lastLoggedChar || now - lastLogMs > 1000)
                        {
                            Console.WriteLine($"[KEY] {ch}");
                            lastLoggedChar = ch;
                            lastLogMs = now;
                        }
                        lastKeyMs = now;
                        switch (ch)
                        {
                            case 'w': v = Speed; w = 0; break;
                            case 's': v = -Speed; w = 0; break;
                            case 'a': v = 0; w = Turn; break;
                            case 'd': v = 0; w = -Turn; break;
                            case ' ': v = 0; w = 0; break;
                            case 'x':
                                if (now - startMs > 800) return await FinishAsync(writer);
                                break;
                        }
                    }
                }
                catch (InvalidOperationException)
                {
                    // 没有控制台（隐藏运行）时忽略
                }

                // 通道 1：物理按键状态
                var physical = false;
                var physicalDir = '\0';
                if (Down(VkW)) { v = Speed; w = 0; physical = true; }
                else if (Down(VkS)) { v = -Speed; w = 0; physical = true; }
                else if (Down(VkA)) { v = 0; w = Turn; physical = true; }
                else if (Down(VkD)) { v = 0; w = -Turn; physical = true; }
                if (Down(VkW)) physicalDir = 'w';
                else if (Down(VkS)) physicalDir = 's';
                else if (Down(VkA)) physicalDir = 'a';
                else if (Down(VkD)) physicalDir = 'd';
                if (physicalDir != lastPhysicalDir)
                {
                    Console.WriteLine($"[KEY] {(physicalDir == '\0' ? "-" : physicalDir.ToString())} (physical)");
                    lastPhysicalDir = physicalDir;
                }
                if (Down(VkSpace)) { v = 0; w = 0; }
                if (now - startMs > 800 && Down(VkX))
                    return await FinishAsync(writer);

                // 两个通道都没有活动 -> 自动归零
                if (!physical && now - lastKeyMs > KeyTimeoutMs)
                {
                    v = 0;
                    w = 0;
                }

                var moving = v != 0 || w != 0;
                if (moving)
                {
                    if (now - lastSend >= RefreshMs)
                    {
                        await writer.WriteLineAsync($"{v} {w} 0.3");
                        lastSend = now;
                    }
                }
                else if (wasMoving)
                {
                    await writer.WriteLineAsync("0 0 0.05");
                }
                wasMoving = moving;
                await Task.Delay(20, token);
            }
        }
        catch (OperationCanceledException) { }
        finally
        {
            try { await writer.WriteLineAsync("0 0 0.05"); } catch { }
            Console.WriteLine("\n遥控已结束，程序退出（agent 已关闭）");
        }
        return 0;
    }

    private static async Task<int> FinishAsync(StreamWriter writer)
    {
        try { await writer.WriteLineAsync("0 0 0.05"); } catch { }
        Console.WriteLine("\n遥控已结束，程序退出（agent 已关闭）");
        return 0;
    }
}
