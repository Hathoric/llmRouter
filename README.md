# llmRouter

基于规则的 LLM 模型路由：根据任务类型、长度、成本等规则将请求路由到不同模型/端点。

## 项目结构

```
llmRouter/
├── config/
│   ├── rules.yaml    # 路由规则（优先级 + 条件 → target 模型）
│   └── models.yaml   # 模型/端点注册
├── src/
│   ├── router.py     # 路由入口
│   ├── rules/
│   │   ├── engine.py     # 规则引擎
│   │   └── conditions.py # 条件匹配（eq/gte/tags 等）
│   └── models/
│       └── registry.py   # 模型注册表
├── main.py           # 示例调用
└── requirements.txt
```

## 规则设计

- **规则** 在 `config/rules.yaml` 中配置，按 `priority` 从高到低匹配，**先匹配到的规则** 的 `target` 即为所选模型 id。
- **条件** 支持：
  - 简单相等：`task_type: chat`
  - 比较运算：`max_tokens: ["gte", 4000]`（支持 eq/ne/gt/gte/lt/lte/in/contains）
  - 标签：`tags: ["reasoning", "math"]`（请求 context 的 tags 包含其一即满足）

## 使用方式

```bash
pip install -r requirements.txt
python main.py
```

在代码中：

```python
from src.router import Router

router = Router()
# 可选：自定义规则/模型配置文件路径
# router = Router(rules_path="path/to/rules.yaml", models_path="path/to/models.yaml")

context = {
    "task_type": "chat",      # chat | completion
    "max_tokens": 500,
    "cost_tier": "low",       # low | medium | high
    "tags": ["reasoning"],    # 可选
}
result = router.route(context)
# result 包含 model_id, endpoint, name, provider, max_context_tokens 等
```

## 配置说明

- **rules.yaml**：增删改规则即可调整路由策略，无需改代码。
- **models.yaml**：`endpoint` 可写环境变量占位，如 `${OPENAI_API_BASE}`，运行时自动替换。

## 扩展

- 在 `conditions.py` 中增加新的比较符或条件类型。
- 在 `rules.yaml` 中增加新规则或新 `target`，并在 `models.yaml` 中注册对应模型。
