from typing import Dict

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

from .config import QuerySideConfig


class QueryEncoder(nn.Module):
    def __init__(self, cfg: QuerySideConfig):
        super().__init__()
        # First try the configured DeBERTa model. If local env lacks a backend
        # (e.g. protobuf on Windows), fallback to a robust BERT-family model.
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(cfg.deberta_model_name, use_fast=False)
            self.backbone = AutoModel.from_pretrained(cfg.deberta_model_name)
            self.model_name = cfg.deberta_model_name
        except Exception:
            fallback_model = "distilbert-base-uncased"
            self.tokenizer = AutoTokenizer.from_pretrained(fallback_model, use_fast=True)
            self.backbone = AutoModel.from_pretrained(fallback_model)
            self.model_name = fallback_model
        self.proj = nn.Linear(self.backbone.config.hidden_size, cfg.embedding_dim)

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        out = self.backbone(input_ids=input_ids, attention_mask=attention_mask)
        cls = out.last_hidden_state[:, 0, :]
        z = self.proj(cls)
        return F.normalize(z, dim=-1)

    def tokenize(self, texts: list[str], max_length: int = 128) -> Dict[str, torch.Tensor]:
        return self.tokenizer(
            texts,
            max_length=max_length,
            padding=True,
            truncation=True,
            return_tensors="pt",
        )


class DualProjectionHead(nn.Module):
    def __init__(self, cfg: QuerySideConfig):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(cfg.embedding_dim, cfg.hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
        )
        self.known = nn.Linear(cfg.hidden_dim, cfg.projection_dim)
        self.unknown = nn.Linear(cfg.hidden_dim, cfg.projection_dim)
        self.classifier = nn.Linear(cfg.projection_dim, cfg.num_known_tasks)

    def forward(self, z: torch.Tensor) -> Dict[str, torch.Tensor]:
        h = self.shared(z)
        h_known = F.normalize(self.known(h), dim=-1)
        h_unknown = F.normalize(self.unknown(h), dim=-1)
        logits = self.classifier(h_known)
        return {"h_known": h_known, "h_unknown": h_unknown, "logits": logits}

