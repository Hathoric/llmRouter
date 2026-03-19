"""
使用 Router 调用 DeepSeek 的简单测试脚本。

运行前请确保：
- 已在 config/models.yaml 中配置了 deepseek-chat 模型，endpoint 指向 https://api.deepseek.com
- 已设置环境变量 DEEPSEEK_API_KEY 为你的 DeepSeek API Key

示例（PowerShell）：
  [Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "sk-xxxx", "User")
然后重新打开终端，再执行：
  conda activate llmrouter
  python -m tests.call_deepseek_demo
"""

import os
import json

import requests

from src.router import Router


def main() -> None:
    api_key = "sk-0e6f6d49fc3e40709103aaeae4ecf93a"
    if not api_key:
        raise RuntimeError("请先通过环境变量 DEEPSEEK_API_KEY 设置 DeepSeek API Key")

    router = Router()

    # 期望通过规则路由到 deepseek-chat（例如：task_type=chat, cost_tier=low）
    context = {
        "task_type": "chat",
        "cost_tier": "low",
        "tags": ["test"],
    }
    cfg = router.route(context)

    if cfg.get("error"):
        raise RuntimeError(f"路由失败: {cfg}")

    if cfg.get("provider") != "deepseek":
        raise RuntimeError(f"当前路由到的并非 DeepSeek 模型: {cfg}")

    endpoint = cfg.get("endpoint")
    if not endpoint:
        raise RuntimeError("DeepSeek 模型未配置 endpoint")

    # 约定 endpoint 为 https://api.deepseek.com
    url = endpoint.rstrip("/") + "/chat/completions"

    payload = {
        "model": cfg.get("model_id", "deepseek-chat"),
        "messages": [
            {"role": "user", "content": "用一句话自我介绍一下。"},
        ],
        "temperature": 0.7,
        "max_tokens": 256,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    print("原始响应：")
    print(json.dumps(data, ensure_ascii=False, indent=2))

    try:
        content = data["choices"][0]["message"]["content"]
        print("\n模型回复：")
        print(content)
    except Exception:
        print("\n无法按预期解析回复，请检查 DeepSeek 最新文档。")


if __name__ == "__main__":
    main()

