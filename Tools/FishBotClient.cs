using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace FishBotToolPanel.Tools
{
    /// <summary>
    /// 表示一次小车控制调用的结果；状态查询成功不代表小车已连接。
    /// </summary>
    /// <param name="Ok">协议调用是否成功。</param>
    /// <param name="Response">服务端原始响应。</param>
    /// <param name="Error">失败原因。</param>
    /// <param name="Status">状态查询返回的 JSON 对象。</param>
    /// <param name="StopConfirmed">运动异常后是否收到停车确认；未尝试时为 null。</param>
    public sealed record FishBotResult(bool Ok, string? Response = null, string? Error = null, JsonElement? Status = null, bool? StopConfirmed = null);

    /// <summary>
    /// 通过本机 TCP 控制口调用独立运行的 XRCE agent，每次请求使用独立连接。
    /// </summary>
    public sealed class FishBotClient
    {
        /// <summary>
        /// 本机控制端口。
        /// </summary>
        private readonly int _port;

        /// <summary>
        /// 可选的响应超时覆盖值，主要用于调用方定制及离线验证。
        /// </summary>
        private readonly TimeSpan? _responseTimeout;

        /// <summary>
        /// 创建本机控制客户端，不启动进程或建立连接。
        /// </summary>
        /// <param name="port">控制端口。</param>
        /// <param name="responseTimeout">响应超时；为空时按动作预计时长计算。</param>
        /// <exception cref="ArgumentOutOfRangeException">端口或超时时间无效。</exception>
        public FishBotClient(int port = 8898, TimeSpan? responseTimeout = null)
        {
            if (port < 1 || port > 65535)
            {
                throw new ArgumentOutOfRangeException(nameof(port));
            }
            if (responseTimeout is not null && (responseTimeout.Value <= TimeSpan.Zero || responseTimeout.Value.TotalMilliseconds > int.MaxValue))
            {
                throw new ArgumentOutOfRangeException(nameof(responseTimeout));
            }
            _port = port;
            _responseTimeout = responseTimeout;
        }

        /// <summary>
        /// 查询 agent 状态及里程计信息。
        /// </summary>
        /// <param name="cancellationToken">取消令牌。</param>
        /// <returns>包含服务端 JSON 状态或错误的异步结果。</returns>
        public Task<FishBotResult> GetStatusAsync(CancellationToken cancellationToken = default)
        {
            return ExecuteAsync("status", false, TimeSpan.FromSeconds(5), cancellationToken);
        }

        /// <summary>
        /// 立即停止运动，可与正在等待完成的运动调用并发。
        /// </summary>
        /// <param name="cancellationToken">取消令牌。</param>
        /// <returns>收到停车确认后成功的异步结果。</returns>
        public Task<FishBotResult> StopAsync(CancellationToken cancellationToken = default)
        {
            return ExecuteAsync("stop", false, TimeSpan.FromSeconds(5), cancellationToken);
        }

        /// <summary>
        /// 按里程计闭环前进或后退，等待动作结束。
        /// </summary>
        /// <param name="meters">距离，正数前进、负数后退，非零且绝对值不超过 10 米。</param>
        /// <param name="speed">速度，0.02 至 0.20 米每秒。</param>
        /// <param name="cancellationToken">取消令牌；取消后尝试单独发送停车命令。</param>
        /// <returns>运动完成或失败的异步结果。</returns>
        public Task<FishBotResult> MoveAsync(double meters, double speed = 0.05, CancellationToken cancellationToken = default)
        {
            if (!double.IsFinite(meters) || meters == 0 || Math.Abs(meters) > 10 || !double.IsFinite(speed) || speed < 0.02 || speed > 0.20)
            {
                return Task.FromResult(new FishBotResult(false, Error: "距离必须为非零有限数且在 -10 至 10 米内；速度必须在 0.02 至 0.20 米每秒内。"));
            }
            return ExecuteAsync(FormattableString.Invariant($"forward {meters:R} {speed:R}"), true, TimeSpan.FromSeconds(Math.Abs(meters) / speed + 10), cancellationToken);
        }

        /// <summary>
        /// 按里程计闭环转向，等待动作结束；单次限制在正负 180 度内以匹配当前 agent 实现。
        /// </summary>
        /// <param name="degrees">非零转角，正数左转、负数右转，绝对值不超过 180 度。</param>
        /// <param name="angularSpeed">角速度，0.1 至 1.0 弧度每秒。</param>
        /// <param name="cancellationToken">取消令牌；取消后尝试单独发送停车命令。</param>
        /// <returns>运动完成或失败的异步结果。</returns>
        public Task<FishBotResult> TurnAsync(double degrees, double angularSpeed = 0.3, CancellationToken cancellationToken = default)
        {
            if (!double.IsFinite(degrees) || degrees == 0 || Math.Abs(degrees) > 180 || !double.IsFinite(angularSpeed) || angularSpeed < 0.1 || angularSpeed > 1.0)
            {
                return Task.FromResult(new FishBotResult(false, Error: "角度必须为非零有限数且在 -180 至 180 度内；角速度必须在 0.1 至 1.0 弧度每秒内。"));
            }
            return ExecuteAsync(FormattableString.Invariant($"turn {degrees:R} {angularSpeed:R}"), true, TimeSpan.FromSeconds(Math.Abs(degrees) * Math.PI / 180 / angularSpeed + 10), cancellationToken);
        }

        /// <summary>
        /// 发送命令并解释响应；运动通信异常时尝试停车并明确报告确认结果。
        /// </summary>
        /// <param name="command">完整协议命令。</param>
        /// <param name="motion">是否为运动命令。</param>
        /// <param name="timeout">默认响应超时。</param>
        /// <param name="cancellationToken">取消令牌。</param>
        /// <returns>结构化协议结果。</returns>
        private async Task<FishBotResult> ExecuteAsync(string command, bool motion, TimeSpan timeout, CancellationToken cancellationToken)
        {
            if (cancellationToken.IsCancellationRequested)
            {
                return new FishBotResult(false, Error: "调用已取消，未发送命令。 ");
            }
            try
            {
                string response = await ExchangeAsync(command, _responseTimeout ?? timeout, cancellationToken).ConfigureAwait(false);
                if (response.StartsWith("ERR ", StringComparison.Ordinal))
                {
                    return new FishBotResult(false, Response: response, Error: response);
                }
                if (command == "status")
                {
                    using JsonDocument document = JsonDocument.Parse(response);
                    if (document.RootElement.ValueKind != JsonValueKind.Object || !document.RootElement.TryGetProperty("ok", out JsonElement ok) || ok.ValueKind != JsonValueKind.True)
                    {
                        throw new IOException("状态响应缺少有效的 ok 标记。");
                    }
                    return new FishBotResult(true, response, Status: document.RootElement.Clone());
                }
                if ((command == "stop" && response == "OK stopped") || (command.StartsWith("forward ", StringComparison.Ordinal) && response.StartsWith("DONE forward ", StringComparison.Ordinal)) || (command.StartsWith("turn ", StringComparison.Ordinal) && response.StartsWith("DONE turn ", StringComparison.Ordinal)))
                {
                    return new FishBotResult(true, response);
                }
                throw new IOException($"无法识别的控制响应：{response}");
            }
            catch (Exception exception) when (exception is SocketException or IOException or OperationCanceledException or JsonException)
            {
                bool? stopConfirmed = null;
                if (motion)
                {
                    stopConfirmed = await TryStopAsync().ConfigureAwait(false);
                }
                string error = exception is OperationCanceledException ? (cancellationToken.IsCancellationRequested ? "调用已取消。" : "控制请求超时。") : $"控制请求失败：{exception.Message}";
                if (motion)
                {
                    error += stopConfirmed == true ? " 已收到停车确认。" : " 未收到停车确认，请检查 agent 和小车状态。";
                }
                return new FishBotResult(false, Error: error, StopConfirmed: stopConfirmed);
            }
        }

        /// <summary>
        /// 建立独立连接并交换一行 UTF-8 消息，连接阶段最多等待三秒。
        /// </summary>
        /// <param name="command">待发送命令。</param>
        /// <param name="timeout">完整交换超时。</param>
        /// <param name="cancellationToken">外部取消令牌。</param>
        /// <returns>收到的响应行。</returns>
        private async Task<string> ExchangeAsync(string command, TimeSpan timeout, CancellationToken cancellationToken)
        {
            using var requestCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            requestCts.CancelAfter(timeout);
            using var connectCts = CancellationTokenSource.CreateLinkedTokenSource(requestCts.Token);
            connectCts.CancelAfter(TimeSpan.FromSeconds(3));
            using var client = new TcpClient();
            await client.ConnectAsync(IPAddress.Loopback, _port, connectCts.Token).ConfigureAwait(false);
            using NetworkStream stream = client.GetStream();
            using var writer = new StreamWriter(stream, new UTF8Encoding(false), 1024, true) { AutoFlush = true, NewLine = "\n" };
            using var reader = new StreamReader(stream, Encoding.UTF8, false, 1024, true);
            await writer.WriteLineAsync(command.AsMemory(), requestCts.Token).ConfigureAwait(false);
            return await reader.ReadLineAsync(requestCts.Token).ConfigureAwait(false) ?? throw new IOException("控制口在返回结果前断开连接。");
        }

        /// <summary>
        /// 在不复用调用方取消令牌的情况下发送停车请求，最多等待两秒。
        /// </summary>
        /// <returns>是否收到明确的停车确认。</returns>
        private async Task<bool> TryStopAsync()
        {
            try
            {
                return await ExchangeAsync("stop", TimeSpan.FromSeconds(2), CancellationToken.None).ConfigureAwait(false) == "OK stopped";
            }
            catch (Exception exception) when (exception is SocketException or IOException or OperationCanceledException)
            {
                // 调用结果中的 StopConfirmed=false 会向调用方明确报告停车未确认。
                return false;
            }
        }
    }
}
