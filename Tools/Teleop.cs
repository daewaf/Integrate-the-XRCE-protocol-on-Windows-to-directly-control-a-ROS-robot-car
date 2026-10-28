using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;

namespace FishBotXrceAgent.Tools;

/// <summary>终端 WASD 遥控：轮询按键物理状态，不依赖 Windows 键盘连发。</summary>
public static class Teleop
{
    [DllImport("user32.dll")]
    private static extern short GetAsyncKeyState(int vKey);

    private const int VkW = 0x57, VkA = 0x41, VkS = 0x53, VkD = 0x44, VkSpace = 0x20, VkX = 0x58;
    private const double Speed = 0.05, Turn = 0.3;
    private const int RefreshMs = 100;

    private static bool Down(int vk) => (GetAsyncKeyState(vk) & 0x8000) != 0;

    public static async Task<int> RunAsync(int controlPort, CancellationToken token)
    {
        using var client = new TcpClient();
        await client.ConnectAsync(IPAddress.Loopback, controlPort, token);
        await using var stream = client.GetStream();
        using var writer = new StreamWriter(stream) { AutoFlush = true };

        Console.WriteLine("W 前进  S 后退  A 左转  D 右转  空格停  X 退出");
        Console.WriteLine("（按住方向键持续运动，松开立即停止）");

        long lastSend = 0;
        var wasMoving = false;
        try
        {
            while (!token.IsCancellationRequested)
            {
                if (Down(VkX)) break;

                double v, w;
                if (Down(VkSpace)) { v = 0; w = 0; }
                else if (Down(VkW)) { v = Speed; w = 0; }
                else if (Down(VkS)) { v = -Speed; w = 0; }
                else if (Down(VkA)) { v = 0; w = Turn; }
                else if (Down(VkD)) { v = 0; w = -Turn; }
                else { v = 0; w = 0; }

                var now = Environment.TickCount64;
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
            Console.WriteLine("\n已停车");
        }
        return 0;
    }
}
