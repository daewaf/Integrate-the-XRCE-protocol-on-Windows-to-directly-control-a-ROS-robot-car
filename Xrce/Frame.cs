using System.Buffers.Binary;

namespace FishBotXrceAgent.Xrce;

/// <summary>DDS-XRCE 1.0 子消息。</summary>
public sealed record Submessage(byte Id, byte Flags, byte[] Payload);

/// <summary>DDS-XRCE 1.0 消息（头部 + 一个或多个子消息）。</summary>
public sealed class XrceMessage
{
    public byte SessionId { get; set; }
    public byte StreamId { get; set; }
    public ushort SequenceNr { get; set; }
    public uint? ClientKey { get; set; }
    public List<Submessage> Submessages { get; } = new();

    public byte[] Encode()
    {
        var buf = new List<byte>(64);
        buf.Add(SessionId);
        buf.Add(StreamId);
        AddU16(buf, SequenceNr);

        // sessionId <= 0x7F 时头部必须带 clientKey
        if (SessionId <= 0x7F)
        {
            if (ClientKey is null)
                throw new InvalidOperationException("sessionId <= 127 requires clientKey");
            AddU32(buf, ClientKey.Value);
        }

        for (var i = 0; i < Submessages.Count; i++)
        {
            var sm = Submessages[i];
            buf.Add(sm.Id);
            buf.Add(sm.Flags);
            AddU16(buf, (ushort)sm.Payload.Length);
            buf.AddRange(sm.Payload);
            if (i < Submessages.Count - 1)
            {
                while (buf.Count % 4 != 0) buf.Add(0);
            }
        }
        return buf.ToArray();
    }

    public static XrceMessage Decode(ReadOnlySpan<byte> data)
    {
        if (data.Length < 4) throw new InvalidDataException("message header truncated");

        var msg = new XrceMessage
        {
            SessionId = data[0],
            StreamId = data[1],
            SequenceNr = BinaryPrimitives.ReadUInt16LittleEndian(data.Slice(2, 2)),
        };

        var offset = 4;
        if (msg.SessionId <= 0x7F)
        {
            if (data.Length < offset + 4) throw new InvalidDataException("clientKey truncated");
            msg.ClientKey = BinaryPrimitives.ReadUInt32LittleEndian(data.Slice(offset, 4));
            offset += 4;
        }

        while (offset < data.Length)
        {
            if (offset + 4 > data.Length) break;
            var id = data[offset];
            var flags = data[offset + 1];
            var len = BinaryPrimitives.ReadUInt16LittleEndian(data.Slice(offset + 2, 2));
            var start = offset + 4;
            if (start + len > data.Length)
                throw new InvalidDataException($"submessage {id} length {len} exceeds buffer");
            msg.Submessages.Add(new Submessage(id, flags, data.Slice(start, len).ToArray()));
            offset = start + len;
            while (offset % 4 != 0 && offset < data.Length) offset++;
        }
        return msg;
    }

    internal static void AddU16(List<byte> buf, ushort value)
    {
        Span<byte> tmp = stackalloc byte[2];
        BinaryPrimitives.WriteUInt16LittleEndian(tmp, value);
        buf.AddRange(tmp.ToArray());
    }

    internal static void AddU32(List<byte> buf, uint value)
    {
        Span<byte> tmp = stackalloc byte[4];
        BinaryPrimitives.WriteUInt32LittleEndian(tmp, value);
        buf.AddRange(tmp.ToArray());
    }
}

public static class SubIds
{
    public const byte CreateClient = 0x00;
    public const byte Create = 0x01;
    public const byte GetInfo = 0x02;
    public const byte Delete = 0x03;
    public const byte StatusAgent = 0x04;
    public const byte Status = 0x05;
    public const byte Info = 0x06;
    public const byte WriteData = 0x07;
    public const byte ReadData = 0x08;
    public const byte Data = 0x09;
    public const byte AckNack = 0x0A;
    public const byte Heartbeat = 0x0B;
    public const byte Reset = 0x0C;
    public const byte Fragment = 0x0D;
    public const byte Timestamp = 0x0E;
    public const byte TimestampReply = 0x0F;

    public static string Name(byte id) => id switch
    {
        CreateClient => "CREATE_CLIENT",
        Create => "CREATE",
        GetInfo => "GET_INFO",
        Delete => "DELETE",
        StatusAgent => "STATUS_AGENT",
        Status => "STATUS",
        Info => "INFO",
        WriteData => "WRITE_DATA",
        ReadData => "READ_DATA",
        Data => "DATA",
        AckNack => "ACKNACK",
        Heartbeat => "HEARTBEAT",
        Reset => "RESET",
        Fragment => "FRAGMENT",
        Timestamp => "TIMESTAMP",
        TimestampReply => "TIMESTAMP_REPLY",
        _ => id.ToString(),
    };
}

public static class SmFlags
{
    public const byte Endiannes = 0x01;
    public const byte Reuse = 0x02;
    public const byte Replace = 0x04;
}

public static class StreamIds
{
    public const byte None = 0x00;
    public const byte BestEffort = 0x01;
    public const byte Reliable = 0x80;
}

public static class ObjectKinds
{
    public const byte Participant = 0x01;
    public const byte Topic = 0x02;
    public const byte Publisher = 0x03;
    public const byte Subscriber = 0x04;
    public const byte DataWriter = 0x05;
    public const byte DataReader = 0x06;
    public const byte Type = 0x0A;
    public const byte QosProfile = 0x0B;
    public const byte Application = 0x0C;
    public const byte Agent = 0x0D;
    public const byte Client = 0x0E;
}
