# Python 版本

本版本已扩展 LangGraph、Qdrant RAG、Redis 和 SSE。请从仓库根目录阅读 [启动说明](../README.md) 和 [学习手册](../docs/LEARNING_GUIDE.md)。

在仓库根目录执行：

```powershell
uv sync --frozen
uv run uvicorn api.app:app --app-dir python --host 127.0.0.1 --port 8000
```

网页位于 http://127.0.0.1:8000，接口文档位于 /docs。

上游 CLI 仍可从 python 目录运行 python main.py，它只演示规则 Pipeline；新功能通过 FastAPI 入口使用。
上游 Streamlit 页面属于可选参考，安装 uv sync --group ui 后可使用，不包含新 RAG 与任务事件交互。
