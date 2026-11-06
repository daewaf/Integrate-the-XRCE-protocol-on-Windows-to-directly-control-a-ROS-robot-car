<!-- csharp-wpf-development:begin -->
## C#/WPF 代码约定

本项目已接入 csharp-wpf-development 的规范资料。处理 C#/WPF 代码前读取 `docs/csharp-wpf-standard/code-standard.md`；接入记录位于 `docs/csharp-wpf-standard/skill-state.json`，配置和迁移说明位于 `docs/csharp-wpf-standard/adoption.md`。

- 有该 skill 时使用其开发、审查、接入、迁移或升级流程；未安装时按上述项目内文档执行，不要求访问原作者的电脑。
- 普通开发完成本次需求并遵循规范；只读审查不修改项目；统一迁移在用户明确要求的范围内进行。
- 资料已接入不代表全库代码已符合规范。首次采用已有项目需要一次统一风格迁移；迁移完成情况以实际改动和验证记录为准，不从资料存在推断完成。
- 架构、框架升级和实质性重构渐进处理；新增依赖先询问，已获得的同项授权不重复询问。
- 需要图标时优先使用 XAML 绘制；XAML 图标定义集中放入独立的图标资源字典文件，通过资源引用使用。
- 开发或构建中发现需求模糊或有尚未明确选择的多种可行实现路径时，及时说明选项和差异，由用户选择；答复前暂停依赖该选择的实现，可继续独立工作。已确认或已明确授权自行决定的同一事项不重复询问。
- 保留本项目已明确的编码和行尾约定；现有 EditorConfig 的合并方式按接入说明执行。
- 数据、网络、存储和发布需求有缺失时，按 `docs/csharp-wpf-standard/project-scenarios.md` 针对当前任务补充询问。

<!-- csharp-wpf-development:end -->
