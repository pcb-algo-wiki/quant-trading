from __future__ import annotations


class OptimizationManager:
    """
    简化的持续优化优先级管理器：
    priority = 0.6 * drift + 0.4 * impact
    """

    def prioritize(self, backlog: list[dict]) -> list[dict]:
        ranked = []
        for item in backlog:
            drift = float(item.get("drift_score", 0))
            impact = float(item.get("impact_score", 0))
            priority = 0.6 * drift + 0.4 * impact
            ranked.append({**item, "priority": round(priority, 4)})
        ranked.sort(key=lambda x: x["priority"], reverse=True)
        return ranked
