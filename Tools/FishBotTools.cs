using System.ComponentModel;
using System.Threading;
using System.Threading.Tasks;

namespace FishBotToolPanel.Tools
{
    /// <summary>
    /// 按现有 AgentTool 格式公开 FishBot 控制工具，agent 必须单独启动。
    /// </summary>
    public static class FishBotTools
    {
        /// <summary>
        /// 默认本机控制客户端，不持有长期连接。
        /// </summary>
        private static readonly FishBotClient _client = new FishBotClient();

        /// <summary>
        /// 获取可直接合并到 ToolSet 的四个小车工具。
        /// </summary>
        public static ToolSet AllTools => new ToolSet(new IAgentTool[]
        {
            new AgentTool(GetStatusAsync, "fishbot_status"),
            new AgentTool(StopAsync, "fishbot_stop"),
            new AgentTool(MoveAsync, "fishbot_move"),
            new AgentTool(TurnAsync, "fishbot_turn")
        });

        /// <summary>
        /// 查询 agent 会话、里程计与当前动作。
        /// </summary>
        /// <param name="cancellationToken">取消令牌，由工具调用框架提供。</param>
        /// <returns>状态 JSON 或失败原因。</returns>
        [Description("查询 FishBot 小车的连接、里程计位姿和运动状态；运动前应先确认 active、cmd_vel_reader 及 odom_age_ms。")]
        public static Task<FishBotResult> GetStatusAsync(CancellationToken cancellationToken = default) => _client.GetStatusAsync(cancellationToken);

        /// <summary>
        /// 立即停止小车并取消当前闭环动作。
        /// </summary>
        /// <param name="cancellationToken">取消令牌，由工具调用框架提供。</param>
        /// <returns>停车确认或失败原因。</returns>
        [Description("立即停止 FishBot 小车并取消当前运动。")]
        public static Task<FishBotResult> StopAsync(CancellationToken cancellationToken = default) => _client.StopAsync(cancellationToken);

        /// <summary>
        /// 闭环前进或后退指定距离。
        /// </summary>
        /// <param name="meters">非零距离，单位米。</param>
        /// <param name="speed">正的线速度，单位米每秒。</param>
        /// <param name="cancellationToken">取消令牌，由工具调用框架提供。</param>
        /// <returns>动作完成或失败结果。</returns>
        [Description("使 FishBot 按里程计前进或后退指定距离并等待完成。正距离前进、负距离后退。仅在用户要求运动时调用；小车没有避障能力。")]
        public static Task<FishBotResult> MoveAsync([Description("非零距离，范围 -10 至 10 米，正数前进、负数后退。")] double meters, [Description("线速度，范围 0.02 至 0.20 米每秒，默认 0.05。")] double speed = 0.05, CancellationToken cancellationToken = default) => _client.MoveAsync(meters, speed, cancellationToken);

        /// <summary>
        /// 闭环原地转向指定角度。
        /// </summary>
        /// <param name="degrees">非零角度，单位度。</param>
        /// <param name="angularSpeed">正的角速度，单位弧度每秒。</param>
        /// <param name="cancellationToken">取消令牌，由工具调用框架提供。</param>
        /// <returns>动作完成或失败结果。</returns>
        [Description("使 FishBot 原地旋转并等待完成，正角度左转、负角度右转。单次绝对角度不超过 180 度。仅在用户要求运动时调用。")]
        public static Task<FishBotResult> TurnAsync([Description("非零角度，范围 -180 至 180 度，正数左转、负数右转。")] double degrees, [Description("角速度，范围 0.1 至 1.0 弧度每秒，默认 0.3。")] double angularSpeed = 0.3, CancellationToken cancellationToken = default) => _client.TurnAsync(degrees, angularSpeed, cancellationToken);
    }
}
