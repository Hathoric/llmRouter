from dataclasses import dataclass
from typing import Any, Dict

import torch
import torch.nn.functional as F

from .config import QuerySideConfig
from .losses import dpl_loss, ood_energy_loss, supcon_loss
from .modules import DualProjectionHead, QueryEncoder
from .prototype import PrototypeBank


@dataclass
class QueryOutput:
    demand_vector: torch.Tensor
    p_known: torch.Tensor
    p_ood: torch.Tensor
    nearest_proto_idx: torch.Tensor
    nearest_proto_conf: torch.Tensor


class QuerySidePipeline:
    def __init__(self, cfg: QuerySideConfig, device: str = "cpu"):
        self.cfg = cfg
        self.device = torch.device(device)
        self.encoder = QueryEncoder(cfg).to(self.device)
        self.head = DualProjectionHead(cfg).to(self.device)
        self.bank = PrototypeBank(cfg, device=self.device)

    @torch.no_grad()
    def encode_texts(self, texts: list[str]) -> Dict[str, torch.Tensor]:
        toks = self.encoder.tokenize(texts)
        toks = {k: v.to(self.device) for k, v in toks.items()}
        z = self.encoder(toks["input_ids"], toks["attention_mask"])
        out = self.head(z)
        return out

    @torch.no_grad()
    def initialize_bank(self, texts: list[str], labels: torch.Tensor) -> None:
        out = self.encode_texts(texts)
        self.bank.initialize_from_labeled(out["h_known"], labels.to(self.device))

    def training_step(
        self,
        texts: list[str],
        labels: torch.Tensor,
        is_known: torch.Tensor,
        optimizer: torch.optim.Optimizer,
    ) -> Dict[str, float]:
        toks = self.encoder.tokenize(texts)
        toks = {k: v.to(self.device) for k, v in toks.items()}
        labels = labels.to(self.device)
        is_known = is_known.to(self.device).float()

        z = self.encoder(toks["input_ids"], toks["attention_mask"])
        out = self.head(z)
        logits = out["logits"]
        h_known = out["h_known"]

        loss_sup = F.cross_entropy(logits, labels)
        loss_supcon = supcon_loss(h_known, labels, temperature=self.cfg.temperature)
        loss_dpl = dpl_loss(h_known, labels, self.bank)
        loss_ood = ood_energy_loss(logits, is_known)
        loss_reg = (h_known.pow(2).mean() + out["h_unknown"].pow(2).mean()) * 0.5

        loss = (
            self.cfg.lambda_sup * loss_sup
            + self.cfg.lambda_supcon * loss_supcon
            + self.cfg.lambda_dpl * loss_dpl
            + self.cfg.lambda_ood * loss_ood
            + self.cfg.lambda_reg * loss_reg
        )

        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()

        return {
            "loss": float(loss.item()),
            "loss_sup": float(loss_sup.item()),
            "loss_supcon": float(loss_supcon.item()),
            "loss_dpl": float(loss_dpl.item()),
            "loss_ood": float(loss_ood.item()),
        }

    @torch.no_grad()
    def pseudo_label_unlabeled(self, texts: list[str]) -> Dict[str, Any]:
        out = self.encode_texts(texts)
        idx, conf = self.bank.nearest(out["h_known"])
        thr = self.bank.adaptive_threshold(idx)
        keep = conf >= thr

        pseudo_task = self.bank.state.task_ids[idx]  # type: ignore[union-attr]
        kept_idx = idx[keep]
        self.bank.update_loads(kept_idx)

        return {
            "keep_mask": keep,
            "pseudo_labels": pseudo_task,
            "proto_idx": idx,
            "confidence": conf,
        }

    @torch.no_grad()
    def handle_ood_and_grow(self, texts: list[str]) -> int:
        out = self.encode_texts(texts)
        logits = out["logits"]
        p_known = torch.softmax(logits, dim=-1).max(dim=-1).values
        ood_mask = p_known < self.cfg.ood_threshold
        residual = out["h_unknown"] - out["h_known"]
        return self.bank.add_new_prototypes_from_ood(residual[ood_mask])

    @torch.no_grad()
    def infer(self, texts: list[str]) -> QueryOutput:
        out = self.encode_texts(texts)
        logits = out["logits"]
        p_known_full = torch.softmax(logits, dim=-1)
        p_known = p_known_full.max(dim=-1).values
        p_ood = 1.0 - p_known
        idx, conf = self.bank.nearest(out["h_known"])

        # 需求向量 r(q): [h_known, h_unknown, p_known_max, p_ood, proto_conf]
        demand_vector = torch.cat(
            [
                out["h_known"],
                out["h_unknown"],
                p_known.unsqueeze(-1),
                p_ood.unsqueeze(-1),
                conf.unsqueeze(-1),
            ],
            dim=-1,
        )
        return QueryOutput(
            demand_vector=demand_vector,
            p_known=p_known,
            p_ood=p_ood,
            nearest_proto_idx=idx,
            nearest_proto_conf=conf,
        )

