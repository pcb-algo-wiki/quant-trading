"""GNN 图神经网络模型（Phase 7）

软导入 torch + torch_geometric：
  - 有包 → GNNModel 使用 GraphSAGE 做行业关系特征增强
  - 无包 → GNNModel.is_available() 返回 False，调用方降级 LinearReturnModel

架构：
  - 输入节点特征：[sentiment_score, policy_score, propagated_score, momentum]（4维）
  - 消息传递：2 层 GraphSAGE（mean 聚合）
  - 输出：每节点的预测收益率分数（1维），用于信号排序

用法：
    from ml.gnn_model import GNNModel, is_gnn_available
    if is_gnn_available():
        model = GNNModel(in_channels=4, hidden_channels=32)
        # 训练 / 预测 ...
    else:
        from ml.models import LinearReturnModel
        model = LinearReturnModel()
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def is_gnn_available() -> bool:
    """返回 True 当 torch + torch_geometric 均已安装。"""
    try:
        import torch  # noqa: F401
        import torch_geometric  # noqa: F401
        return True
    except ImportError:
        return False


class GNNModel:
    """GraphSAGE 行业图神经网络（Phase 7）。

    Args:
        in_channels: 输入特征维度（默认 4）
        hidden_channels: 隐层维度（默认 32）
        out_channels: 输出维度（默认 1，预测收益分数）
        num_layers: GraphSAGE 层数（默认 2）
    """

    def __init__(
        self,
        in_channels: int = 4,
        hidden_channels: int = 32,
        out_channels: int = 1,
        num_layers: int = 2,
    ) -> None:
        self.in_channels = in_channels
        self.hidden_channels = hidden_channels
        self.out_channels = out_channels
        self.num_layers = num_layers
        self._model = None
        self._available = False
        self._try_build()

    def _try_build(self) -> None:
        try:
            import torch
            import torch.nn as nn
            from torch_geometric.nn import SAGEConv

            class _SAGENet(nn.Module):
                def __init__(self, in_ch: int, hidden: int, out_ch: int, layers: int):
                    super().__init__()
                    self.convs = nn.ModuleList()
                    self.convs.append(SAGEConv(in_ch, hidden))
                    for _ in range(layers - 2):
                        self.convs.append(SAGEConv(hidden, hidden))
                    self.convs.append(SAGEConv(hidden, out_ch))
                    self.relu = nn.ReLU()

                def forward(self, x, edge_index):
                    for i, conv in enumerate(self.convs[:-1]):
                        x = self.relu(conv(x, edge_index))
                    return self.convs[-1](x, edge_index)

            self._model = _SAGENet(
                self.in_channels, self.hidden_channels,
                self.out_channels, self.num_layers,
            )
            self._available = True
            logger.info("[GNNModel] GraphSAGE 构建成功 in=%d hidden=%d out=%d layers=%d",
                        self.in_channels, self.hidden_channels, self.out_channels, self.num_layers)
        except ImportError:
            logger.warning("[GNNModel] torch/torch_geometric 未安装，降级为 LinearReturnModel")
        except Exception as exc:
            logger.warning("[GNNModel] 模型构建失败: %s", exc)

    @property
    def is_available(self) -> bool:
        return self._available

    def fit(self, x: np.ndarray, edge_index: np.ndarray, y: np.ndarray,
            epochs: int = 50, lr: float = 1e-3) -> "GNNModel":
        """训练 GNN。

        Args:
            x: 节点特征矩阵 [N, in_channels]
            edge_index: 边索引 [2, E]（源节点/目标节点）
            y: 节点标签 [N]
            epochs: 训练轮数
            lr: 学习率
        """
        if not self._available:
            raise RuntimeError("GNNModel 不可用，请安装 torch + torch_geometric")

        import torch
        import torch.nn.functional as F

        x_t = torch.tensor(x, dtype=torch.float32)
        e_t = torch.tensor(edge_index, dtype=torch.long)
        y_t = torch.tensor(y, dtype=torch.float32)

        optimizer = torch.optim.Adam(self._model.parameters(), lr=lr)
        self._model.train()
        for _ in range(epochs):
            optimizer.zero_grad()
            out = self._model(x_t, e_t).squeeze(-1)
            loss = F.mse_loss(out, y_t)
            loss.backward()
            optimizer.step()

        return self

    def predict(self, x: np.ndarray, edge_index: np.ndarray) -> np.ndarray:
        """推理，返回每节点分数 [N]。"""
        if not self._available:
            raise RuntimeError("GNNModel 不可用")

        import torch
        x_t = torch.tensor(x, dtype=torch.float32)
        e_t = torch.tensor(edge_index, dtype=torch.long)
        self._model.eval()
        with torch.no_grad():
            out = self._model(x_t, e_t).squeeze(-1)
        return out.numpy()

    def get_fallback(self):
        """返回 LinearReturnModel 作为降级备用。"""
        from ml.models import LinearReturnModel
        return LinearReturnModel()
