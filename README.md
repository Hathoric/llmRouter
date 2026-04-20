# llmRouter

当前项目已切换为 **Query 侧原型增量学习框架**（已移除基于规则的路由实现）。

## 项目结构

```
llmRouter/
├── query_side/
│   ├── config.py      # Query 侧配置（原型预算、阈值、损失权重）
│   ├── modules.py     # DeBERTa + 双投影头（h_known, h_unknown）
│   ├── prototype.py   # 子原型空间、伪标签负载阈值、OOD 生长
│   ├── losses.py      # L_supcon / L_dpl / L_ood
│   └── pipeline.py    # 训练步、推理、OOD 处理、需求向量导出
├── main.py            # dataset 驱动的最小训练/推理入口
├── tests/
│   └── test_query_side_smoke.py
└── requirements.txt
```

## Query 侧原型增量学习框架

新增 `query_side/`，用于把 Query 建模为“已知任务 + 未知任务”的原型分布表示：

- `modules.py`：DeBERTa 编码器 + 双投影头（`h_known`, `h_unknown`）
- `prototype.py`：子原型空间初始化、近邻分配、负载自适应阈值、OOD 原型生长
- `losses.py`：`L_supcon` / `L_dpl` / `L_ood`（简化可训练版本）
- `pipeline.py`：统一训练步、伪标签增量、OOD 处理、需求向量导出

最小使用示例：

```python
import torch
from query_side import QuerySideConfig, QuerySidePipeline

cfg = QuerySideConfig(num_known_tasks=3, total_prototypes=30)
pipe = QuerySidePipeline(cfg, device="cpu")

labeled_texts = ["sample a", "sample b", "sample c"]
labels = torch.tensor([0, 1, 2], dtype=torch.long)
pipe.initialize_bank(labeled_texts, labels)

out = pipe.infer(["new query"])
print(out.demand_vector.shape)
```

> 注：当前实现是“可运行骨架 + 核心接口”，便于后续替换成你的真实数据加载、完整 OOD 聚类（如 HDBSCAN）和在线增量策略。

## 用 dataset 快速测试

```bash
pip install -r requirements.txt
python main.py --data-path dataset/routerbench_0shot.pkl --text-col prompt --label-col eval_name --total-prototypes 300
```

说明：
- `--label-col` 默认是 `eval_name`，也可换成你的任务标签列。
- `total_prototypes` 默认已从 3000 调整到 300，更适合首轮实验。
