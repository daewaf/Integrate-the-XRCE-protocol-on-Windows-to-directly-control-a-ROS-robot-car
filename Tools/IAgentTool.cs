using System.Text.Json;

namespace FishBotToolPanel.Tools
{
    /// <summary>
    /// 保留现有工具的名称、描述、参数模式和 JSON 异步调用契约。
    /// </summary>
    public interface IAgentTool
    {
        /// <summary>
        /// 工具名称。
        /// </summary>
        string Name { get; }

        /// <summary>
        /// 工具说明。
        /// </summary>
        string Description { get; }

        /// <summary>
        /// JSON Schema 参数定义。
        /// </summary>
        string ParametersSchema { get; }

        /// <summary>
        /// 使用 JSON 对象调用工具。
        /// </summary>
        /// <param name="arguments">参数对象。</param>
        /// <param name="cancellationToken">取消令牌。</param>
        /// <returns>工具的实际返回结果。</returns>
        ValueTask<object?> InvokeAsync(JsonElement arguments, CancellationToken cancellationToken = default);
    }
}
