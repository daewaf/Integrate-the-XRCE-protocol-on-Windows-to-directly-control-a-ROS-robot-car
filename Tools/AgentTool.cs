using System.ComponentModel;
using System.Reflection;
using System.Text.Json;

namespace FishBotToolPanel.Tools
{
    /// <summary>
    /// 将带 Description 的委托封装为 JSON 工具，不依赖模型 SDK。
    /// </summary>
    public sealed class AgentTool : IAgentTool
    {
        /// <summary>
        /// 已绑定目标的工具委托。
        /// </summary>
        private readonly Delegate _handler;

        /// <summary>
        /// 工具方法的参数定义。
        /// </summary>
        private readonly ParameterInfo[] _parameters;

        /// <summary>
        /// 初始化委托工具并生成参数 Schema。
        /// </summary>
        /// <param name="handler">工具委托。</param>
        /// <param name="name">工具名称。</param>
        public AgentTool(Delegate handler, string? name = null)
        {
            ArgumentNullException.ThrowIfNull(handler);
            _handler = handler;
            _parameters = handler.Method.GetParameters();
            Name = name ?? handler.Method.Name;
            Description = handler.Method.GetCustomAttribute<DescriptionAttribute>()?.Description ?? Name;
            var properties = new Dictionary<string, object>();
            var required = new List<string>();
            foreach (ParameterInfo parameter in _parameters)
            {
                if (parameter.ParameterType == typeof(CancellationToken))
                {
                    continue;
                }
                string parameterName = parameter.Name ?? throw new ArgumentException("工具参数缺少名称。", nameof(handler));
                string type = parameter.ParameterType == typeof(double) ? "number" : throw new NotSupportedException($"工具参数类型不受支持：{parameter.ParameterType}");
                properties.Add(parameterName, new { type, description = parameter.GetCustomAttribute<DescriptionAttribute>()?.Description ?? parameterName });
                if (!parameter.HasDefaultValue)
                {
                    required.Add(parameterName);
                }
            }
            ParametersSchema = JsonSerializer.Serialize(new { type = "object", properties, required, additionalProperties = false });
        }

        /// <summary>
        /// 工具名称。
        /// </summary>
        public string Name { get; }

        /// <summary>
        /// 工具说明。
        /// </summary>
        public string Description { get; }

        /// <summary>
        /// JSON Schema 参数定义。
        /// </summary>
        public string ParametersSchema { get; }

        /// <summary>
        /// 校验 JSON 参数并调用异步工具，取消令牌不暴露为用户参数。
        /// </summary>
        /// <param name="arguments">参数对象。</param>
        /// <param name="cancellationToken">取消令牌。</param>
        /// <returns>工具返回结果。</returns>
        public async ValueTask<object?> InvokeAsync(JsonElement arguments, CancellationToken cancellationToken = default)
        {
            if (arguments.ValueKind != JsonValueKind.Object)
            {
                throw new ArgumentException("工具参数必须是 JSON 对象。", nameof(arguments));
            }
            foreach (JsonProperty property in arguments.EnumerateObject())
            {
                if (!_parameters.Any(parameter => parameter.ParameterType != typeof(CancellationToken) && parameter.Name == property.Name))
                {
                    throw new ArgumentException($"未知参数：{property.Name}", nameof(arguments));
                }
            }
            var values = new object?[_parameters.Length];
            for (int index = 0; index < _parameters.Length; index++)
            {
                ParameterInfo parameter = _parameters[index];
                if (parameter.ParameterType == typeof(CancellationToken))
                {
                    values[index] = cancellationToken;
                }
                else if (arguments.TryGetProperty(parameter.Name ?? string.Empty, out JsonElement value))
                {
                    values[index] = value.Deserialize(parameter.ParameterType);
                }
                else if (parameter.HasDefaultValue)
                {
                    values[index] = parameter.DefaultValue;
                }
                else
                {
                    throw new ArgumentException($"缺少必填参数：{parameter.Name}", nameof(arguments));
                }
            }
            object? invocation = _handler.DynamicInvoke(values);
            if (invocation is Task<FishBotResult> task)
            {
                return await task.ConfigureAwait(false);
            }
            throw new NotSupportedException("此独立工具集要求工具返回 Task<FishBotResult>。");
        }
    }
}
