"""
规则引擎：加载规则配置，按优先级排序，返回第一个匹配的 target（模型 id）。
"""
from pathlib import Path
from typing import Any

import yaml

from .conditions import match_conditions


def load_rules(config_path: str | Path) -> list[dict[str, Any]]:
    """从 YAML 文件加载 rules 列表，并按 priority 降序排序。"""
    path = Path(config_path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = data.get("rules") or []
    return sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)


class RuleEngine:
    """基于规则的匹配引擎。"""

    def __init__(self, rules: list[dict[str, Any]] | None = None, config_path: str | Path | None = None):
        if rules is not None:
            self._rules = sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)
        elif config_path is not None:
            self._rules = load_rules(config_path)
        else:
            self._rules = []

    def resolve(self, context: dict[str, Any]) -> str | None:
        """
        根据上下文解析出目标模型 id。
        context 示例: {"task_type": "chat", "max_tokens": 500, "cost_tier": "low", "tags": ["reasoning"]}
        """
        for rule in self._rules:
            if match_conditions(rule.get("conditions") or {}, context):
                return rule.get("target")
        return None
