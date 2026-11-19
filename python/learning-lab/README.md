# 基于 LangGraph 与 RAG 的多 Agent 旅游规划系统

一个用于学习和展示 Agent 工程能力的 Python 项目：接收旅行偏好后，编排目的地、航班、酒店、活动和知识检索分支，执行预算回路，并通过 RAG 生成带来源引用的资料摘要。

## 架构

```text
POST /tasks
  │
  ├─ Redis：任务快照、事件序号、SSE 回放记录、检索缓存
  └─ ThreadPoolExecutor
       └─ LangGraph
          preferences → destination
                          ├─ flight ───┐
                          ├─ hotel ────┤
                          ├─ activity ─┼→ budget → adjust (最多 2 次)
                          └─ knowledge ┘                 │
                                                          ↓
                                               answer（受引用约束）

Qdrant：文档切分、向量召回、城市过滤、关键词二阶段重排
SSE：queued / running / progress / succeeded / failed，支持 Last-Event-ID 补发
```

## 核心能力

- **LangGraph 工作流**：预算超限只调整活动费用，不修改用户原始需求；最多两轮后返回 `over_budget`。
- **RAG 检索**：以城市过滤向量候选，再按关键词得分二阶段重排；答案只能引用本次检索出的片段 ID。
- **增量入库**：`document_id` 由城市和文件名稳定生成，`content_hash` 识别版本；内容未变不重复向量化，更新或删除文件会同步替换 Qdrant 片段。
- **任务与事件**：Redis Lua 脚本原子更新任务快照、事件序号和 SSE 回放数据；断线后使用 `Last-Event-ID` 增量恢复。
- **重启恢复**：服务启动时将旧进程遗留的 `queued/running` 任务标记为 `ServiceRestarted`，不自动重跑，以免重复调用模型或产生重复外部副作用。
- **可靠性**：模型请求有超时和最多三次网络重试；节点完成和重试都会作为 SSE `progress` 事件推送。
- **报价边界**：航班、酒店、活动经过独立供应商适配层；默认 `demo` 报价会带 `provider/quote_reference/quoted_at` 标识，非 `demo` 供应商未配置时会显式失败，不会伪装成实时价格。
- **运行可观测性**：`/livez` 用于进程存活检查，`/healthz` 同时检查 Redis 与 Qdrant，`/metrics` 提供 Prometheus 文本指标（受 API Key 保护）；指标包括路由请求量/耗时与规划任务最终状态/耗时，且不使用任务 ID 作为标签。

## 环境准备

- Python 3.12+
- Docker Desktop（本地 Redis、Qdrant，或直接使用完整 Compose 部署）
- DeepSeek API Key

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中填写 `DEEPSEEK_API_KEY`，不要提交该文件。

## 启动

启动 Redis：

```powershell
docker compose up -d redis
docker compose ps
```

首次使用新版知识库格式时，显式重建本项目本地的 `travel_knowledge` 集合：

```powershell
python ingest_knowledge.py --rebuild
```

日常修改 `knowledge/*.md` 后执行增量入库：

```powershell
python ingest_knowledge.py
```

启动 API：

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

访问 `http://127.0.0.1:8001/docs` 使用 Swagger 调试。

## Docker 部署

Compose 会启动 API、Redis 和 Qdrant。Redis、Qdrant 仅在 Docker 内部网络暴露，API 只映射到本机 `127.0.0.1:8001`。

```powershell
Copy-Item .env.example .env
# 在 .env 中设置 DEEPSEEK_API_KEY；部署环境同时设置 API_KEY
docker compose up -d --build
docker compose run --rm api python ingest_knowledge.py --rebuild
curl.exe http://127.0.0.1:8001/healthz
```

首次容器入库会下载 Embedding 模型；模型缓存、任务清单、Redis 和 Qdrant 数据均使用 Docker Volume 持久化。`--rebuild` 只清空本项目的 `travel_knowledge` 集合。

设置 `API_KEY` 后，除 `/health` 与 `/healthz` 外的接口均需要携带：

```text
X-API-Key: <你的 API_KEY>
```

可通过 `REDIS_HOST`、`REDIS_PORT`、`QDRANT_URL`、`QDRANT_API_KEY` 切换到托管 Redis 或 Qdrant Cloud；本地模式下不设置 `QDRANT_URL` 即继续使用磁盘路径模式。

`RATE_LIMIT_REQUESTS` 与 `RATE_LIMIT_WINDOW_SECONDS` 控制固定窗口限流；设为 `0` 可临时关闭限流（只建议本地调试）。访问日志只记录方法、路径、状态码和耗时，不记录请求体或认证信息。

### HTTPS 与域名

默认 Compose 仅把 API 绑定在本机 `127.0.0.1:8001`。有可公开访问的域名、DNS A/AAAA 记录和开放的 80/443 端口时，填写 `.env` 的 `DOMAIN`，再启用 Caddy 配置文件：

```powershell
docker compose --profile edge up -d
```

Caddy 会自动申请和续期 TLS 证书，并将 HTTPS 请求转发给 API。公网环境还应将 `ALLOWED_HOSTS` 设为真实域名，将 `CORS_ALLOW_ORIGINS` 设为实际前端来源。`.env` 只适合本地或单机部署；云环境应由平台的 Secret Manager 在运行时注入同名环境变量，绝不能写入镜像或提交 Git。

## 异步任务接口

| 接口 | 说明 |
| --- | --- |
| `POST /tasks` | 创建任务，返回任务 ID、查询地址和 SSE 地址 |
| `GET /tasks/{task_id}` | 获取任务快照与最终规划结果 |
| `GET /tasks/{task_id}/events` | 订阅 SSE 事件；支持 `Last-Event-ID` |
| `POST /recommendations` | 同步执行入口，便于快速调试 |

任务的 `status=succeeded` 代表执行成功；最终规划的 `result.status=over_budget` 代表业务上预算无解，两者并不矛盾。

## Hotelbeds 真实酒店查询

`POST /providers/hotelbeds/hotel-offers` 接入 Hotelbeds Hotel Booking API 的只读 Availability 查询，不调用 `checkrates` 或 `bookings`，不会产生订单。请求必须带入住/离店日期、成人数及 Hotelbeds 酒店代码；返回真实供应商金额与币种，**不会直接加入当前 CNY 演示预算**，避免未接汇率服务时跨币种误算。

Hotelbeds 目前要求酒店 Availability 使用 mTLS。将 API Key、Secret、客户端证书和私钥只配置在本机 `.env`，例如：

```ini
HOTELBEDS_API_KEY=...
HOTELBEDS_SECRET=...
HOTELBEDS_CLIENT_CERT=C:\\secure\\hotelbeds-client.crt
HOTELBEDS_CLIENT_KEY=C:\\secure\\hotelbeds-client.key
```

证书目录、`.pem`、`.key` 和 `.crt` 均被忽略，不能提交 Git。测试环境基地址为 `https://api-mtls.test.hotelbeds.com`。完整预订流程还必须先对 `rateType=RECHECK` 的报价调用 CheckRate，再由经审核的支付/预订流程确认；本项目不执行这些有外部副作用的步骤。

如果系统 OpenSSL 配置不可用，可用安装在本机 Anaconda 的 Python 生成 CSR：`D:\\anaconda\\python.exe generate_hotelbeds_csr.py`。只将生成的 `certs/hotelbeds-client.csr` 上传给 Hotelbeds，私钥始终留在 `certs/hotelbeds-client.key`。

## 验证

```powershell
python -m pytest test_answer_agent.py test_answer_retry.py test_document_loader.py test_reranker.py test_ingest_manifest.py test_knowledge_cache.py -q
python rag_rerank_demo.py
```

`rag_rerank_demo.py` 会展示向量初排分、关键词分和最终重排分，便于检查资料排序。

## 边界

航班、酒店与活动工具目前使用可预测的演示数据，用于验证编排和预算回路；接入真实供应商时应通过独立适配器注入凭据、超时、限流和报价校验，不能将演示报价当作实时数据。

要接入真实供应商，还需要扩展请求中的出行日期、乘客数、舱等/房型等信息，并按供应商合同实现 `quote_providers.py` 中的适配器。当前将 `TRAVEL_PROVIDER` 设置为非 `demo` 会失败关闭，防止误导用户。
