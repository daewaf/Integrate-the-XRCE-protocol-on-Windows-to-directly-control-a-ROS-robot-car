using System.Text.Json;

namespace FishBotToolPanel.Tools
{
    /// <summary>
    /// 管理四个小车工具并导出函数工具定义。
    /// </summary>
    public sealed class ToolSet
    {
        /// <summary>
        /// 工具列表。
        /// </summary>
        public List<IAgentTool> Tools { get; } = new List<IAgentTool>();

        /// <summary>
        /// 创建空工具集合。
        /// </summary>
        public ToolSet() { }

        /// <summary>
        /// 从已有工具初始化集合。
        /// </summary>
        /// <param name="tools">工具序列。</param>
        public ToolSet(IEnumerable<IAgentTool> tools)
        {
            foreach (IAgentTool tool in tools)
            {
                Add(tool);
            }
        }

        /// <summary>
        /// 按唯一名称添加工具。
        /// </summary>
        /// <param name="tool">待注册的工具。</param>
        /// <returns>是否新增成功。</returns>
        public bool Add(IAgentTool tool)
        {
            ArgumentNullException.ThrowIfNull(tool);
            if (Tools.Any(candidate => candidate.Name == tool.Name))
            {
                return false;
            }
            Tools.Add(tool);
            return true;
        }

        /// <summary>
        /// 导出独立于模型 SDK 的函数工具 JSON 定义。
        /// </summary>
        /// <returns>包含名称、说明及参数 Schema 的 JSON 数组。</returns>
        public string GetToolDefinitionsJson()
        {
            return JsonSerializer.Serialize(Tools.Select(tool => new { type = "function", name = tool.Name, description = tool.Description, parameters = JsonSerializer.Deserialize<JsonElement>(tool.ParametersSchema) }), new JsonSerializerOptions { WriteIndented = true });
        }
    }
}
