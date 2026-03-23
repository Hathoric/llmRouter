#!/usr/bin/env python3
"""
Analyze RouterBench dataset file (offline .pkl/.csv) and produce:
- field/schema summary
- missing-value rates
- numeric stats
- categorical top values
- sample rows and sample values per field

Outputs:
- console summary
- markdown report
- json structured report
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Any
import matplotlib.pyplot as plt  # type: ignore
import pandas as pd  # type: ignore

def _to_py_scalar(value: Any) -> Any:
    # Convert pandas/numpy scalars to plain Python values for JSON serialization.
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _format_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _infer_semantic_groups(columns: list[str]) -> dict[str, list[str]]:
    groups = {
        "id_like": [],
        "text_like": [],
        "model_performance": [],
        "model_response": [],
        "model_cost": [],
        "other": [],
    }
    for c in columns:
        if c in {"sample_id", "eval_name", "source"} or c.endswith("_id"):
            groups["id_like"].append(c)
        elif "prompt" in c or "question" in c:
            groups["text_like"].append(c)
        elif c.endswith("|model_response"):
            groups["model_response"].append(c)
        elif c.endswith("|total_cost"):
            groups["model_cost"].append(c)
        elif "|" not in c and c not in {"prompt", "eval_name", "sample_id", "source", "embedding"}:
            groups["model_performance"].append(c)
        else:
            groups["other"].append(c)
    return groups


def build_report(df, dataset_path: str, sample_rows: int, top_k: int) -> dict[str, Any]:
    import pandas as pd  # type: ignore

    n_rows, n_cols = df.shape
    columns = [str(c) for c in df.columns]
    dtypes = {str(c): str(df[c].dtype) for c in df.columns}
    null_count = df.isna().sum().to_dict()
    null_rate = {str(k): float(v) / max(1, n_rows) for k, v in null_count.items()}

    numeric_cols = [str(c) for c in df.select_dtypes(include=["number"]).columns]
    object_cols = [str(c) for c in df.select_dtypes(include=["object", "string"]).columns]

    numeric_stats: dict[str, dict[str, Any]] = {}
    for c in numeric_cols:
        s = df[c]
        numeric_stats[c] = {
            "count": int(s.count()),
            "mean": float(s.mean()) if s.count() else None,
            "std": float(s.std()) if s.count() else None,
            "min": float(s.min()) if s.count() else None,
            "p25": float(s.quantile(0.25)) if s.count() else None,
            "p50": float(s.quantile(0.5)) if s.count() else None,
            "p75": float(s.quantile(0.75)) if s.count() else None,
            "max": float(s.max()) if s.count() else None,
        }

    categorical_top_values: dict[str, list[dict[str, Any]]] = {}
    for c in object_cols:
        vc = df[c].value_counts(dropna=False).head(top_k)
        rows = []
        for value, cnt in vc.items():
            rows.append(
                {
                    "value": _to_py_scalar(value),
                    "count": int(cnt),
                    "rate": float(cnt) / max(1, n_rows),
                }
            )
        categorical_top_values[c] = rows

    sample_value_by_column: dict[str, list[Any]] = {}
    for c in columns:
        values = []
        # Keep examples compact and deterministic.
        for v in df[c].dropna().head(3).tolist():
            v = _to_py_scalar(v)
            if isinstance(v, str) and len(v) > 180:
                v = v[:180] + "...(truncated)"
            values.append(v)
        sample_value_by_column[c] = values

    groups = _infer_semantic_groups(columns)

    # Model-level quick stats if this is converted RouterBench wide format.
    model_response_cols = groups["model_response"]
    model_cost_cols = groups["model_cost"]
    perf_cols = groups["model_performance"]
    models_detected = sorted({c.replace("|model_response", "") for c in model_response_cols})

    model_cost_summary: dict[str, dict[str, float | None]] = {}
    for m in models_detected:
        col = f"{m}|total_cost"
        if col in df.columns:
            s = df[col]
            model_cost_summary[m] = {
                "mean_cost": float(s.mean()) if s.count() else None,
                "median_cost": float(s.median()) if s.count() else None,
            }

    model_performance_summary: dict[str, dict[str, float | None]] = {}
    for m in perf_cols:
        s = df[m]
        if str(s.dtype).startswith(("float", "int", "bool")):
            model_performance_summary[m] = {
                "mean_performance": float(pd.to_numeric(s, errors="coerce").mean())
                if s.count()
                else None
            }

    sample_rows_data = []
    for _, row in df.head(sample_rows).iterrows():
        row_dict = {}
        for c in columns:
            v = _to_py_scalar(row[c])
            if isinstance(v, str) and len(v) > 240:
                v = v[:240] + "...(truncated)"
            row_dict[c] = v
        sample_rows_data.append(row_dict)

    report = {
        "dataset_path": dataset_path,
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "shape": {"rows": n_rows, "columns": n_cols},
        "columns": columns,
        "dtypes": dtypes,
        "missing": {"null_count": null_count, "null_rate": null_rate},
        "numeric_columns": numeric_cols,
        "object_columns": object_cols,
        "numeric_stats": numeric_stats,
        "categorical_top_values": categorical_top_values,
        "sample_value_by_column": sample_value_by_column,
        "semantic_groups": groups,
        "routerbench_like_summary": {
            "models_detected_count": len(models_detected),
            "models_detected": models_detected,
            "performance_columns_count": len(perf_cols),
            "response_columns_count": len(model_response_cols),
            "cost_columns_count": len(model_cost_cols),
            "model_cost_summary": model_cost_summary,
            "model_performance_summary": model_performance_summary,
        },
        "sample_rows": sample_rows_data,
    }
    return report


def to_markdown(report: dict[str, Any], top_k: int) -> str:
    shape = report["shape"]
    lines: list[str] = []
    lines.append("# RouterBench Dataset Analysis")
    lines.append("")
    lines.append(f"- Dataset: `{report['dataset_path']}`")
    lines.append(f"- Generated at (UTC): `{report['generated_at_utc']}`")
    lines.append(f"- Rows: `{shape['rows']}`")
    lines.append(f"- Columns: `{shape['columns']}`")
    lines.append("")
    lines.append("## Column Overview")
    lines.append("")
    lines.append("| Column | DType | Null Rate | Example Values |")
    lines.append("|---|---|---:|---|")
    for c in report["columns"]:
        dtype = report["dtypes"][c]
        nr = _format_pct(float(report["missing"]["null_rate"].get(c, 0.0)))
        ex = report["sample_value_by_column"].get(c, [])
        ex_text = "; ".join([str(v) for v in ex]) if ex else "-"
        lines.append(f"| `{c}` | `{dtype}` | {nr} | {ex_text} |")
    lines.append("")
    lines.append("## Semantic Groups")
    lines.append("")
    for g, cols in report["semantic_groups"].items():
        lines.append(f"- `{g}`: {len(cols)}")
    lines.append("")
    rb = report["routerbench_like_summary"]
    lines.append("## RouterBench-Like Summary")
    lines.append("")
    lines.append(f"- Models detected: `{rb['models_detected_count']}`")
    lines.append(f"- Performance columns: `{rb['performance_columns_count']}`")
    lines.append(f"- Response columns: `{rb['response_columns_count']}`")
    lines.append(f"- Cost columns: `{rb['cost_columns_count']}`")
    lines.append("")
    plot_files = report.get("plot_files") or []
    if plot_files:
        lines.append("## Visualizations")
        lines.append("")
        for p in plot_files:
            lines.append(f"- `{p}`")
        lines.append("")
    if rb["models_detected"]:
        lines.append("### Models")
        lines.append("")
        for m in rb["models_detected"]:
            lines.append(f"- `{m}`")
        lines.append("")
    lines.append("## Top Values (Object Columns)")
    lines.append("")
    for c, entries in report["categorical_top_values"].items():
        lines.append(f"### `{c}`")
        lines.append("")
        if not entries:
            lines.append("- (empty)")
        else:
            for e in entries[:top_k]:
                lines.append(f"- `{e['value']}`: {e['count']} ({_format_pct(float(e['rate']))})")
        lines.append("")
    lines.append("## Sample Rows")
    lines.append("")
    for i, row in enumerate(report["sample_rows"], start=1):
        lines.append(f"### Row {i}")
        lines.append("")
        for k, v in row.items():
            lines.append(f"- `{k}`: `{v}`")
        lines.append("")
    return "\n".join(lines)


def create_plots(df, report: dict[str, Any], plot_dir: str, top_k_eval: int = 15) -> list[str]:

    os.makedirs(plot_dir, exist_ok=True)
    out_paths: list[str] = []

    # 1) eval_name distribution (top-k)
    if "eval_name" in df.columns:
        vc = df["eval_name"].astype(str).value_counts().head(top_k_eval)
        if len(vc) > 0:
            plt.figure(figsize=(11, 5))
            vc.sort_values(ascending=False).plot(kind="bar")
            plt.title(f"Top {min(top_k_eval, len(vc))} eval_name Distribution")
            plt.ylabel("Count")
            plt.tight_layout()
            p = os.path.join(plot_dir, "eval_name_top_distribution.png")
            plt.savefig(p, dpi=150)
            plt.close()
            out_paths.append(p)

    rb = report.get("routerbench_like_summary", {})
    models = rb.get("models_detected", [])

    # 2) per-model average performance
    perf_pairs = []
    for m in models:
        if m in df.columns:
            s = pd.to_numeric(df[m], errors="coerce")
            perf_pairs.append((m, float(s.mean())))
    if perf_pairs:
        perf_pairs = sorted(perf_pairs, key=lambda x: x[1], reverse=True)
        x = [k for k, _ in perf_pairs]
        y = [v for _, v in perf_pairs]
        plt.figure(figsize=(12, 5))
        plt.bar(x, y)
        plt.title("Average Performance by Model")
        plt.ylabel("Mean performance")
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        p = os.path.join(plot_dir, "model_avg_performance.png")
        plt.savefig(p, dpi=150)
        plt.close()
        out_paths.append(p)

    # 3) per-model average cost (log scale)
    cost_pairs = []
    for m in models:
        c = f"{m}|total_cost"
        if c in df.columns:
            s = pd.to_numeric(df[c], errors="coerce")
            cost_pairs.append((m, float(s.mean())))
    if cost_pairs:
        cost_pairs = sorted(cost_pairs, key=lambda x: x[1], reverse=True)
        x = [k for k, _ in cost_pairs]
        y = [max(v, 1e-12) for _, v in cost_pairs]
        plt.figure(figsize=(12, 5))
        plt.bar(x, y)
        plt.yscale("log")
        plt.title("Average Cost by Model (log scale)")
        plt.ylabel("Mean total_cost")
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        p = os.path.join(plot_dir, "model_avg_cost_log.png")
        plt.savefig(p, dpi=150)
        plt.close()
        out_paths.append(p)

    # 4) cost-performance scatter
    if perf_pairs and cost_pairs:
        perf_map = dict(perf_pairs)
        cost_map = dict(cost_pairs)
        common = [m for m in models if m in perf_map and m in cost_map]
        if common:
            xs = [cost_map[m] for m in common]
            ys = [perf_map[m] for m in common]
            plt.figure(figsize=(8, 6))
            plt.scatter(xs, ys)
            for m in common:
                plt.annotate(m, (cost_map[m], perf_map[m]), fontsize=8)
            plt.xscale("log")
            plt.xlabel("Mean cost (log scale)")
            plt.ylabel("Mean performance")
            plt.title("Model Cost vs Performance")
            plt.tight_layout()
            p = os.path.join(plot_dir, "model_cost_vs_performance.png")
            plt.savefig(p, dpi=150)
            plt.close()
            out_paths.append(p)

    # 5) prompt length distribution (if prompt exists)
    if "prompt" in df.columns:
        prompt_len = df["prompt"].astype(str).apply(lambda x: len(x.split()))
        if len(prompt_len) > 0:
            plt.figure(figsize=(10, 5))
            plt.hist(prompt_len, bins=50)
            plt.title("Prompt Length Distribution (word count)")
            plt.xlabel("Words per prompt")
            plt.ylabel("Frequency")
            plt.tight_layout()
            p = os.path.join(plot_dir, "prompt_length_distribution.png")
            plt.savefig(p, dpi=150)
            plt.close()
            out_paths.append(p)

    return out_paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-path",
        default="dataset/routerbench_0shot.pkl",
        help="Path to local dataset file (.pkl or .csv).",
    )
    parser.add_argument(
        "--out-dir",
        default="analysis",
        help="Output directory for analysis files.",
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=5,
        help="How many sample rows to include.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Top-k values for categorical columns.",
    )
    parser.add_argument(
        "--with-plots",
        action="store_true",
        help="Generate PNG visualizations for the dataset profile.",
    )
    args = parser.parse_args()

    import pandas as pd  # type: ignore

    if not os.path.exists(args.data_path):
        raise SystemExit(f"Data file not found: {args.data_path}")

    if args.data_path.endswith(".csv"):
        df = pd.read_csv(args.data_path)
    else:
        df = pd.read_pickle(args.data_path)

    report = build_report(df, dataset_path=args.data_path, sample_rows=args.sample_rows, top_k=args.top_k)

    plot_paths: list[str] = []
    if args.with_plots:
        plot_dir = os.path.join(args.out_dir, "plots")
        plot_paths = create_plots(df, report=report, plot_dir=plot_dir)
        # Save relative paths to keep report portable.
        report["plot_files"] = [os.path.relpath(p, start=os.getcwd()) for p in plot_paths]

    md = to_markdown(report, top_k=args.top_k)

    os.makedirs(args.out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.data_path))[0]
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    json_path = os.path.join(args.out_dir, f"{stem}_analysis_{ts}.json")
    md_path = os.path.join(args.out_dir, f"{stem}_analysis_{ts}.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    # Console summary
    rb = report["routerbench_like_summary"]
    print("[done] Dataset analysis generated")
    print(f"[path] json: {json_path}")
    print(f"[path] md:   {md_path}")
    print(f"[shape] rows={report['shape']['rows']}, cols={report['shape']['columns']}")
    print(
        "[routerbench] models_detected="
        f"{rb['models_detected_count']}, perf_cols={rb['performance_columns_count']}, "
        f"resp_cols={rb['response_columns_count']}, cost_cols={rb['cost_columns_count']}"
    )
    if plot_paths:
        print(f"[plots] generated: {len(plot_paths)}")
        for p in plot_paths:
            print(f"[plot] {p}")


if __name__ == "__main__":
    main()

