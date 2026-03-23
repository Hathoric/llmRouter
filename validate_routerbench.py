#!/usr/bin/env python3
"""
Use RouterBench to sanity-check your router (subset only).

This script supports:
- HF mode: download a small subset from HuggingFace.
- Offline mode: read a local routerbench converted dataset file (pkl/csv), avoiding network.

For each sampled task, it:
- builds per-model performance/cost,
- calls your local `Router.route()` to pick a model,
- compares chosen vs oracle (best accuracy, then lowest cost).

Notes:
- RouterBench model ids look like "gpt-4-1106-preview", etc.
  If they differ from your `config/models.yaml`, provide `--model-map-json`.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
from collections import defaultdict
from typing import Any


def _try_import_datasets():
    try:
        from datasets import get_dataset_config_names, load_dataset  # type: ignore

        return get_dataset_config_names, load_dataset
    except Exception as e:  # pragma: no cover
        raise SystemExit(
            "Missing dependency `datasets`. Install it first:\n"
            "  pip install datasets\n"
            f"Original import error: {e}"
        )


def _pick_first_key(item: dict[str, Any], candidates: list[str]) -> str | None:
    for k in candidates:
        if k in item:
            return k
    return None


def _heuristic_context_from_prompt(prompt: str, *, cost_tier: str) -> dict[str, Any]:
    lc = (prompt or "").lower()

    # Very rough: RouterBench prompts are usually single-turn tasks.
    # If you have chat-style prompts, role markers may exist.
    task_type = (
        "chat"
        if any(x in lc for x in ["assistant", "user:", "system:", "<|user|>", "<|assistant|>"])
        else "completion"
    )

    tags: list[str] = []
    if any(x in lc for x in ["reason", "explain", "step", "chain of thought"]):
        tags.append("reasoning")
    # Rough math heuristic: digits + common operators.
    if re.search(r"\d", lc) and any(op in lc for op in ["+", "-", "*", "/", "=", "^"]):
        tags.append("math")

    # token estimate: ~1.3 words -> tokens (rough sanity only).
    # Your rules.yaml uses thresholds like 4000, so this should be treated as approximate.
    approx_tokens = max(1, int(len(prompt.split()) * 1.3))
    max_tokens = min(8000, approx_tokens)

    # Your current rules use cost_tier for cheaper routing.
    # RouterBench dataset may not contain an explicit "cost_tier" label, so we set it externally.
    return {
        "task_type": task_type,
        "max_tokens": max_tokens,
        "tags": tags,
        "cost_tier": cost_tier,
    }


def _oracle_select(perf_by_model: dict[str, float], cost_by_model: dict[str, float]) -> tuple[str, float, float]:
    if not perf_by_model:
        return "no_model_correct", 0.0, 0.0
    max_perf = max(perf_by_model.values())
    if max_perf <= 0.0 + 1e-12:
        return "no_model_correct", 0.0, 0.0
    # Choose cheapest among those with max performance (tie within epsilon).
    eps = 1e-9
    best_models = [m for m, p in perf_by_model.items() if abs(p - max_perf) <= eps]
    chosen = min(best_models, key=lambda m: float(cost_by_model.get(m, math.inf)))
    return chosen, float(max_perf), float(cost_by_model.get(chosen, 0.0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-path",
        default=None,
        help="Offline mode: path to local routerbench dataset (.pkl/.csv) in converted wide format.",
    )
    parser.add_argument(
        "--data-split",
        default=None,
        help="Offline mode (best-effort): if dataset has eval_name, only keep rows whose eval_name starts with this prefix.",
    )
    parser.add_argument("--hf-dataset", default="withmartian/routerbench")
    parser.add_argument("--hf-config", default=None, help="Optional dataset config name (0-shot/5-shot or similar).")
    parser.add_argument("--split", default="train", help="Dataset split to sample from.")
    parser.add_argument("--n-tasks", type=int, default=50, help="How many unique tasks to sample.")
    parser.add_argument("--scan-records", type=int, default=3000, help="Max records to scan to find n-tasks.")
    parser.add_argument("--seed", type=int, default=42)

    parser.add_argument(
        "--router-rules-path",
        default="config/rules.yaml",
        help="Path to your rules.yaml (relative to this script).",
    )
    parser.add_argument(
        "--router-models-path",
        default="config/models.yaml",
        help="Path to your models.yaml (relative to this script).",
    )
    parser.add_argument(
        "--default-model-id",
        default="gpt-3.5-turbo-1106",
        help="Router fallback model id (must exist in config/models.yaml).",
    )

    parser.add_argument(
        "--cost-tier",
        default="low",
        choices=["low", "medium", "high"],
        help="Heuristic setting for your router input context.",
    )
    parser.add_argument(
        "--model-map-json",
        default=None,
        help="Optional JSON mapping your model_id -> RouterBench model_name. "
        "Useful when your router outputs ids not present in RouterBench data.",
    )

    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    rules_path = os.path.join(script_dir, args.router_rules_path)
    models_path = os.path.join(script_dir, args.router_models_path)

    rng = random.Random(args.seed)

    model_map: dict[str, str] = {}
    if args.model_map_json:
        with open(args.model_map_json, "r", encoding="utf-8") as f:
            model_map = json.load(f)
        print(f"[info] loaded model map with {len(model_map)} entries")

    # Build tasks: task_id -> prompt, perf_by_model, cost_by_model
    tasks: dict[str, dict[str, Any]] = {}
    task_ids: list[str] = []

    if args.data_path:
        # Offline mode: local converted wide-format (.pkl/.csv)
        import pandas as pd  # type: ignore

        data_path = args.data_path
        print(f"[info] offline dataset path: {data_path}")
        if data_path.endswith(".csv"):
            df = pd.read_csv(data_path)
        else:
            df = pd.read_pickle(data_path)

        if df is None or len(df) == 0:
            raise SystemExit("Loaded offline dataset is empty.")

        cols = list(df.columns)
        prompt_col = "prompt" if "prompt" in cols else None
        if not prompt_col:
            prompt_candidates = [c for c in cols if "prompt" in str(c).lower()]
            prompt_col = prompt_candidates[0] if prompt_candidates else None
        if not prompt_col:
            raise SystemExit(f"Could not find `prompt` column in offline dataset. Columns sample: {cols[:40]}")

        sample_id_col = "sample_id" if "sample_id" in cols else None

        models_to_route = [
            str(c).replace("|model_response", "")
            for c in cols
            if isinstance(c, str) and "|model_response" in c
        ]
        if not models_to_route:
            raise SystemExit(
                "Offline mode expects converted wide-format with columns like `<model>|model_response`. "
                "Could not infer models_to_route from columns."
            )

        if args.data_split and "eval_name" in cols:
            df = df[df["eval_name"].astype(str).str.startswith(args.data_split)].copy()
            print(f"[info] after eval_name prefix filter: {len(df)} rows")

        k = min(args.n_tasks, len(df))
        if k <= 0:
            raise SystemExit("Offline dataset has no rows after filtering.")

        sampled_df = df.sample(n=k, random_state=args.seed) if len(df) > k else df
        for _, row in sampled_df.iterrows():
            prompt = str(row.get(prompt_col, ""))
            task_id = str(row.get(sample_id_col)) if sample_id_col else f"prompt::{hash(prompt)}"

            perf_by_model: dict[str, float] = {}
            cost_by_model: dict[str, float] = {}
            for m in models_to_route:
                perf_by_model[m] = float(row.get(m, 0.0) or 0.0)
                cost_by_model[m] = float(row.get(f"{m}|total_cost", 0.0) or 0.0)

            tasks[task_id] = {
                "prompt": prompt,
                "perf_by_model": perf_by_model,
                "cost_by_model": cost_by_model,
                "eval_name": row.get("eval_name", None),
            }

        if not tasks:
            raise SystemExit("No tasks collected from offline dataset.")

        task_ids = list(tasks.keys())
    else:
        # HF mode: download a small subset from HuggingFace
        get_dataset_config_names, load_dataset = _try_import_datasets()

        configs = get_dataset_config_names(args.hf_dataset)
        if not configs:
            raise SystemExit(f"No dataset configs found for {args.hf_dataset}")

        if args.hf_config is None:
            # Use the first config as a reasonable default.
            hf_config = configs[0]
        else:
            hf_config = args.hf_config

        print(f"[info] HF dataset: {args.hf_dataset}, config: {hf_config}, split: {args.split}")
        print(f"[info] available configs: {configs}")

        ds = load_dataset(args.hf_dataset, hf_config, split=args.split)
        if len(ds) == 0:
            raise SystemExit("Dataset split is empty.")

        # Detect columns from the first record.
        first = ds[0]
        prompt_col = _pick_first_key(first, ["prompt", "input", "question"])
        model_col = _pick_first_key(first, ["model_name", "model", "model_id"])
        perf_col = _pick_first_key(first, ["performance", "accuracy", "is_correct"])
        cost_col = _pick_first_key(first, ["cost", "estimated_cost", "total_cost"])
        sample_id_col = _pick_first_key(first, ["sample_id", "task_id", "id", "idx"])

        if not prompt_col or not model_col or not perf_col or not cost_col:
            raise SystemExit(
                "Could not detect required columns in RouterBench dataset. "
                f"Found keys: {list(first.keys())}\n"
                "Need prompt/model_name/performance/cost."
            )

        print(
            f"[info] detected columns: prompt={prompt_col}, model={model_col}, "
            f"performance={perf_col}, cost={cost_col}, sample_id={sample_id_col}"
        )

        # Build per-task wide dict: task_id -> prompt, perf_by_model, cost_by_model
        record_iter = ds.take(min(args.scan_records, len(ds)))
        for rec in record_iter:
            prompt = rec.get(prompt_col, "")
            model_name = str(rec[model_col])
            perf_raw = rec.get(perf_col, 0.0)
            cost_raw = rec.get(cost_col, 0.0)

            try:
                perf = float(perf_raw)
            except Exception:
                perf = 0.0

            try:
                cost = float(cost_raw)
            except Exception:
                cost = 0.0

            task_id = str(rec.get(sample_id_col, "")) if sample_id_col else None
            if not task_id:
                # Fallback: group by (prompt) only (may collide, but OK for quick sanity).
                task_id = f"prompt::{hash(prompt)}"

            if task_id not in tasks:
                tasks[task_id] = {
                    "prompt": prompt,
                    "perf_by_model": {},
                    "cost_by_model": {},
                    # optional metadata if present
                    "eval_name": rec.get("eval_name", None),
                }

            tasks[task_id]["perf_by_model"][model_name] = perf
            tasks[task_id]["cost_by_model"][model_name] = cost

            if len(tasks) >= args.n_tasks:
                break

        if not tasks:
            raise SystemExit("No tasks collected. Try increasing --scan-records.")

        # Randomly subsample exactly n-tasks for stable results.
        task_ids = list(tasks.keys())
        if len(task_ids) > args.n_tasks:
            rng.shuffle(task_ids)
            task_ids = task_ids[: args.n_tasks]

    models_seen = set()
    for tid in task_ids:
        models_seen.update(tasks[tid]["perf_by_model"].keys())
    preview_models = sorted(models_seen)[:30]
    print(f"[info] model_name preview in sampled tasks (up to 30): {preview_models}")

    # Import your router.
    from src.router import Router

    router = Router(rules_path=rules_path, models_path=models_path, default_model_id=args.default_model_id)

    chosen_perf_list: list[float] = []
    oracle_perf_list: list[float] = []
    chosen_cost_sum = 0.0
    oracle_cost_sum = 0.0

    missing_model_count = 0
    error_count = 0
    chosen_matches_oracle = 0

    for task_id in task_ids:
        task = tasks[task_id]
        prompt = task["prompt"]
        perf_by_model = task["perf_by_model"]
        cost_by_model = task["cost_by_model"]

        context = _heuristic_context_from_prompt(prompt, cost_tier=args.cost_tier)
        routed = router.route(context)
        if "error" in routed:
            error_count += 1
            continue

        predicted_model = str(routed.get("model_id", ""))
        predicted_model_rb = model_map.get(predicted_model, predicted_model)

        if predicted_model_rb not in perf_by_model:
            missing_model_count += 1
            continue

        chosen_perf = float(perf_by_model[predicted_model_rb])
        chosen_cost = float(cost_by_model.get(predicted_model_rb, 0.0))

        oracle_model, oracle_perf, oracle_cost = _oracle_select(perf_by_model, cost_by_model)
        chosen_matches_oracle += int(predicted_model_rb == oracle_model)

        chosen_perf_list.append(chosen_perf)
        oracle_perf_list.append(oracle_perf)
        chosen_cost_sum += chosen_cost
        oracle_cost_sum += oracle_cost

    n_ok = len(chosen_perf_list)
    if n_ok == 0:
        raise SystemExit(
            "No valid samples for evaluation (model id mismatch likely). "
            "Check whether your router outputs model ids that exist in RouterBench model_name."
        )

    chosen_acc = sum(chosen_perf_list) / n_ok
    oracle_acc = sum(oracle_perf_list) / n_ok
    avg_chosen_cost = chosen_cost_sum / n_ok
    avg_oracle_cost = oracle_cost_sum / n_ok

    print("\n=== RouterBench sanity result (subset) ===")
    print(f"[n_tasks requested] {args.n_tasks}")
    print(f"[n_tasks evaluated] {n_ok} (skipped model-mismatch: {missing_model_count}, router errors: {error_count})")
    print(f"[accuracy chosen]  {chosen_acc:.4f}")
    print(f"[accuracy oracle]  {oracle_acc:.4f}")
    print(f"[chosen avg cost]  ${avg_chosen_cost:.6f}")
    print(f"[oracle avg cost]  ${avg_oracle_cost:.6f}")
    print(f"[match oracle rate] {chosen_matches_oracle / n_ok:.4f}")

    # Quick failure summary for interpretation
    wrong = sum(1 for p in chosen_perf_list if p <= 0.0 + 1e-12)
    wrong_rate = wrong / n_ok
    print(f"[chosen wrong rate] {wrong_rate:.4f}")


if __name__ == "__main__":
    main()

