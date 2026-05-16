"""
半导体+光通信 供需产业链数据库
=====================================
分析框架:
  1. 各环节产能数据 (现有产能/在建/投产时间线)
  2. 供需缺口计算 (产能 vs 需求)
  3. 价格/利润率周期 (紧缺→过剩)
  4. 个股走势与供需周期对照

产业链层级:
  半导体: 硅片 → 晶圆代工 → 封装测试 → 终端应用
         设备   →  材料   → 设计/EDA

  光通信: 芯片(激光器/探测器) → 光组件 → 光模块 → 交换机/服务器
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import date


# ============================================================
# 数据结构
# ============================================================

@dataclass
class CapacityEntry:
    """单个公司单个环节的产能条目"""
    company: str           # 公司名
    ticker: str            # 股票代码
    segment: str           # 产业链环节
    product: str           # 具体产品
    capacity_current: float  # 现有产能 (单位: 根据segment约定)
    capacity_unit: str      # 产能单位 (万片/月, 万只/年, 亿元/产能单位)
    utilization: float = 0.80  # 产能利用率 (0.0-1.0)
    capacity_building: float = 0  # 在建/规划产能
    build_start: Optional[str] = None  # 开工时间
    production_date: Optional[str] = None  # 预计投产时间
    status: str = "在产"    # 在产/在建/规划/已投产/已退出
    notes: str = ""        # 备注: 关键技术参数/扩产动因/风险点

    def capacity_soon(self) -> float:
        """半年内可释放产能"""
        return self.capacity_building if self.status in ("在建", "在产") else 0

    def capacity_operational(self, months_ahead: int = 0) -> float:
        """当前+未来某月可释放的运营产能"""
        return self.capacity_current + (self.capacity_building if months_ahead >= 0 else 0)


@dataclass
class DemandEntry:
    """单个环节的需求数据"""
    segment: str
    period: str             # "2023/2024/2025/Q1-2025"等
    demand_value: float    # 需求量
    unit: str               # 单位
    yoy_change: float = 0  # 同比变化 %
    source: str = ""        # 数据来源


@dataclass
class PriceEntry:
    """价格周期数据"""
    segment: str
    product: str
    period: str             # "2023Q1"
    price: float
    unit: str               # 价格单位
    price_change_yoy: float = 0  # 同比涨跌%


@dataclass
class CyclePhase:
    """供需周期阶段"""
    segment: str
    phase: str               # "紧缺" / "均衡" / "过剩" / "去化"
    start_period: str       # 开始时间
    end_period: Optional[str] = None  # 结束时间（如已知）
    gap_ratio: float = 0    # 供需缺口率 (正=紧缺, 负=过剩)
    price_trend: str = ""    # 价格趋势: "上涨/平稳/下跌/急跌"


# ============================================================
# 半导体产业链各环节
# ============================================================

SEMI_CHAIN_SEGMENTS = [
    # 上游
    "硅片/晶圆",
    "光刻胶/电子化学品",
    "CMP材料",
    "靶材/高纯气体",
    # 中游制造
    "半导体设备",
    "晶圆代工",
    "封装设备",
    "EDA/IP",
    # 下游
    "IC设计",
    "封装测试",
    "先进封装",
    "分立器件",
]

OPTICAL_CHAIN_SEGMENTS = [
    # 上游
    "光芯片",
    "PLC光分路器",
    "光无源组件",
    # 中游
    "光模块",
    "光放大器",
    # 下游
    "光纤连接器",
    "高速PCB/背板",
    "AI服务器/交换机",
]


# ============================================================
# 产能数据库 (万片/月 或 具体单位)
# ============================================================
# 注: 数据来源为公开新闻/财报披露，仅供分析参考
# 单位约定:
#   硅片/晶圆: 万片/月(8寸等效)
#   晶圆代工: 万片/月(12寸等效)
#   光模块: 万只/年
#   封装: 万颗/月

CAPACITY_DATABASE: list[CapacityEntry] = []

# ── 硅片/晶圆 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="沪硅产业", ticker="688126",
        segment="硅片/晶圆", product="12英寸硅片",
        capacity_current=45, capacity_unit="万片/月",
        utilization=0.75, capacity_building=30,
        build_start="2024Q1", production_date="2026Q2",
        status="在建",
        notes="12英寸正片产能，30万片/月新产能建设中，2026年逐步释放"
    ),
    CapacityEntry(
        company="有研硅", ticker="688432",
        segment="硅片/晶圆", product="12英寸硅片",
        capacity_current=15, capacity_unit="万片/月",
        utilization=0.90, capacity_building=0,
        status="在产",
        notes="山东有研艾斯15万片/月，已是稳定供货商"
    ),
    CapacityEntry(
        company="立昂微", ticker="605358",
        segment="硅片/晶圆", product="6/8英寸硅片",
        capacity_current=60, capacity_unit="万片/月",
        utilization=0.70, capacity_building=0,
        status="在产",
        notes="6-8英寸硅片为主，12英寸还在爬坡"
    ),
    CapacityEntry(
        company="中环股份", ticker="002129",
        segment="硅片/晶圆", product="12英寸硅片",
        capacity_current=30, capacity_unit="万片/月",
        utilization=0.80, capacity_building=20,
        build_start="2024Q2", production_date="2026Q3",
        status="在建",
        notes="TCL中环，12英寸硅片扩产中"
    ),
])

# ── 晶圆代工 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="中芯国际", ticker="688981",
        segment="晶圆代工", product="12英寸成熟制程(28nm及以上)",
        capacity_current=80, capacity_unit="万片/月(12寸等效)",
        utilization=0.90, capacity_building=20,
        build_start="2024Q1", production_date="2025Q3",
        status="在产",
        notes="北京/上海/深圳三地12寸厂，产能持续扩张，2025年新增约20万片/月"
    ),
    CapacityEntry(
        company="华虹半导体", ticker="688347",
        segment="晶圆代工", product="12英寸成熟制程",
        capacity_current=15, capacity_unit="万片/月",
        utilization=0.95, capacity_building=25,
        build_start="2023Q3", production_date="2025Q2",
        status="在建",
        notes="华虹无锡 fab9 25万片/月爬坡中，2025Q2开始释放"
    ),
    CapacityEntry(
        company="台积电(台湾)", ticker="TSM",
        segment="晶圆代工", product="7nm/5nm/3nm",
        capacity_current=120, capacity_unit="万片/月(12寸)",
        utilization=0.95, capacity_building=30,
        production_date="2025Q4",
        status="在产",
        notes="先进制程满载，AI芯片需求持续旺盛"
    ),
])

# ── 半导体设备 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="北方华创", ticker="002371",
        segment="半导体设备", product="刻蚀设备(PVD+CVD)",
        capacity_current=200, capacity_unit="台/年(8寸等效)",
        utilization=0.85, capacity_building=0,
        status="在产",
        notes="国产替代主力，刻蚀+薄膜设备，2024年订单满载"
    ),
    CapacityEntry(
        company="中微公司", ticker="688012",
        segment="半导体设备", product="CCP刻蚀机",
        capacity_current=100, capacity_unit="台/年",
        utilization=0.90, capacity_building=50,
        build_start="2024Q1", production_date="2025Q4",
        status="在产",
        notes="5nm CCP刻蚀机已量产，新产能50台/年建设中"
    ),
    CapacityEntry(
        company="拓荆科技", ticker="688072",
        segment="半导体设备", product="PECVD/ALD设备",
        capacity_current=80, capacity_unit="台/年",
        utilization=0.80, capacity_building=0,
        status="在产",
        notes="PECVD主力，先进封装用设备需求增加"
    ),
    CapacityEntry(
        company="华海清科", ticker="688120",
        segment="半导体设备", product="CMP设备",
        capacity_current=50, capacity_unit="台/年",
        utilization=0.85, capacity_building=0,
        status="在产",
        notes="CMP设备国产替代，12英寸CMP已量产"
    ),
    CapacityEntry(
        company="ASML(荷兰)", ticker="ASML",
        segment="半导体设备", product="EUV光刻机",
        capacity_current=60, capacity_unit="台/年",
        utilization=1.0, capacity_building=20,
        production_date="2026Q3",
        status="在产",
        notes="EUV满单，2026年产能提升至80台/年，EUV到2029年才出货"
    ),
    CapacityEntry(
        company="AMAT(美国)", ticker="AMAT",
        segment="半导体设备", product="沉积/刻蚀设备",
        capacity_current=500, capacity_unit="台/年",
        utilization=0.90, capacity_building=0,
        status="在产",
        notes="全球最大半导体设备商，中国市场受限"
    ),
])

# ── 封装测试 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="长电科技", ticker="600584",
        segment="封装测试", product="先进封装/Chiplet",
        capacity_current=50, capacity_unit="万颗/月",
        utilization=0.85, capacity_building=30,
        build_start="2024Q2", production_date="2026Q1",
        status="在产",
        notes="固定资产投资上调至100亿，海内外同步加码先进封装，CPO光电合封进展中"
    ),
    CapacityEntry(
        company="通富微电", ticker="002156",
        segment="封装测试", product="先进封装/Chiplet",
        capacity_current=40, capacity_unit="万颗/月",
        utilization=0.80, capacity_building=20,
        production_date="2026Q2",
        status="在产",
        notes="玻璃基板封装技术储备，2025Q1净利润+224%"
    ),
    CapacityEntry(
        company="华天科技", ticker="002185",
        segment="封装测试", product="先进封装",
        capacity_current=35, capacity_unit="万颗/月",
        utilization=0.75, capacity_building=0,
        status="在产",
        notes="QFN/BGA/CSP封装，先进封装占比提升"
    ),
])

# ── 光模块 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="中际旭创", ticker="300308",
        segment="光模块", product="800G/1.6T光模块",
        capacity_current=300, capacity_unit="万只/年",
        utilization=0.95, capacity_building=200,
        build_start="2024Q1", production_date="2025Q4",
        status="在产",
        notes="高端光模块订单和出货持续增加，2024Q4产能利用率接近满载"
    ),
    CapacityEntry(
        company="光迅科技", ticker="002281",
        segment="光模块", product="800G/1.6T光模块",
        capacity_current=250, capacity_unit="万只/年",
        utilization=0.90, capacity_building=150,
        production_date="2026Q1",
        status="在产",
        notes="1.6T已具备批量交付能力，800G已批量出货"
    ),
    CapacityEntry(
        company="新易盛", ticker="300502",
        segment="光模块", product="800G光模块",
        capacity_current=200, capacity_unit="万只/年",
        utilization=0.85, capacity_building=100,
        production_date="2025Q3",
        status="在产",
        notes="成都光模块厂商，产能扩张中"
    ),
    CapacityEntry(
        company="博创科技", ticker="300548",
        segment="光模块", product="400G/800G光模块",
        capacity_current=150, capacity_unit="万只/年",
        utilization=0.80, capacity_building=100,
        production_date="2025Q4",
        status="在产",
        notes="PLC光器件基础，扩展到光模块，400G+800G发力"
    ),
    CapacityEntry(
        company="天孚通信", ticker="300394",
        segment="光模块", product="光无源组件/光引擎",
        capacity_current=180, capacity_unit="万只/年",
        utilization=0.90, capacity_building=80,
        production_date="2026Q2",
        status="在产",
        notes="光器件上游，一体化光通信解决方案"
    ),
])

# ── 光芯片 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="三安光电", ticker="600703",
        segment="光芯片", product="VCSEL/DFB激光器芯片",
        capacity_current=30, capacity_unit="万颗/年",
        utilization=0.75, capacity_building=50,
        production_date="2026Q3",
        status="在产",
        notes="用于1.6T光模块的光芯片已向客户送样验证，扩产中"
    ),
    CapacityEntry(
        company="源杰科技", ticker="688498",
        segment="光芯片", product="25G/50G DFB激光器",
        capacity_current=20, capacity_unit="万颗/年",
        utilization=0.70, capacity_building=30,
        production_date="2026Q2",
        status="在产",
        notes="国产高速激光器芯片，100G/200G光模块用芯片"
    ),
    CapacityEntry(
        company="仕佳光子", ticker="688313",
        segment="光芯片", product="PLC光分路器芯片",
        capacity_current=100, capacity_unit="万颗/年",
        utilization=0.80, capacity_building=0,
        status="在产",
        notes="PLC光分路器全球前列，FTTH核心供应商"
    ),
])

# ── PCB/载板 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="深南电路", ticker="002916",
        segment="PCB/载板", product="AI服务器PCB/载板",
        capacity_current=80, capacity_unit="万平方米/年",
        utilization=0.95, capacity_building=40,
        production_date="2026Q1",
        status="在产",
        notes="400G以上高速交换机、光模块占比同比提升，AI服务器PCB用量增8-12倍"
    ),
    CapacityEntry(
        company="生益科技", ticker="600183",
        segment="PCB/载板", product="高速覆铜板/PCB",
        capacity_current=200, capacity_unit="万平方米/年",
        utilization=0.85, capacity_building=0,
        status="在产",
        notes="覆铜板龙头，高速材料用于AI服务器"
    ),
    CapacityEntry(
        company="南亚新材", ticker="688188",
        segment="PCB/载板", product="高速覆铜板",
        capacity_current=100, capacity_unit="万平方米/年",
        utilization=0.80, capacity_building=50,
        production_date="2026Q2",
        status="在产",
        notes="高速覆铜板产能扩张中"
    ),
])


# ============================================================
# 供需周期阶段定义 (从历史到未来)
# ============================================================

CYCLE_PHASES: list[CyclePhase] = [
    # ── 半导体硅片 ────────────────────────────────────────
    CyclePhase("硅片/晶圆", "紧缺", "2020Q1", "2022Q2", 0.15, "上涨"),
    CyclePhase("硅片/晶圆", "均衡", "2022Q3", "2023Q2", 0.0, "平稳"),
    CyclePhase("硅片/晶圆", "过剩", "2023Q3", "2024Q2", -0.20, "下跌"),
    CyclePhase("硅片/晶圆", "去化", "2024Q3", "2025Q2", -0.10, "缓跌"),
    CyclePhase("硅片/晶圆", "紧缺", "2025Q3", None, 0.12, "上涨"),

    # ── 晶圆代工 ──────────────────────────────────────────
    CyclePhase("晶圆代工", "紧缺", "2020Q3", "2022Q3", 0.20, "上涨"),
    CyclePhase("晶圆代工", "过剩", "2022Q4", "2024Q1", -0.25, "急跌"),
    CyclePhase("晶圆代工", "去化", "2024Q2", "2025Q1", -0.10, "缓跌"),
    CyclePhase("晶圆代工", "紧缺", "2025Q2", None, 0.15, "上涨"),

    # ── 半导体设备 ─────────────────────────────────────────
    CyclePhase("半导体设备", "紧缺", "2023Q1", None, 0.20, "上涨"),
    CyclePhase("半导体设备", "紧缺", "2025Q2", None, 0.25, "上涨"),

    # ── 封装测试 ──────────────────────────────────────────
    CyclePhase("封装测试", "紧缺", "2023Q3", "2024Q2", 0.15, "上涨"),
    CyclePhase("封装测试", "均衡", "2024Q3", "2025Q1", 0.0, "平稳"),
    CyclePhase("封装测试", "紧缺", "2025Q2", None, 0.10, "上涨"),

    # ── 光模块 ─────────────────────────────────────────────
    CyclePhase("光模块", "过剩", "2022Q1", "2023Q2", -0.30, "急跌"),
    CyclePhase("光模块", "去化", "2023Q3", "2023Q4", -0.15, "缓跌"),
    CyclePhase("光模块", "紧缺", "2024Q1", None, 0.20, "急涨"),
    CyclePhase("光模块", "紧缺", "2025Q1", None, 0.25, "上涨"),

    # ── 光芯片 ─────────────────────────────────────────────
    CyclePhase("光芯片", "过剩", "2022Q2", "2023Q4", -0.20, "下跌"),
    CyclePhase("光芯片", "紧缺", "2024Q1", "2025Q2", 0.15, "上涨"),
    CyclePhase("光芯片", "均衡", "2025Q3", None, 0.02, "平稳"),

    # ── PCB/载板 ─────────────────────────────────────────────
    CyclePhase("PCB/载板", "紧缺", "2024Q1", None, 0.18, "上涨"),
]


# ============================================================
# 工具函数
# ============================================================

def get_segment_capacity(segment: str) -> tuple[float, float, float]:
    """
    返回: (当前产能总计, 在建产能总计, 产能利用率)
    """
    entries = [e for e in CAPACITY_DATABASE if e.segment == segment]
    current = sum(e.capacity_current * e.utilization for e in entries)
    building = sum(e.capacity_building for e in entries)
    avg_util = sum(e.utilization for e in entries) / len(entries) if entries else 0
    return current, building, avg_util


def get_supply_demand_gap(segment: str, months_ahead: int = 0) -> dict:
    """
    计算某环节供需缺口
    months_ahead: 0=当前, 3=三个月后, 6=半年后, 9=九个月后, 12=一年后
    """
    current, building, util = get_segment_capacity(segment)
    # 未来某月产能 = 当前产能 + 在建×(已过时间/月数)
    if months_ahead == 0:
        supply = current
    else:
        supply = current + building * min(months_ahead / 18, 1.0)  # 假设平均18个月建设周期

    # 需求估算(基于周期相位)
    phases = [p for p in CYCLE_PHASES if p.segment == segment and p.end_period is None]
    if phases:
        latest = phases[-1]
        gap_ratio = latest.gap_ratio
    else:
        gap_ratio = 0

    demand = supply / (1 + gap_ratio) if gap_ratio > -0.99 else supply * 1.2
    gap = supply - demand
    gap_pct = gap / demand * 100 if demand > 0 else 0

    return {
        "segment": segment,
        "supply": round(supply, 2),
        "demand": round(demand, 2),
        "gap": round(gap, 2),
        "gap_pct": round(gap_pct, 1),
        "status": "紧缺" if gap > 0 else ("过剩" if gap < -supply * 0.05 else "均衡"),
        "months_ahead": months_ahead,
    }


def get_stock_by_segment(segment: str) -> list[tuple[str, str]]:
    """找某环节对应的A股股票"""
    mapping = {
        "硅片/晶圆": [("688126", "沪硅产业"), ("688432", "有研硅"), ("002129", "中环股份"), ("605358", "立昂微")],
        "晶圆代工": [("688981", "中芯国际"), ("688347", "华虹半导体"), ("TSM", "台积电")],
        "半导体设备": [("002371", "北方华创"), ("688012", "中微公司"), ("688072", "拓荆科技"), ("688120", "华海清科"), ("ASML", "ASML")],
        "封装测试": [("600584", "长电科技"), ("002156", "通富微电"), ("002185", "华天科技")],
        "光模块": [("300308", "中际旭创"), ("002281", "光迅科技"), ("300502", "新易盛"), ("300548", "博创科技"), ("300394", "天孚通信")],
        "光芯片": [("600703", "三安光电"), ("688498", "源杰科技"), ("688313", "仕佳光子")],
        "PCB/载板": [("002916", "深南电路"), ("600183", "生益科技"), ("688188", "南亚新材")],
    }
    return mapping.get(segment, [])


def print_supply_chain_report():
    """打印完整供需链报告"""
    all_segments = list(set(e.segment for e in CAPACITY_DATABASE))
    print("=" * 80)
    print("📊 半导体+光通信 供需产业链全景")
    print("=" * 80)

    for seg in all_segments:
        entries = [e for e in CAPACITY_DATABASE if e.segment == seg]
        print(f"\n{'─' * 60}")
        print(f"【{seg}】")
        for e in entries:
            status_icon = "🔴" if e.utilization > 0.90 else ("🟡" if e.utilization > 0.75 else "🟢")
            print(f"  {status_icon} {e.company}({e.ticker}): {e.capacity_current}{e.capacity_unit} 利用率={e.utilization*100:.0f}%")
            if e.capacity_building > 0:
                print(f"    📈 在建: {e.capacity_building}{e.capacity_unit} (预计{e.production_date}投产)")

        for months in [0, 3, 6, 9, 12]:
            gap = get_supply_demand_gap(seg, months)
            icon = "🔴" if gap["status"] == "紧缺" else ("🟢" if gap["status"] == "均衡" else "🔵")
            print(f"  {icon} {months}个月后: 供给{gap['supply']:.1f} / 需求{gap['demand']:.1f} / 缺口{gap['gap']:+.1f} ({gap['gap_pct']:+.1f}%)")

        stocks = get_stock_by_segment(seg)
        print(f"  📌 对应个股: {', '.join(f'{s[1]}({s[0]})' for s in stocks)}")


if __name__ == "__main__":
    print_supply_chain_report()
