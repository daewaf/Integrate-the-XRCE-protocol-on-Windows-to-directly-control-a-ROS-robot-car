using System.Buffers.Binary;

namespace FishBotXrceAgent.Xrce;

/// <summary>最小 XCDR（小端）写入器。</summary>
public sealed class CdrWriter
{
    private readonly List<byte> _buf = new();

    public CdrWriter Align(int n)
    {
        while (_buf.Count % n != 0) _buf.Add(0);
        return this;
    }

    public CdrWriter U8(byte v) { _buf.Add(v); return this; }

    public CdrWriter U16(ushort v)
    {
        Align(2);
        Span<byte> tmp = stackalloc byte[2];
        BinaryPrimitives.WriteUInt16LittleEndian(tmp, v);
        _buf.AddRange(tmp.ToArray());
        return this;
    }

    public CdrWriter I32(int v)
    {
        Align(4);
        Span<byte> tmp = stackalloc byte[4];
        BinaryPrimitives.WriteInt32LittleEndian(tmp, v);
        _buf.AddRange(tmp.ToArray());
        return this;
    }

    public CdrWriter U32(uint v)
    {
        Align(4);
        Span<byte> tmp = stackalloc byte[4];
        BinaryPrimitives.WriteUInt32LittleEndian(tmp, v);
        _buf.AddRange(tmp.ToArray());
        return this;
    }

    public CdrWriter F64(double v)
    {
        Align(8);
        Span<byte> tmp = stackalloc byte[8];
        BinaryPrimitives.WriteDoubleLittleEndian(tmp, v);
        _buf.AddRange(tmp.ToArray());
        return this;
    }

    public CdrWriter String(string s)
    {
        var raw = System.Text.Encoding.UTF8.GetBytes(s + "\0");
        U32((uint)raw.Length);
        _buf.AddRange(raw);
        return this;
    }

    public CdrWriter Raw(ReadOnlySpan<byte> data) { _buf.AddRange(data.ToArray()); return this; }

    public CdrWriter DHeader(int payloadLength)
    {
        U32(0x80000000u | ((uint)payloadLength & 0x7FFFFFFF));
        return this;
    }

    public byte[] Bytes() => _buf.ToArray();
    public int Length => _buf.Count;
}

/// <summary>最小 XCDR（小端）读取器。</summary>
public sealed class CdrReader
{
    private readonly byte[] _data;
    private int _offset;

    public CdrReader(byte[] data, int offset = 0)
    {
        _data = data;
        _offset = offset;
    }

    public CdrReader Align(int n)
    {
        while (_offset % n != 0) _offset++;
        return this;
    }

    private ReadOnlySpan<byte> Take(int n)
    {
        if (_offset + n > _data.Length) throw new InvalidDataException("CDR buffer underflow");
        var span = _data.AsSpan(_offset, n);
        _offset += n;
        return span;
    }

    public byte U8() => Take(1)[0];

    public ushort U16()
    {
        Align(2);
        return BinaryPrimitives.ReadUInt16LittleEndian(Take(2));
    }

    public int I32()
    {
        Align(4);
        return BinaryPrimitives.ReadInt32LittleEndian(Take(4));
    }

    public uint U32()
    {
        Align(4);
        return BinaryPrimitives.ReadUInt32LittleEndian(Take(4));
    }

    public double F64()
    {
        Align(8);
        return BinaryPrimitives.ReadDoubleLittleEndian(Take(8));
    }

    public string String()
    {
        var len = (int)U32();
        var raw = Take(len).ToArray();
        var end = Array.IndexOf(raw, (byte)0);
        if (end < 0) end = raw.Length;
        return System.Text.Encoding.UTF8.GetString(raw, 0, end);
    }
}

public static class MsgCodec
{
    /// <summary>geometry_msgs/msg/Twist：6 个 float64，共 48 字节。</summary>
    public static byte[] TwistCdr(double linearX = 0, double angularZ = 0)
    {
        var w = new CdrWriter();
        foreach (var v in new[] { linearX, 0.0, 0.0, 0.0, 0.0, angularZ })
            w.F64(v);
        return w.Bytes();
    }

    /// <summary>解析 nav_msgs/msg/Odometry 的 x, y, yaw(度)。</summary>
    public static (double X, double Y, double YawDeg) OdomPose(byte[] data)
    {
        var r = new CdrReader(data);
        r.I32();          // stamp.sec
        r.U32();          // stamp.nanosec
        r.String();       // header.frame_id
        r.String();       // child_frame_id
        var x = r.F64();
        var y = r.F64();
        r.F64();          // z
        var qx = r.F64();
        var qy = r.F64();
        var qz = r.F64();
        var qw = r.F64();
        var yaw = Math.Atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz));
        return (x, y, yaw * 180.0 / Math.PI);
    }
}
