# 学习与面试手册

先运行根目录 README 的启动命令，在页面生成一次计划，无需先申请模型密钥。

## 1. 看懂状态与并行

阅读 python/models/schemas.py 和 python/orchestrator/graph.py。
从 preferences 到 destination，再扇出 flight_result、hotel_result、activity_result、knowledge。
四个分支通过 LangGraph 的列表起点边汇合，budget 在全部完成后执行。
每个分支创建独立的 Pydantic 状态，并写入不同通道，避免共享可变对象。

练习：画出预算不足时的回边，解释为什么不重新执行全部搜索。

## 2. 理解预算修复

阅读 python/agents/budget_agent.py 和预算回归测试。
原版直接修改价格并重新生成搜索结果。本版在同一批候选中选择更便宜的活动、酒店和航班，原始价格不变。
每轮调整后重新汇总，最多三轮。仍然超预算则 infeasible，表示无法满足约束；failed 表示执行出错。

练习：在页面输入 1 元预算，检查状态、adjustment_round 与费用明细。

## 3. 拆开 RAG 链路

阅读 python/services/rag.py。流程为切分、向量化、Qdrant 城市过滤召回、关键词覆盖度重排、引用摘要。
默认 hash 是无密钥的词项检索基线，不是训练过的语义模型。
同一 city/source 使用稳定文档标识，重复上传覆盖旧片段，短版本删除多余片段。
切换语义模型后会使用新的集合，需要重新入库，避免不同向量空间混用。

练习：上传成都资料，分别以成都与东京搜索，确认城市过滤生效。
真实模型返回非法 JSON 或未知引用时最多修复一次；无资料时跳过模型调用。
引用 ID 合法只证明来源存在，摘要内容仍需抽样检查。

## 4. 理解后台任务与 SSE

阅读 python/services/runtime.py 与 python/api/app.py。
创建任务返回 202 和 task_id；asyncio 后台任务独立执行，SSE 只读取进度。
关闭连接不会取消任务，重连时携带 Last-Event-ID，从下一个事件续传。
心跳是 SSE 注释行，不占业务事件编号。

练习：curl.exe -N 查看事件，手动中断，再带 -H "Last-Event-ID: 2" 连接，确认第一个事件为 id: 3。

## 5. 理解 Redis 原子操作

阅读 python/services/storage.py。任务使用 Hash，事件使用 List；Lua 把快照更新、编号分配、事件追加与 TTL 更新放在一个操作内。
字段保留 JSON 字符串，避免 Lua cjson 把空数组转换成空对象。
工具缓存键包含工具名、版本、偏好与目的地，防止跨请求错误复用。
Redis 持久化状态不等于任务队列，进程崩溃后尚不能自动恢复执行。

练习：启动 Docker Compose，在 /api/health 确认 storage=redis，再重复任务与重连演示。

## 面试演示顺序

1. 正常预算生成计划，说明各节点与费用汇总。
2. 1 元预算触发三轮调整和 infeasible。
3. 重复相同请求，解释缓存键与 TTL。
4. 上传资料，展示城市过滤与来源引用。
5. SSE 断线重连，验证不重复发送旧事件。
6. 展示 pytest，说明真实 Qdrant 本地模式、Redis 模拟环境与模型请求桩。

不要描述未实现的 MySQL、真实机票 API、生产任务队列、自动恢复、神经重排或未实测的性能百分比。
