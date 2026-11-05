# 来源与二次开发

上游：https://github.com/bcefghj/multi-agent-travel-planner

基线提交：8132dfcded4539a4ca28b1c1fc316b93001c0b08。

本地克隆保留上游提交历史；远程仓库通过连接器导入完整源码快照，并以独立提交记录本次改进。本次在 Python 版本中加入 LangGraph 工作流、Qdrant 检索、Redis 状态与缓存、SSE 重放、模型摘要、演示页与回归测试，并修复预算循环与异常传播。

原始 README 归档在 docs/UPSTREAM_README.md。上游 README 标注 MIT，但该快照没有单独的 LICENSE 文件；此处保留原始说明，不替原作者编写版权声明。

简历建议描述为“基于开源旅游规划系统进行 Python 二次开发”，再介绍实际完成的改进。上游资料中的百分比指标不代表本版本的实测性能。
