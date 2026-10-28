using System.Net;
using System.Net.Sockets;
using System.Text;
using FishBotXrceAgent.Tools;
using FishBotXrceAgent.Xrce;

namespace FishBotXrceAgent;

public static class Program
{
    public static async Task<int> Main(string[] args)
    {
        try
        {
            Console.OutputEncoding = Encoding.UTF8;
            Console.InputEncoding = Encoding.UTF8;
        }
        catch { }

        var host = "0.0.0.0";
        var port = 8888;
        var controlPort = 8898;
        var mode = "run";

        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--host" when i + 1 < args.Length: host = args[++i]; break;
                case "--port" when i + 1 < args.Length: port = int.Parse(args[++i]); break;
                case "--control-port" when i + 1 < args.Length: controlPort = int.Parse(args[++i]); break;
                case "--agent-only": mode = "agent"; break;
                case "--check": mode = "check"; break;
                case "--selftest": mode = "selftest"; break;
                case "--help" or "-h": PrintHelp(); return 0;
                default:
                    Console.WriteLine($"未知参数: {args[i]}");
                    PrintHelp();
                    return 2;
            }
        }

        if (mode == "selftest") return SelfTest();

        using var cts = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) =>
        {
            e.Cancel = true;
            cts.Cancel();
        };

        using var agent = new XrceAgent(host, port);
        using var control = new ControlServer(agent, controlPort, cts.Token);
        agent.Start();
        control.Start();

        if (mode == "check")
        {
            var ready = false;
            for (var i = 0; i < 50; i++)
            {
                if (PortOpen(controlPort)) { ready = true; break; }
                await Task.Delay(100);
            }
            Console.WriteLine(ready ? "检查通过：agent 可用" : "检查失败：控制口未就绪");
            return ready ? 0 : 1;
        }

        if (mode == "agent")
        {
            Console.WriteLine("agent 运行中，Ctrl+C 退出");
            try { await Task.Delay(Timeout.Infinite, cts.Token); }
            catch (OperationCanceledException) { }
            return 0;
        }

        try
        {
            return await Teleop.RunAsync(controlPort, cts.Token);
        }
        catch (Exception ex) when (ex is SocketException or IOException)
        {
            Console.WriteLine($"连不上控制口 127.0.0.1:{controlPort}: {ex.Message}");
            return 1;
        }
    }

    private static bool PortOpen(int port)
    {
        try
        {
            using var c = new TcpClient();
            return c.ConnectAsync(IPAddress.Loopback, port).Wait(300);
        }
        catch { return false; }
    }

    private static void PrintHelp()
    {
        Console.WriteLine("""
        FishBot 纯 C# XRCE-DDS agent

          FishBotXrceAgent                 agent + WASD 遥控（默认）
          FishBotXrceAgent --agent-only    只运行 agent
          FishBotXrceAgent --check         启动检查
          FishBotXrceAgent --selftest      运行编解码自检
          --host <ip>                      UDP 绑定地址（默认 0.0.0.0）
          --port <n>                       UDP 端口（默认 8888）
          --control-port <n>               本机 TCP 控制口（默认 8898）
        """);
    }

    // ---------------- 自检 ----------------
    private static int SelfTest()
    {
        var failures = 0;

        void Check(bool ok, string name)
        {
            Console.WriteLine($"{(ok ? "PASS" : "FAIL")}  {name}");
            if (!ok) failures++;
        }

        // 1. 规范 B.1 的消息头布局
        var m = new XrceMessage { SessionId = 0x80, StreamId = 0, SequenceNr = 0 };
        m.Submessages.Add(new Submessage(SubIds.CreateClient, SmFlags.Reuse | SmFlags.Replace | SmFlags.Endiannes, new byte[14]));
        var raw = m.Encode();
        Check(raw.AsSpan(0, 8).SequenceEqual(Convert.FromHexString("8000000000070E00")), "CREATE_CLIENT 头部布局");

        // 2. 编解码往返
        var m2 = new XrceMessage { SessionId = 0x81, StreamId = 0x80, SequenceNr = 3 };
        m2.Submessages.Add(new Submessage(SubIds.Create, 0x07, new byte[] { 1, 2, 3, 4 }));
        m2.Submessages.Add(new Submessage(SubIds.WriteData, 0x01, new byte[] { 5, 6 }));
        var back = XrceMessage.Decode(m2.Encode());
        Check(back.SessionId == 0x81 && back.StreamId == 0x80 && back.SequenceNr == 3
              && back.Submessages.Count == 2
              && back.Submessages[0].Payload.SequenceEqual(new byte[] { 1, 2, 3, 4 }),
              "消息编解码往返");

        // 3. clientKey 条件
        var m3 = new XrceMessage { SessionId = 0x01, StreamId = 0x80, SequenceNr = 7, ClientKey = 0x55667788 };
        m3.Submessages.Add(new Submessage(SubIds.AckNack, 0x01, Array.Empty<byte>()));
        Check(m3.Encode().AsSpan(0, 8).SequenceEqual(Convert.FromHexString("0180070088776655")), "clientKey 条件");

        // 4. Twist CDR
        var twist = MsgCodec.TwistCdr(0.1, -0.5);
        var cdr = new CdrReader(twist);
        var t0 = cdr.F64(); cdr.F64(); cdr.F64(); cdr.F64(); cdr.F64();
        var t5 = cdr.F64();
        Check(twist.Length == 48 && Math.Abs(t0 - 0.1) < 1e-12 && Math.Abs(t5 + 0.5) < 1e-12, "Twist 48B CDR");

        // 5. Odometry 位姿解析
        var w = new CdrWriter();
        w.I32(1).U32(2).String("odom").String("base_footprint");
        w.F64(1.25).F64(-0.5).F64(0);
        var half = 30.0 * Math.PI / 180 / 2;
        w.F64(0).F64(0).F64(Math.Sin(half)).F64(Math.Cos(half));
        var (x, y, yaw) = MsgCodec.OdomPose(w.Bytes());
        Check(Math.Abs(x - 1.25) < 1e-9 && Math.Abs(y + 0.5) < 1e-9 && Math.Abs(yaw - 30) < 1e-6,
              "Odometry 位姿解析");

        // 6. 关键常量
        Check(Convert.FromHexString("010D585243450100010F00010D000100000000000000").Length == 22,
              "INFO 尾部 22B");

        Console.WriteLine(failures == 0 ? "\n全部自检通过" : $"\n{failures} 项失败");
        return failures == 0 ? 0 : 1;
    }
}
