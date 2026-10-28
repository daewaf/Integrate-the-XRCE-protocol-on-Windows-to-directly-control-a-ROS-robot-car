using System.Net;
using System.Net.Sockets;
using FishBotXrceAgent.Xrce;

namespace FishBotXrceAgent.Tools;

/// <summary>本地 TCP 控制口：一行 "线速度 角速度 持续秒数"。</summary>
public sealed class ControlServer : IDisposable
{
    private readonly TcpListener _listener;
    private readonly XrceAgent _agent;
    private readonly CancellationTokenSource _cts;

    public int Port { get; }

    public ControlServer(XrceAgent agent, int port, CancellationToken outerToken)
    {
        _agent = agent;
        Port = port;
        _listener = new TcpListener(IPAddress.Loopback, port);
        _cts = CancellationTokenSource.CreateLinkedTokenSource(outerToken);
    }

    public void Start()
    {
        _listener.Start();
        _ = Task.Run(AcceptLoopAsync);
        Console.WriteLine($"[{DateTime.Now:HH:mm:ss}] control server listening on tcp 127.0.0.1:{Port}");
    }

    private async Task AcceptLoopAsync()
    {
        try
        {
            while (!_cts.IsCancellationRequested)
            {
                var client = await _listener.AcceptTcpClientAsync(_cts.Token);
                _ = Task.Run(() => HandleClientAsync(client, _cts.Token));
            }
        }
        catch (OperationCanceledException) { }
        catch (ObjectDisposedException) { }
    }

    private async Task HandleClientAsync(TcpClient client, CancellationToken token)
    {
        using (client)
        using (var stream = client.GetStream())
        using (var reader = new StreamReader(stream))
        using (var writer = new StreamWriter(stream) { AutoFlush = true })
        {
            while (!token.IsCancellationRequested)
            {
                var line = await reader.ReadLineAsync(token);
                if (line is null) return;
                line = line.Trim();
                if (line.Length == 0) continue;

                if (line.Equals("status", StringComparison.OrdinalIgnoreCase))
                {
                    await writer.WriteLineAsync(_agent.StatusText());
                    continue;
                }

                var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length < 2 ||
                    !double.TryParse(parts[0], out var v) ||
                    !double.TryParse(parts[1], out var w))
                {
                    await writer.WriteLineAsync("ERR usage: <linear> <angular> <seconds>");
                    continue;
                }
                var d = parts.Length > 2 && double.TryParse(parts[2], out var dd) ? dd : 0.5;

                if (Math.Abs(v) < 1e-9 && Math.Abs(w) < 1e-9) _agent.StopTarget();
                else _agent.SetTarget(v, w, d);
                Console.WriteLine($"[{DateTime.Now:HH:mm:ss}] CTRL {v} {w} {d}");
                await writer.WriteLineAsync($"OK {v} {w} {d}");
            }
        }
    }

    public void Dispose()
    {
        _cts.Cancel();
        _listener.Stop();
        _cts.Dispose();
    }
}
