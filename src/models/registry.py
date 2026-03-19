"""
模型注册表：从 YAML 加载模型配置，按 id 返回 endpoint 等信息。
"""
from pathlib import Path
from typing import Any

import yaml


def load_models(config_path: str | Path) -> dict[str, dict[str, Any]]:
    """从 YAML 文件加载 models 字典。"""
    path = Path(config_path)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("models") or {}


class ModelRegistry:
    """模型注册表。"""

    def __init__(
        self,
        models: dict[str, dict[str, Any]] | None = None,
        config_path: str | Path | None = None,
    ):
        if models is not None:
            self._models = dict(models)
        elif config_path is not None:
            self._models = load_models(config_path)
        else:
            self._models = {}

    def get(self, model_id: str) -> dict[str, Any] | None:
        """获取模型配置，支持环境变量展开 endpoint。"""
        info = self._models.get(model_id)
        if not info:
            return None
        import os
        out = dict(info)
        endpoint = out.get("endpoint") or ""
        if isinstance(endpoint, str) and "${" in endpoint:
            for key, value in os.environ.items():
                endpoint = endpoint.replace("${" + key + "}", value)
            out["endpoint"] = endpoint
        return out

    def list_ids(self) -> list[str]:
        """返回所有已注册的 model id。"""
        return list(self._models.keys())
