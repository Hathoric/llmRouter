"""
路由入口：结合规则引擎与模型注册表，根据请求上下文返回目标模型配置。
"""
from pathlib import Path
from typing import Any

from .rules.engine import RuleEngine
from .models.registry import ModelRegistry


class Router:
    """基于规则的模型路由器。"""

    def __init__(
        self,
        rules_path: str | Path | None = None,
        models_path: str | Path | None = None,
        default_model_id: str | None = None,
    ):
        base = Path(__file__).resolve().parent.parent
        rules_path = rules_path or base / "config" / "rules.yaml"
        models_path = models_path or base / "config" / "models.yaml"

        self._engine = RuleEngine(config_path=rules_path)
        self._registry = ModelRegistry(config_path=models_path)
        self._default_model_id = default_model_id or "gpt-3.5-turbo-1106"

    def route(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        根据上下文做路由，返回目标模型的完整配置（含 endpoint 等）。
        context 常用字段: task_type, max_tokens, cost_tier, tags
        """
        model_id = self._engine.resolve(context)
        if model_id is None:
            model_id = self._default_model_id

        info = self._registry.get(model_id)
        if info is None:
            return {"model_id": model_id, "error": f"model not found: {model_id}"}
        info["model_id"] = model_id
        return info
