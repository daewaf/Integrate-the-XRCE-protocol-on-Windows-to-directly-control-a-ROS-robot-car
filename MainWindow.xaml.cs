using System.ComponentModel;
using System.Globalization;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using FishBotToolPanel.Tools;

namespace FishBotToolPanel
{
    /// <summary>
    /// 通过统一 JSON 工具接口调用四个 FishBot 工具的窗口。
    /// </summary>
    public partial class MainWindow : Window
    {
        /// <summary>
        /// 当前窗口的工具集合。
        /// </summary>
        private readonly ToolSet _tools = FishBotTools.AllTools;

        /// <summary>
        /// 窗口生命期取消源。
        /// </summary>
        private readonly CancellationTokenSource _lifetimeCts = new CancellationTokenSource();

        /// <summary>
        /// 当前运动的取消源。
        /// </summary>
        private CancellationTokenSource? _motionCts;

        /// <summary>
        /// 当前运动任务，关闭窗口时等待补偿停车完成。
        /// </summary>
        private Task? _motionTask;

        /// <summary>
        /// 是否正在执行停车请求。
        /// </summary>
        private bool _isStopping;

        /// <summary>
        /// 是否正在关闭窗口。
        /// </summary>
        private bool _closing;

        /// <summary>
        /// 是否允许最终关闭。
        /// </summary>
        private bool _allowClose;

        /// <summary>
        /// 初始化界面与工具定义，不连接或启动 XRCE。
        /// </summary>
        public MainWindow()
        {
            InitializeComponent();
            SchemaOutput.Text = _tools.GetToolDefinitionsJson();
        }

        /// <summary>
        /// 查询连接、位姿和运动状态。
        /// </summary>
        /// <param name="sender">事件源。</param>
        /// <param name="e">事件参数。</param>
        private async void StatusButton_Click(object sender, RoutedEventArgs e)
        {
            StatusButton.IsEnabled = false;
            try
            {
                await InvokeToolAsync("fishbot_status", new { }, _lifetimeCts.Token);
            }
            finally
            {
                if (!_closing)
                {
                    StatusButton.IsEnabled = true;
                }
            }
        }

        /// <summary>
        /// 校验输入并调用位移工具。
        /// </summary>
        /// <param name="sender">事件源。</param>
        /// <param name="e">事件参数。</param>
        private async void MoveButton_Click(object sender, RoutedEventArgs e)
        {
            if (!TryNumber(DistanceInput.Text, out double meters) || !TryNumber(SpeedInput.Text, out double speed))
            {
                MessageText.Text = "距离和速度必须填写有限数字，例如 0.20、0.05。";
                return;
            }
            _motionTask = RunMotionAsync("fishbot_move", new { meters, speed });
            await _motionTask;
        }

        /// <summary>
        /// 校验输入并调用转向工具。
        /// </summary>
        /// <param name="sender">事件源。</param>
        /// <param name="e">事件参数。</param>
        private async void TurnButton_Click(object sender, RoutedEventArgs e)
        {
            if (!TryNumber(AngleInput.Text, out double degrees) || !TryNumber(AngularSpeedInput.Text, out double angularSpeed))
            {
                MessageText.Text = "转角和角速度必须填写有限数字，例如 90、0.30。";
                return;
            }
            _motionTask = RunMotionAsync("fishbot_turn", new { degrees, angularSpeed });
            await _motionTask;
        }

        /// <summary>
        /// 通过独立 TCP 请求停车，不等待运动调用结束。
        /// </summary>
        /// <param name="sender">事件源。</param>
        /// <param name="e">事件参数。</param>
        private async void StopButton_Click(object sender, RoutedEventArgs e)
        {
            if (_isStopping)
            {
                return;
            }
            _isStopping = true;
            UpdateMotionButtons();
            StopButton.IsEnabled = false;
            try
            {
                await InvokeToolAsync("fishbot_stop", new { }, _lifetimeCts.Token);
            }
            finally
            {
                _isStopping = false;
                if (!_closing)
                {
                    StopButton.IsEnabled = true;
                    UpdateMotionButtons();
                }
            }
        }

        /// <summary>
        /// 管理单次运动的取消和按钮状态。
        /// </summary>
        /// <param name="name">工具名称。</param>
        /// <param name="arguments">参数对象。</param>
        /// <returns>动作结束或失败后完成的任务。</returns>
        private async Task RunMotionAsync(string name, object arguments)
        {
            if (_motionCts is not null || _closing)
            {
                return;
            }
            using var motionCts = CancellationTokenSource.CreateLinkedTokenSource(_lifetimeCts.Token);
            _motionCts = motionCts;
            UpdateMotionButtons();
            try
            {
                await InvokeToolAsync(name, arguments, motionCts.Token);
            }
            finally
            {
                _motionCts = null;
                if (!_closing)
                {
                    UpdateMotionButtons();
                }
            }
        }

        /// <summary>
        /// 通过 IAgentTool 进行调用，展示统一的结构化结果。
        /// </summary>
        /// <param name="name">工具名称。</param>
        /// <param name="arguments">参数对象。</param>
        /// <param name="cancellationToken">取消令牌。</param>
        /// <returns>处理完成的任务。</returns>
        private async Task InvokeToolAsync(string name, object arguments, CancellationToken cancellationToken)
        {
            try
            {
                IAgentTool tool = _tools.Tools.Single(candidate => candidate.Name == name);
                JsonElement json = JsonSerializer.SerializeToElement(arguments);
                AppendLog($"> {name} {json.GetRawText()}");
                MessageText.Text = $"正在调用 {name}…";
                object? result = await tool.InvokeAsync(json, cancellationToken);
                if (_closing)
                {
                    return;
                }
                AppendLog(JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping }));
                if (result is FishBotResult response)
                {
                    MessageText.Text = response.Ok ? $"{name} 调用成功。" : response.Error ?? "调用失败。";
                    if (name == "fishbot_status")
                    {
                        UpdateStatus(response);
                    }
                }
            }
            catch (Exception exception)
            {
                if (!_closing)
                {
                    MessageText.Text = $"调用失败：{exception.GetBaseException().Message}";
                    AppendLog(MessageText.Text);
                }
            }
        }

        /// <summary>
        /// 将状态 JSON 显示为可读的连接与位姿信息。
        /// </summary>
        /// <param name="result">状态查询结果。</param>
        private void UpdateStatus(FishBotResult result)
        {
            if (!result.Ok || result.Status is not JsonElement status)
            {
                ConnectionText.Text = "无法连接 agent";
                ConnectionText.Foreground = Brushes.Firebrick;
                StateText.Text = "运动状态：未知";
                PoseText.Text = "X：— m     Y：— m     朝向：— °";
                OdomText.Text = "里程计：—     活跃会话：—";
                return;
            }
            int active = status.TryGetProperty("active", out JsonElement activeValue) && activeValue.TryGetInt32(out int count) ? count : 0;
            long age = status.TryGetProperty("odom_age_ms", out JsonElement ageValue) && ageValue.TryGetInt64(out long milliseconds) ? milliseconds : -1;
            bool reader = status.TryGetProperty("cmd_vel_reader", out JsonElement readerValue) && readerValue.ValueKind == JsonValueKind.True;
            bool ready = active > 0 && reader && age >= 0 && age <= 200;
            ConnectionText.Text = ready ? "小车已连接 · 里程计正常" : "agent 已连接 · 小车未就绪";
            ConnectionText.Foreground = ready ? Brushes.DarkGreen : Brushes.DarkGoldenrod;
            string state = status.TryGetProperty("state", out JsonElement stateValue) ? stateValue.ToString() : "未知";
            StateText.Text = $"运动状态：{state}";
            PoseText.Text = status.TryGetProperty("pose", out JsonElement pose) && pose.ValueKind == JsonValueKind.Object ? $"X：{GetCoordinate(pose, "x")} m     Y：{GetCoordinate(pose, "y")} m     朝向：{GetCoordinate(pose, "yaw")} °" : "X：— m     Y：— m     朝向：— °";
            OdomText.Text = $"里程计帧龄：{age} ms     活跃会话：{active}";
        }

        /// <summary>
        /// 提取有限的位姿数值。
        /// </summary>
        /// <param name="pose">位姿对象。</param>
        /// <param name="name">坐标名称。</param>
        /// <returns>格式化数值或缺失标记。</returns>
        private static string GetCoordinate(JsonElement pose, string name)
        {
            return pose.TryGetProperty(name, out JsonElement value) && value.TryGetDouble(out double number) && double.IsFinite(number) ? number.ToString("0.000", CultureInfo.InvariantCulture) : "—";
        }

        /// <summary>
        /// 解析界面上的有限数字，支持小数点和当前区域格式。
        /// </summary>
        /// <param name="text">输入文本。</param>
        /// <param name="number">解析结果。</param>
        /// <returns>是否为有限数字。</returns>
        private static bool TryNumber(string text, out double number)
        {
            return (double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out number) || double.TryParse(text, NumberStyles.Float, CultureInfo.CurrentCulture, out number)) && double.IsFinite(number);
        }

        /// <summary>
        /// 按执行状态启停运动按钮，不影响状态和停车请求。
        /// </summary>
        private void UpdateMotionButtons()
        {
            MoveButton.IsEnabled = _motionCts is null && !_isStopping && !_closing;
            TurnButton.IsEnabled = MoveButton.IsEnabled;
        }

        /// <summary>
        /// 追加有时间戳的记录，并限制日志长度。
        /// </summary>
        /// <param name="message">日志文本。</param>
        private void AppendLog(string message)
        {
            if (LogOutput.Text.Length > 100000)
            {
                LogOutput.Text = LogOutput.Text[^50000..];
            }
            LogOutput.AppendText($"[{DateTime.Now:HH:mm:ss}] {message}{Environment.NewLine}{Environment.NewLine}");
            LogOutput.ScrollToEnd();
        }

        /// <summary>
        /// 关闭时取消本窗口的运动并等待客户端尝试停车，不结束独立 XRCE 进程。
        /// </summary>
        /// <param name="sender">事件源。</param>
        /// <param name="e">关闭参数。</param>
        private async void Window_Closing(object? sender, CancelEventArgs e)
        {
            if (_allowClose)
            {
                return;
            }
            e.Cancel = true;
            if (_closing)
            {
                return;
            }
            _closing = true;
            IsEnabled = false;
            MessageText.Text = "正在结束工具调用…";
            try
            {
                _lifetimeCts.Cancel();
                if (_motionTask is not null)
                {
                    await _motionTask;
                }
            }
            catch (Exception exception)
            {
                System.Diagnostics.Trace.WriteLine($"关闭时结束运动失败：{exception}");
            }
            finally
            {
                _lifetimeCts.Dispose();
                _allowClose = true;
                // 等本次 Closing 事件返回后再关闭，避免同步重入。
                _ = Dispatcher.BeginInvoke(new Action(Close));
            }
        }
    }
}
