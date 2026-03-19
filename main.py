"""
示例入口：演示基于规则的模型路由用法。
"""
from src.router import Router


def main() -> None:
    router = Router()

    # 示例 1：对话任务 -> 走默认对话规则
    ctx1 = {"task_type": "chat", "max_tokens": 500}
    r1 = router.route(ctx1)
    print("chat 默认:", r1.get("model_id"), r1.get("name"))

    # 示例 2：带推理标签 -> 走推理规则
    ctx2 = {"task_type": "chat", "tags": ["reasoning", "math"]}
    r2 = router.route(ctx2)
    print("推理任务:", r2.get("model_id"), r2.get("name"))

    # 示例 3：长文本 + 低成本
    ctx3 = {"task_type": "completion", "max_tokens": 8000, "cost_tier": "low"}
    r3 = router.route(ctx3)
    print("长文本经济:", r3.get("model_id"), r3.get("name"))


if __name__ == "__main__":
    main()
