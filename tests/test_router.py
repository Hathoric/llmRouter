"""路由与规则匹配的简单测试。"""
import pytest
from src.router import Router
from src.rules.conditions import match_conditions


def test_match_conditions_empty():
    assert match_conditions({}, {"task_type": "chat"}) is True
    assert match_conditions({"task_type": "chat"}, {"task_type": "chat"}) is True
    assert match_conditions({"task_type": "chat"}, {"task_type": "completion"}) is False


def test_match_conditions_operators():
    assert match_conditions({"max_tokens": ["gte", 4000]}, {"max_tokens": 5000}) is True
    assert match_conditions({"max_tokens": ["gte", 4000]}, {"max_tokens": 3000}) is False


def test_match_conditions_tags():
    assert match_conditions({"tags": ["reasoning"]}, {"tags": ["reasoning", "math"]}) is True
    assert match_conditions({"tags": ["reasoning"]}, {"tags": ["other"]}) is False


def test_router_returns_model_info():
    router = Router()
    r = router.route({"task_type": "chat"})
    assert "model_id" in r
    assert "endpoint" in r or "error" in r
