using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Text;

namespace FishBotXrceAgent.Xrce;

public sealed record XrceObject((byte, byte) Id, byte Kind, string? Topic);

public sealed class ClientSession
{
    public required EndPoint Remote { get; init; }
    public required string Key { get; init; }
    public uint ClientKey { get; set; }
    public byte SessionId { get; set; }
    public long LastRxMs { get; set; } = Environment.TickCount64;
    public Dictionary<(byte, byte), XrceObject> Objects { get; } = new();
    public object ObjectsLock { get; } = new();
    private readonly Dictionary<byte, ushort> _seqOut = new();
    private readonly object _seqLock = new();

    public ushort NextSeq(byte stream)
    {
        lock (_seqLock)
        {
            var n = _seqOut.TryGetValue(stream, out var v) ? v : (ushort)0;
            _seqOut[stream] = (ushort)((n + 1) & 0xFFFF);
            return n;
        }
    }

    public ushort LastSeq(byte stream)
    {
        lock (_seqLock)
        {
            if (!_seqOut.TryGetValue(stream, out var v) || v == 0) return 0;
            return (ushort)(v - 1);
        }
    }

    public (byte, byte)? FindReader(string needle)
    {
        lock (ObjectsLock)
        {
            foreach (var o in Objects.Values)
            {
                if (o.Kind == ObjectKinds.DataReader && o.Topic is not null && o.Topic.Contains(needle))
                    return o.Id;
            }
        }
        return null;
    }

    public (byte, byte)? FindAnyReader()
    {
        lock (ObjectsLock)
        {
            foreach (var o in Objects.Values)
            {
                if (o.Kind == ObjectKinds.DataReader && o.Id != XrceAgent.ServiceObject)
                    return o.Id;
            }
        }
        return null;
    }
}

/// <summary>FishBot 的最小 XRCE agent。</summary>
public sealed class XrceAgent : IDisposable
{
    public static readonly (byte, byte) ServiceObject = (0x00, 0x08);

    // 抓包确认的会话内 GET_INFO 应答尾部（22 字节）
    private static readonly byte[] InfoTail = Convert.FromHexString(
        "010D585243450100010F00010D000100000000000000");

    private static readonly Dictionary<(byte, byte), XrceObject> DefaultObjects = new()
    {
        [(0x00, 0x01)] = new((0x00, 0x01), ObjectKinds.Participant, null),
        [(0x00, 0x02)] = new((0x00, 0x02), ObjectKinds.Topic, "odom"),
        [(0x00, 0x03)] = new((0x00, 0x03), ObjectKinds.Publisher, null),
        [(0x00, 0x05)] = new((0x00, 0x05), ObjectKinds.DataWriter, "odom"),
        [(0x00, 0x12)] = new((0x00, 0x12), ObjectKinds.Topic, "imu"),
        [(0x00, 0x13)] = new((0x00, 0x13), ObjectKinds.Publisher, null),
        [(0x00, 0x15)] = new((0x00, 0x15), ObjectKinds.DataWriter, "imu"),
        [(0x00, 0x22)] = new((0x00, 0x22), ObjectKinds.Topic, "cmd_vel"),
        [(0x00, 0x04)] = new((0x00, 0x04), ObjectKinds.Subscriber, null),
        [(0x00, 0x06)] = new((0x00, 0x06), ObjectKinds.DataReader, "cmd_vel"),
        [(ServiceObject)] = new((0x00, 0x08), 0x08, null),
    };

    private readonly Socket _udp;
    private readonly ConcurrentDictionary<string, ClientSession> _sessions = new();
    private readonly CancellationTokenSource _cts = new();
    private readonly object _sendLock = new();
    private readonly object _twistLock = new();
    private readonly byte[] _rxBuffer = new byte[65535];
    private (double V, double W) _twistTarget;
    private long _twistDeadlineMs;
    private int _dataRequestId;

    public int UdpPort { get; }
    public bool Verbose { get; set; } = true;
    public CancellationToken Token => _cts.Token;

    public XrceAgent(string host = "0.0.0.0", int port = 8888)
    {
        UdpPort = port;
        _udp = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
        _udp.Bind(new IPEndPoint(IPAddress.Parse(host), port));
        _udp.ReceiveBufferSize = 1 << 20;
    }

    public void Start()
    {
        _ = Task.Run(ReceiveLoopAsync);
        _ = Task.Run(HeartbeatLoopAsync);
        _ = Task.Run(TwistLoopAsync);
        Log($"agent listening on udp 0.0.0.0:{UdpPort}");
    }

    public void Log(string text)
    {
        if (Verbose) Console.WriteLine($"[{DateTime.Now:HH:mm:ss}] {text}");
    }

    public void Stop() => _cts.Cancel();

    // ---------------- 收发 ----------------
    private async Task ReceiveLoopAsync()
    {
        var remote = (EndPoint)new IPEndPoint(IPAddress.Any, 0);
        while (!_cts.IsCancellationRequested)
        {
            try
            {
                var n = _udp.ReceiveFrom(_rxBuffer, ref remote);
                if (n <= 0) continue;
                var data = _rxBuffer.AsSpan(0, n).ToArray();
                var from = (IPEndPoint)remote;
                Handle(data, from);
            }
            catch (SocketException) when (_cts.IsCancellationRequested)
            {
                break;
            }
            catch (SocketException ex) when (ex.SocketErrorCode == SocketError.ConnectionReset)
            {
                // 合成客户端关闭后 Windows 会回 ICMP 端口不可达，忽略即可
                continue;
            }
            catch (Exception ex)
            {
                Log($"处理失败: {ex.Message}");
            }
        }
        await Task.CompletedTask;
    }

    private void Send(ClientSession session, byte streamId, params Submessage[] subs)
    {
        var seq = streamId == StreamIds.None ? (ushort)0 : session.NextSeq(streamId);
        var msg = new XrceMessage
        {
            SessionId = session.SessionId,
            StreamId = streamId,
            SequenceNr = seq,
            ClientKey = session.ClientKey,
        };
        msg.Submessages.AddRange(subs);
        var raw = msg.Encode();
        lock (_sendLock)
        {
            try
            {
                _udp.SendTo(raw, session.Remote);
            }
            catch (SocketException)
            {
                // 客户端可能已关闭；保留会话，等待它重新连接
                return;
            }
        }
        Log($"TX stream={streamId} seq={seq} {raw.Length}B");
    }

    private void Handle(byte[] data, IPEndPoint from)
    {
        var msg = XrceMessage.Decode(data);
        var names = string.Join(",", msg.Submessages.Select(s => SubIds.Name(s.Id)));
        Log($"RX {from} session=0x{msg.SessionId:X2} stream=0x{msg.StreamId:X2} seq={msg.SequenceNr} subs=[{names}]");

        var key = from.ToString();
        _sessions.TryGetValue(key, out var session);

        // 客户端在 agent 重启后会沿用旧 session，这里自动接管
        if (session is null && msg.SessionId >= 0x81)
        {
            session = new ClientSession { Remote = from, Key = key, SessionId = msg.SessionId, ClientKey = 0 };
            foreach (var pair in DefaultObjects) session.Objects[pair.Key] = pair.Value;
            _sessions[key] = session;
            Log($"  自动接管已有会话 session=0x{msg.SessionId:X2}");
        }
        if (session is not null) session.LastRxMs = Environment.TickCount64;

        foreach (var sm in msg.Submessages)
        {
            switch (sm.Id)
            {
                case SubIds.CreateClient:
                    session = OnCreateClient(from, msg, sm);
                    break;
                case SubIds.GetInfo:
                    OnGetInfo(from, msg, sm);
                    break;
                case SubIds.Create when session is not null:
                    OnCreate(session, msg.StreamId, sm);
                    break;
                case SubIds.Delete when session is not null:
                    OnDelete(session, msg.StreamId, sm);
                    break;
                case SubIds.Heartbeat when session is not null:
                    SendAckNack(session, msg.SequenceNr);
                    break;
                case SubIds.Timestamp when session is not null:
                    OnTimestamp(session, sm);
                    break;
                case SubIds.ReadData when session is not null:
                    OnReadData(session, sm);
                    break;
                case SubIds.WriteData when session is not null:
                    OnWriteData(session, sm);
                    break;
            }
        }

        if (session is not null && msg.StreamId >= 0x80 &&
            msg.Submessages.All(s => s.Id != SubIds.AckNack))
        {
            SendAckNack(session, msg.SequenceNr);
        }
    }

    // ---------------- 握手 ----------------
    private ClientSession OnCreateClient(IPEndPoint from, XrceMessage msg, Submessage sm)
    {
        var p = sm.Payload;
        uint clientKey = 0;
        byte requested = 0x81;
        if (p.Length >= 14 && p[0] == (byte)'X')
        {
            var keyOff = p.Length >= 22 ? 16 : 8;
            if (p.Length >= keyOff + 5)
            {
                clientKey = BitConverter.ToUInt32(p, keyOff);
                requested = p[keyOff + 4];
            }
        }

        var sessionId = requested >= 0x80 ? requested : (byte)0x81;
        var session = new ClientSession
        {
            Remote = from,
            Key = from.ToString(),
            ClientKey = clientKey,
            SessionId = sessionId,
        };
        _sessions[session.Key] = session;
        Log($"  新会话 client_key=0x{clientKey:X8} session=0x{sessionId:X2}");

        var payload = new List<byte> { 0x00, 0x00 };
        payload.AddRange(Encoding.ASCII.GetBytes("XRCE"));
        payload.AddRange(new byte[] { 0x01, 0x00, 0x01, 0x0F, 0x00 });
        Send(session, StreamIds.None, new Submessage(SubIds.StatusAgent, SmFlags.Endiannes, payload.ToArray()));
        return session;
    }

    private void OnGetInfo(IPEndPoint from, XrceMessage msg, Submessage sm)
    {
        var p = sm.Payload;
        if (p.Length < 4) return;

        // 客户端发出 GET_INFO 后才进入接收等待，过早回复会被丢弃
        Thread.Sleep(5);

        var impl = msg.SessionId == 0x80 ? new byte[] { 0x00, 0x00 } : new byte[] { 0x00, 0x01 };
        var payload = new List<byte>();
        payload.AddRange(p.AsSpan(0, 4).ToArray());
        payload.AddRange(impl);
        payload.AddRange(InfoTail);

        var temp = new ClientSession
        {
            Remote = from,
            Key = from.ToString(),
            SessionId = msg.SessionId,
            ClientKey = 0,
        };
        Send(temp, StreamIds.None, new Submessage(SubIds.Info, SmFlags.Endiannes, payload.ToArray()));
    }

    private void SendAckNack(ClientSession session, ushort seq)
    {
        var payload = new byte[5];
        BitConverter.GetBytes((ushort)((seq + 1) & 0xFFFF)).CopyTo(payload, 0);
        payload[4] = StreamIds.Reliable;
        Send(session, StreamIds.None, new Submessage(SubIds.AckNack, SmFlags.Endiannes, payload));
    }

    private async Task HeartbeatLoopAsync()
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(2));
        try
        {
            while (await timer.WaitForNextTickAsync(_cts.Token))
            {
                foreach (var session in _sessions.Values)
                {
                    if (Environment.TickCount64 - session.LastRxMs > 10_000) continue;
                    var last = session.LastSeq(StreamIds.Reliable);
                    var payload = new byte[5];
                    BitConverter.GetBytes(last).CopyTo(payload, 0);
                    BitConverter.GetBytes(last).CopyTo(payload, 2);
                    payload[4] = StreamIds.Reliable;
                    try { Send(session, StreamIds.None, new Submessage(SubIds.Heartbeat, SmFlags.Endiannes, payload)); }
                    catch { /* 客户端可能已断开 */ }
                }
            }
        }
        catch (OperationCanceledException) { }
    }

    private void OnTimestamp(ClientSession session, Submessage sm)
    {
        var now = DateTimeOffset.UtcNow;
        var stamp = new byte[8];
        BitConverter.GetBytes((int)now.ToUnixTimeSeconds()).CopyTo(stamp, 0);
        BitConverter.GetBytes((uint)(now.Ticks % TimeSpan.TicksPerSecond * 100)).CopyTo(stamp, 4);
        var payload = stamp.Concat(stamp).Concat(sm.Payload).ToArray();
        Send(session, StreamIds.None, new Submessage(SubIds.TimestampReply, SmFlags.Endiannes, payload));
    }

    // ---------------- 实体 ----------------
    private void OnCreate(ClientSession session, byte streamId, Submessage sm)
    {
        var p = sm.Payload;
        if (p.Length < 5) return;
        var requestId = (p[0], p[1]);
        var objectId = (p[2], p[3]);
        var kind = p[4];
        var topic = GuessTopic(p);

        if (kind is ObjectKinds.DataReader or ObjectKinds.DataWriter && p.Length >= 14)
        {
            var refId = (p[12], p[13]);
            lock (session.ObjectsLock)
            {
                if (session.Objects.TryGetValue(refId, out var topicObj))
                    topic = topicObj.Topic;
            }
        }

        lock (session.ObjectsLock)
        {
            session.Objects[objectId] = new XrceObject(objectId, kind, topic);
        }
        Log($"  CREATE req={requestId} obj=0x{objectId.Item1:X2}0x{objectId.Item2:X2} kind=0x{kind:X2} topic={topic ?? "-"}");

        var status = new byte[] { requestId.Item1, requestId.Item2, objectId.Item1, objectId.Item2, 0x00, 0x00 };
        Send(session, streamId, new Submessage(SubIds.Status, SmFlags.Endiannes, status));

        var last = session.LastSeq(StreamIds.Reliable);
        var hb = new byte[5];
        BitConverter.GetBytes(last).CopyTo(hb, 0);
        BitConverter.GetBytes(last).CopyTo(hb, 2);
        hb[4] = StreamIds.Reliable;
        Send(session, StreamIds.None, new Submessage(SubIds.Heartbeat, SmFlags.Endiannes, hb));
    }

    private void OnDelete(ClientSession session, byte streamId, Submessage sm)
    {
        var p = sm.Payload;
        if (p.Length < 4) return;
        var status = new byte[] { p[0], p[1], p[2], p[3], 0x00, 0x00 };
        Log($"  DELETE obj=0x{p[2]:X2}0x{p[3]:X2} -> STATUS OK");
        Send(session, streamId, new Submessage(SubIds.Status, SmFlags.Endiannes, status));
    }

    private static string? GuessTopic(byte[] p)
    {
        foreach (var needle in new[] { "cmd_vel", "odom", "imu" })
        {
            if (Encoding.ASCII.GetString(p).Contains(needle)) return needle;
        }
        return null;
    }

    private void OnReadData(ClientSession session, Submessage sm)
    {
        var p = sm.Payload;
        if (p.Length < 4) return;
        var id = (p[2], p[3]);
        if (id == ServiceObject) return;
        lock (session.ObjectsLock)
        {
            if (!session.Objects.ContainsKey(id))
            {
                session.Objects[id] = new XrceObject(id, ObjectKinds.DataReader, null);
                Log($"  学习到 DataReader 0x{id.Item1:X2}0x{id.Item2:X2}");
            }
        }
    }

    private void OnWriteData(ClientSession session, Submessage sm)
    {
        var p = sm.Payload;
        if (p.Length < 4) return;
        var objectId = (p[2], p[3]);
        var data = p.AsSpan(4).ToArray();
        XrceObject? obj;
        lock (session.ObjectsLock)
        {
            session.Objects.TryGetValue(objectId, out obj);
            if (obj is null && Encoding.ASCII.GetString(data[..Math.Min(48, data.Length)]).Contains("odom"))
            {
                obj = new XrceObject(objectId, ObjectKinds.DataWriter, "odom");
                session.Objects[objectId] = obj;
            }
        }
        if (obj?.Topic is not null && obj.Topic.Contains("odom"))
        {
            try
            {
                var (x, y, yaw) = MsgCodec.OdomPose(data);
                Log($"    odom x={x:0.000} y={y:0.000} yaw={yaw:0.0}deg");
            }
            catch (Exception ex)
            {
                Log($"    odom 解析失败: {ex.Message}");
            }
        }
    }

    // ---------------- 控制 ----------------
    public void SetTarget(double v, double w, double durationSeconds)
    {
        lock (_twistLock)
        {
            _twistTarget = (v, w);
            _twistDeadlineMs = Environment.TickCount64 + (long)(Math.Max(durationSeconds, 0.05) * 1000);
        }
    }

    public void StopTarget()
    {
        lock (_twistLock)
        {
            _twistTarget = (0, 0);
            _twistDeadlineMs = 0;
        }
    }

    private async Task TwistLoopAsync()
    {
        using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(50));
        try
        {
            while (await timer.WaitForNextTickAsync(_cts.Token))
            {
                (double v, double w) target;
                lock (_twistLock)
                {
                    target = Environment.TickCount64 > _twistDeadlineMs ? (0, 0) : _twistTarget;
                }
                SendTwist(target.v, target.w);
            }
        }
        catch (OperationCanceledException) { }
    }

    public void SendTwist(double linearX, double angularZ)
    {
        var twist = MsgCodec.TwistCdr(linearX, angularZ);
        foreach (var session in _sessions.Values)
        {
            if (Environment.TickCount64 - session.LastRxMs > 10_000) continue;
            var reader = session.FindReader("cmd_vel") ?? session.FindAnyReader();
            if (reader is null) continue;
            var reqId = (ushort)(Interlocked.Increment(ref _dataRequestId) & 0xFFFF);
            var body = new byte[4 + twist.Length];
            BitConverter.GetBytes(reqId).CopyTo(body, 0);
            body[2] = reader.Value.Item1;
            body[3] = reader.Value.Item2;
            twist.CopyTo(body, 4);
            try
            {
                Send(session, StreamIds.BestEffort,
                    new Submessage(SubIds.Data, SmFlags.Endiannes, body));
            }
            catch { /* 忽略单次发送失败 */ }
        }
    }

    public void Dispose()
    {
        _cts.Cancel();
        _udp.Dispose();
        _cts.Dispose();
    }
}
