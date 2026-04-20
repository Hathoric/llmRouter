from dataclasses import dataclass
from typing import Tuple

import torch
import torch.nn.functional as F
from sklearn.cluster import KMeans

from .config import QuerySideConfig


@dataclass
class PrototypeState:
    means: torch.Tensor        # [P, D]
    vars_diag: torch.Tensor    # [P, D]
    task_ids: torch.Tensor     # [P]
    loads: torch.Tensor        # [P]


class PrototypeBank:
    def __init__(self, cfg: QuerySideConfig, device: torch.device):
        self.cfg = cfg
        self.device = device
        self.state: PrototypeState | None = None

    def initialize_from_labeled(self, h_known: torch.Tensor, labels: torch.Tensor) -> None:
        """按任务分组聚类得到子原型初值。"""
        proto_per_task = self.cfg.proto_per_task
        all_means = []
        all_vars = []
        all_tids = []
        for tid in range(self.cfg.num_known_tasks):
            x = h_known[labels == tid]
            if x.shape[0] == 0:
                continue
            n_cluster = min(proto_per_task, x.shape[0])
            kmeans = KMeans(n_clusters=n_cluster, random_state=42, n_init=10)
            centers = torch.tensor(kmeans.fit(x.detach().cpu().numpy()).cluster_centers_, device=self.device)
            all_means.append(F.normalize(centers, dim=-1))

            # 简化：每个原型方差先用同一任务样本方差近似
            task_var = torch.var(x, dim=0, unbiased=False).clamp_min(1e-4)
            all_vars.append(task_var.unsqueeze(0).repeat(n_cluster, 1))
            all_tids.append(torch.full((n_cluster,), tid, device=self.device, dtype=torch.long))

        means = torch.cat(all_means, dim=0)
        vars_diag = torch.cat(all_vars, dim=0)
        task_ids = torch.cat(all_tids, dim=0)
        loads = torch.zeros(means.shape[0], device=self.device)
        self.state = PrototypeState(means=means, vars_diag=vars_diag, task_ids=task_ids, loads=loads)

    def nearest(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """返回最近原型索引与置信度（基于余弦相似度 softmax）。"""
        assert self.state is not None, "Prototype bank is not initialized."
        sim = x @ self.state.means.T
        conf, idx = torch.max(torch.softmax(sim, dim=-1), dim=-1)
        return idx, conf

    def adaptive_threshold(self, proto_idx: torch.Tensor) -> torch.Tensor:
        assert self.state is not None, "Prototype bank is not initialized."
        load = self.state.loads[proto_idx]
        return self.cfg.pseudo_label_base_threshold + self.cfg.pseudo_label_load_alpha * load

    def update_loads(self, proto_idx: torch.Tensor) -> None:
        assert self.state is not None, "Prototype bank is not initialized."
        for p in proto_idx.tolist():
            self.state.loads[p] += 1.0

    def add_new_prototypes_from_ood(self, ood_feats: torch.Tensor, max_new: int = 8) -> int:
        """
        OOD 增长入口（简化版）：
        - 真实项目可替换为 DBSCAN/HDBSCAN 在残差空间聚类
        - 这里先按随机采样构造少量新原型以打通流程
        """
        assert self.state is not None, "Prototype bank is not initialized."
        if ood_feats.shape[0] < 2:
            return 0
        n_new = min(max_new, ood_feats.shape[0])
        means_new = F.normalize(ood_feats[:n_new], dim=-1)
        vars_new = torch.ones_like(means_new) * 0.05
        task_new = torch.full((n_new,), -1, device=self.device, dtype=torch.long)  # -1 for unknown
        loads_new = torch.zeros(n_new, device=self.device)

        self.state.means = torch.cat([self.state.means, means_new], dim=0)
        self.state.vars_diag = torch.cat([self.state.vars_diag, vars_new], dim=0)
        self.state.task_ids = torch.cat([self.state.task_ids, task_new], dim=0)
        self.state.loads = torch.cat([self.state.loads, loads_new], dim=0)
        return n_new

