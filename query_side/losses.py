import torch
import torch.nn.functional as F

from .prototype import PrototypeBank


def supcon_loss(features: torch.Tensor, labels: torch.Tensor, temperature: float = 0.07) -> torch.Tensor:
    """简化版 SupCon。"""
    features = F.normalize(features, dim=-1)
    sim = torch.matmul(features, features.T) / temperature
    mask = labels.unsqueeze(0) == labels.unsqueeze(1)
    logits_mask = ~torch.eye(features.size(0), device=features.device, dtype=torch.bool)
    mask = mask & logits_mask

    exp_sim = torch.exp(sim) * logits_mask
    log_prob = sim - torch.log(exp_sim.sum(dim=1, keepdim=True) + 1e-8)
    mean_log_prob_pos = (mask * log_prob).sum(dim=1) / (mask.sum(dim=1) + 1e-8)
    return -mean_log_prob_pos.mean()


def dpl_loss(h_known: torch.Tensor, labels: torch.Tensor, bank: PrototypeBank, margin: float = 0.2) -> torch.Tensor:
    """分布原型拉推损失（简化）：同任务最近原型拉近，异任务最近原型推远。"""
    assert bank.state is not None, "Prototype bank is not initialized."
    means = bank.state.means
    task_ids = bank.state.task_ids

    sim = h_known @ means.T
    loss_pull = torch.tensor(0.0, device=h_known.device)
    loss_push = torch.tensor(0.0, device=h_known.device)

    for i in range(h_known.size(0)):
        same = task_ids == labels[i]
        diff = task_ids != labels[i]
        if torch.any(same):
            pos = sim[i, same].max()
            loss_pull = loss_pull + (1.0 - pos)
        if torch.any(diff):
            neg = sim[i, diff].max()
            loss_push = loss_push + F.relu(neg - margin)
    return (loss_pull + loss_push) / max(1, h_known.size(0))


def ood_energy_loss(logits: torch.Tensor, is_known: torch.Tensor) -> torch.Tensor:
    """
    已知样本希望能量低，未知样本希望能量高（简化）。
    is_known: 1 for known, 0 for unknown
    """
    energy = -torch.logsumexp(logits, dim=-1)
    known_loss = (is_known * torch.relu(energy)).mean()
    unknown_loss = ((1 - is_known) * torch.relu(-energy)).mean()
    return known_loss + unknown_loss

