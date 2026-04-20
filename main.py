"""
Dataset 驱动的 Query 侧原型增量学习最小入口。

功能：
1) 从本地 dataset 读取 prompt + label（默认使用 eval_name 作为标签）
2) 初始化子原型空间
3) 跑一个训练 step（打通 L_sup/L_supcon/L_dpl/L_ood）
4) 对若干 query 做推理，输出需求向量形状与 OOD 分数
"""
from __future__ import annotations

import argparse
from typing import Any

import pandas as pd
import torch

from query_side import QuerySideConfig, QuerySidePipeline


def _load_df(path: str) -> pd.DataFrame:
    if path.endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_pickle(path)


def _pick_label_col(df: pd.DataFrame, preferred: str | None) -> str:
    if preferred and preferred in df.columns:
        return preferred
    for c in ["eval_name", "task", "label", "category"]:
        if c in df.columns:
            return c
    raise ValueError("未找到标签列，请通过 --label-col 指定。")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", default="dataset/routerbench_0shot.pkl")
    parser.add_argument("--text-col", default="prompt")
    parser.add_argument("--label-col", default="eval_name")
    parser.add_argument("--max-samples", type=int, default=800)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--total-prototypes", type=int, default=300)
    args = parser.parse_args()

    df = _load_df(args.data_path)
    if df is None or len(df) == 0:
        raise SystemExit("dataset 为空。")
    if args.text_col not in df.columns:
        raise SystemExit(f"文本列不存在: {args.text_col}")

    label_col = _pick_label_col(df, args.label_col)
    use_cols = [args.text_col, label_col]
    clean_df = df[use_cols].dropna().copy()
    if len(clean_df) == 0:
        raise SystemExit("文本/标签列为空，无法训练。")

    if len(clean_df) > args.max_samples:
        clean_df = clean_df.sample(n=args.max_samples, random_state=42)

    texts = clean_df[args.text_col].astype(str).tolist()
    labels_cat = clean_df[label_col].astype("category")
    labels = torch.tensor(labels_cat.cat.codes.values, dtype=torch.long)
    num_known_tasks = int(labels.max().item()) + 1

    cfg = QuerySideConfig(
        num_known_tasks=num_known_tasks,
        total_prototypes=args.total_prototypes,
    )
    pipe = QuerySidePipeline(cfg, device=args.device)

    # 1) 初始化子原型空间
    pipe.initialize_bank(texts, labels)

    # 2) 跑一个训练 step
    bs = min(args.batch_size, len(texts))
    batch_texts = texts[:bs]
    batch_labels = labels[:bs]
    is_known = torch.ones_like(batch_labels)
    optimizer = torch.optim.AdamW(
        list(pipe.encoder.parameters()) + list(pipe.head.parameters()),
        lr=2e-5,
    )
    metrics: dict[str, Any] = pipe.training_step(batch_texts, batch_labels, is_known, optimizer)

    # 3) 推理 + OOD 示例
    infer_texts = texts[: min(4, len(texts))]
    out = pipe.infer(infer_texts)
    grown = pipe.handle_ood_and_grow(infer_texts)

    print(f"[data] samples={len(clean_df)}, tasks={num_known_tasks}, label_col={label_col}")
    print(f"[proto] total={pipe.bank.state.means.shape[0] if pipe.bank.state is not None else 0}")
    print(f"[train] {metrics}")
    print(f"[infer] demand_vector_shape={tuple(out.demand_vector.shape)}")
    print(f"[infer] p_ood={out.p_ood.tolist()}")
    print(f"[ood] new_prototypes={grown}")


if __name__ == "__main__":
    main()
