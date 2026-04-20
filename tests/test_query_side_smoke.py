import torch

from query_side import QuerySideConfig, QuerySidePipeline


def test_query_side_smoke() -> None:
    cfg = QuerySideConfig(num_known_tasks=3, total_prototypes=30, deberta_model_name="microsoft/deberta-v3-base")
    pipe = QuerySidePipeline(cfg, device="cpu")

    labeled_texts = [
        "How to train a neural network?",
        "Write a marketing email.",
        "Solve this algebra equation.",
        "Explain gradient descent.",
        "Create a sales pitch.",
        "Prove a geometry theorem.",
    ]
    labels = torch.tensor([0, 1, 2, 0, 1, 2], dtype=torch.long)
    pipe.initialize_bank(labeled_texts, labels)

    out = pipe.infer(["Summarize this paper in simple words."])
    assert out.demand_vector.shape[0] == 1
    assert out.p_known.shape[0] == 1
    assert out.p_ood.shape[0] == 1

