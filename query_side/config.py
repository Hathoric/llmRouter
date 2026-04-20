from dataclasses import dataclass


@dataclass
class QuerySideConfig:
    # Task / prototypes
    num_known_tasks: int
    total_prototypes: int = 300
    embedding_dim: int = 768
    hidden_dim: int = 512
    projection_dim: int = 256
    max_proto_per_task: int = 0  # 0 means auto by total_prototypes / num_known_tasks

    # Training
    temperature: float = 0.07
    ood_threshold: float = 0.55
    pseudo_label_base_threshold: float = 0.75
    pseudo_label_load_alpha: float = 0.10

    # Loss weights
    lambda_sup: float = 1.0
    lambda_supcon: float = 0.5
    lambda_dpl: float = 0.5
    lambda_ood: float = 0.2
    lambda_reg: float = 0.01

    # Backbone
    deberta_model_name: str = "microsoft/deberta-v3-base"

    @property
    def proto_per_task(self) -> int:
        if self.max_proto_per_task > 0:
            return self.max_proto_per_task
        return max(1, self.total_prototypes // max(1, self.num_known_tasks))

