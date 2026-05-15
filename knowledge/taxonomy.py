from __future__ import annotations


DEFAULT_TAXONOMY = {
    "ai_compute": {
        "name": "AI算力",
        "upstream": ["chips", "memory", "power"],
        "midstream": ["servers", "cloud", "data_center"],
        "downstream": ["model_training", "enterprise_ai", "edge_ai"],
    },
    "gpu": {
        "name": "GPU",
        "upstream": ["eda_ip", "materials", "wafer_fab"],
        "midstream": ["gpu_design", "advanced_packaging"],
        "downstream": ["training", "inference", "ai_terminals"],
    },
    "semiconductor": {
        "name": "半导体",
        "upstream": ["materials", "equipment"],
        "midstream": ["foundry", "ic_design", "packaging_test"],
        "downstream": ["consumer_electronics", "automotive", "industrial"],
    },
    "optical_comms": {
        "name": "光通信",
        "upstream": ["optical_chips", "optical_materials"],
        "midstream": ["optical_modules", "optical_devices"],
        "downstream": ["data_center_network", "telecom_network"],
    },
}


def list_seed_industries() -> list[str]:
    return sorted(DEFAULT_TAXONOMY.keys())


def get_industry_layers(industry: str) -> dict[str, list[str]]:
    if industry not in DEFAULT_TAXONOMY:
        raise KeyError(f"unknown industry: {industry}")
    item = DEFAULT_TAXONOMY[industry]
    return {
        "upstream": item["upstream"],
        "midstream": item["midstream"],
        "downstream": item["downstream"],
    }
