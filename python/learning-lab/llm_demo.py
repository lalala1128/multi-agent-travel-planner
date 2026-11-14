import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


# 读取当前目录下的配置文件
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

api_key = os.getenv("DEEPSEEK_API_KEY")
base_url = os.getenv(
    "DEEPSEEK_BASE_URL",
    "https://api.deepseek.com",
)
model = os.getenv(
    "DEEPSEEK_MODEL",
    "deepseek-flash",
)

if not api_key:
    raise ValueError("没有配置 DEEPSEEK_API_KEY")

# 准备发送给模型的请求
payload = {
    "model": model,
    "messages": [
        {
            "role": "system",
            "content": "你是旅游规划助手，请用中文简短回答。",
        },
        {
            "role": "user",
            "content": "请只回复：模型连接成功",
        },
    ],
    "thinking": {"type": "disabled"},
    "max_tokens": 128,
    "stream": False,
}

# 发起 HTTP 请求
with httpx.Client(timeout=60) as client:
    response = client.post(
        url=f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
        },
        json=payload,
    )

    response.raise_for_status()
    data = response.json()

answer = data["choices"][0]["message"]["content"]

print("模型回答：", answer)