"""
规则条件匹配：根据请求上下文判断单条规则的 conditions 是否满足。
"""
from typing import Any


def _compare(op: str, actual: Any, expected: Any) -> bool:
    """比较运算符：eq, ne, gt, gte, lt, lte, in, contains."""
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "gt":
        return (actual is not None and expected is not None) and actual > expected
    if op == "gte":
        return (actual is not None and expected is not None) and actual >= expected
    if op == "lt":
        return (actual is not None and expected is not None) and actual < expected
    if op == "lte":
        return (actual is not None and expected is not None) and actual <= expected
    if op == "in":
        return actual in expected if isinstance(expected, (list, tuple)) else False
    if op == "contains":
        return expected in actual if isinstance(actual, (list, tuple)) else False
    return False


def match_conditions(conditions: dict[str, Any], context: dict[str, Any]) -> bool:
    """
    判断 context 是否满足 conditions。
    - 简单值：conditions.task_type == context.task_type
    - 带运算符：[op, value] 如 ["gte", 4000] 表示 context 对应字段 >= 4000
    - tags：context.tags 包含 conditions.tags 中任意即满足（若 conditions 有 tags）
    """
    if not conditions:
        return True

    for key, expected in conditions.items():
        actual = context.get(key)
        if expected is None:
            if actual is not None:
                return False
            continue

        # 运算符形式 [op, value]
        if isinstance(expected, (list, tuple)) and len(expected) == 2:
            op, val = expected[0], expected[1]
            if op in ("eq", "ne", "gt", "gte", "lt", "lte", "in", "contains"):
                if not _compare(op, actual, val):
                    return False
                continue

        # tags 特殊：期望的 tags 中任意一个在 context.tags 即满足
        if key == "tags":
            ctx_tags = actual if isinstance(actual, (list, tuple)) else []
            want_tags = expected if isinstance(expected, (list, tuple)) else [expected]
            if not any(t in ctx_tags for t in want_tags):
                return False
            continue

        # 直接相等
        if actual != expected:
            return False

    return True
