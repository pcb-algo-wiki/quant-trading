"""
半导体+光通信+存储+锂电+机器人+军工 供需产业链数据库
=============================================================
分析框架:
  1. 各环节产能数据 (现有产能/在建/投产时间线)
  2. 供需缺口计算 (产能 vs 需求)
  3. 价格/利润率周期 (紧缺→过剩)
  4. 个股走势与供需周期对照

产业链层级:
  半导体: 硅片 → 晶圆代工 → 封装测试 → 终端应用
         设备   →  材料   → 设计/EDA

  光通信: 芯片(激光器/探测器) → 光组件 → 光模块 → 交换机/服务器

  存储:   NAND/DRAM设计 → 晶圆制造 → 封测 → 模组

  锂电:   正极/负极/隔膜/电解液 → 电芯 → 模组/PACK → 整车

  机器人: 核心零部件(减速器/伺服/控制器) → 本体 → 系统集成

  军工:   原材料(钛合金/高温合金) → 零部件 → 整机 → 运营
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

# 新增四大产业链
STORAGE_CHAIN_SEGMENTS = [
    "存储制造",
    "存储封测",
    "HBM/高带宽存储",
    "模组/SSD",
]

BATTERY_CHAIN_SEGMENTS = [
    "正极材料",
    "负极材料",
    "隔膜",
    "电解液",
    "锂电设备",
    "电芯/PACK",
]

ROBOT_CHAIN_SEGMENTS = [
    "减速器",
    "伺服驱动",
    "控制器",
    "传感器",
    "机器人本体",
]

DEFENSE_CHAIN_SEGMENTS = [
    "高温合金/钛合金",
    "航发整机",
    "军机/无人机",
    "导弹/精确制导",
    "军工信息化",
    "商业航天",
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
#   存储制造: 万片/月(12寸)
#   正极: 万吨/年
#   负极: 万吨/年
#   隔膜: 亿平米/年
#   电解液: 万吨/年
#   减速器: 万台/年

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

# ── 存储制造 ──────────────────────────────────────────────
# NAND/DRAM晶圆制造：三星/SK海力士/美光/长江存储
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="长江存储", ticker="NAND",
        segment="存储制造", product="3D NAND晶圆",
        capacity_current=15, capacity_unit="万片/月",
        utilization=0.80, capacity_building=10,
        build_start="2024Q1", production_date="2026Q2",
        status="在产",
        notes="国产NAND突破，232层3D NAND量产，产能持续扩张"
    ),
    CapacityEntry(
        company="合肥长鑫", ticker="DRAM",
        segment="存储制造", product="DRAM晶圆",
        capacity_current=10, capacity_unit="万片/月",
        utilization=0.85, capacity_building=8,
        build_start="2024Q2", production_date="2026Q3",
        status="在产",
        notes="国产DRAM突破，17nm LPDDR5量产，产能爬坡中"
    ),
    CapacityEntry(
        company="三星(韩国)", ticker="SMSN",
        segment="存储制造", product="3D NAND/DRAM",
        capacity_current=200, capacity_unit="万片/月(12寸等效)",
        utilization=0.75, capacity_building=30,
        production_date="2026Q4",
        status="在产",
        notes="全球存储龙头，HBM3e供不应求，AI驱动高价值产品占比提升"
    ),
    CapacityEntry(
        company="SK海力士(韩国)", ticker="000660",
        segment="存储制造", product="HBM/DRAM",
        capacity_current=150, capacity_unit="万片/月(12寸等效)",
        utilization=0.90, capacity_building=40,
        production_date="2026Q3",
        status="在产",
        notes="HBM市占率全球第一~70%，为NVIDIA AI GPU供货，产能紧张"
    ),
    CapacityEntry(
        company="美光(美国)", ticker="MU",
        segment="存储制造", product="HBM/DRAM/NAND",
        capacity_current=120, capacity_unit="万片/月(12寸等效)",
        utilization=0.80, capacity_building=20,
        production_date="2026Q2",
        status="在产",
        notes="HBM获NVIDIA认证，AI需求强劲，产能利用率回升"
    ),
])

# ── 存储封测 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="通富微电", ticker="002156",
        segment="存储封测", product="NAND/DRAM封测",
        capacity_current=30, capacity_unit="万颗/月",
        utilization=0.75, capacity_building=15,
        production_date="2026Q2",
        status="在产",
        notes="存储封测占比提升，海力士/美光等客户加单"
    ),
    CapacityEntry(
        company="华天科技", ticker="002185",
        segment="存储封测", product="NAND封测",
        capacity_current=25, capacity_unit="万颗/月",
        utilization=0.70, capacity_building=10,
        status="在产",
        notes="NAND Flash封测，先进封装占比提升"
    ),
    CapacityEntry(
        company="太极实业", ticker="600667",
        segment="存储封测", product="DRAM封测",
        capacity_current=20, capacity_unit="万颗/月",
        utilization=0.80, capacity_building=0,
        status="在产",
        notes="海力士封测主力供应商，订单稳定"
    ),
])

# ── HBM/高带宽存储 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="SK海力士", ticker="000660",
        segment="HBM/高带宽存储", product="HBM3e",
        capacity_current=5, capacity_unit="万颗/年",
        utilization=1.0, capacity_building=8,
        production_date="2026Q3",
        status="在产",
        notes="HBM3e已量产，2025年产能已被NVIDIA全包，供不应求延续"
    ),
    CapacityEntry(
        company="三星", ticker="SMSN",
        segment="HBM/高带宽存储", product="HBM3e",
        capacity_current=3, capacity_unit="万颗/年",
        utilization=0.90, capacity_building=5,
        production_date="2026Q4",
        status="在产",
        notes="HBM良率改善中，2025年目标产能翻倍"
    ),
    CapacityEntry(
        company="美光", ticker="MU",
        segment="HBM/高带宽存储", product="HBM3e",
        capacity_current=2, capacity_unit="万颗/年",
        utilization=0.95, capacity_building=4,
        production_date="2026Q2",
        status="在产",
        notes="HBM4研发中，已获NVIDIA HBM3e认证"
    ),
])

# ── 模组/SSD ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="江波龙", ticker="301308",
        segment="模组/SSD", product="嵌入式存储/SSD",
        capacity_current=5000, capacity_unit="万颗/年",
        utilization=0.80, capacity_building=2000,
        production_date="2026Q2",
        status="在产",
        notes="国内存储模组龙头，嵌入式存储+AI服务器SSD双线扩张"
    ),
    CapacityEntry(
        company="朗科科技", ticker="300542",
        segment="模组/SSD", product="SSD/存储模组",
        capacity_current=3000, capacity_unit="万颗/年",
        utilization=0.75, capacity_building=0,
        status="在产",
        notes="SSD模组，固态硬盘"
    ),
])

# ── 正极材料 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="容百科技", ticker="688005",
        segment="正极材料", product="高镍正极材料",
        capacity_current=20, capacity_unit="万吨/年",
        utilization=0.65, capacity_building=15,
        production_date="2026Q2",
        status="在产",
        notes="高镍三元正极，2024年出货量全球前三，钠电正极布局"
    ),
    CapacityEntry(
        company="当升科技", ticker="300073",
        segment="正极材料", product="多元正极/磷酸铁锂",
        capacity_current=15, capacity_unit="万吨/年",
        utilization=0.60, capacity_building=10,
        status="在产",
        notes="正极材料老牌厂商，固态电池正极已送样"
    ),
    CapacityEntry(
        company="湖南裕能", ticker="301358",
        segment="正极材料", product="磷酸铁锂正极",
        capacity_current=50, capacity_unit="万吨/年",
        utilization=0.70, capacity_building=20,
        production_date="2026Q3",
        status="在产",
        notes="磷酸铁锂正极出货量国内第一，绑定宁德时代/比亚迪"
    ),
    CapacityEntry(
        company="德方纳米", ticker="300769",
        segment="正极材料", product="磷酸铁锂正极",
        capacity_current=40, capacity_unit="万吨/年",
        utilization=0.65, capacity_building=15,
        status="在产",
        notes="液相法磷酸铁锂，成本优势，产能扩张中"
    ),
])

# ── 负极材料 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="贝特瑞", ticker="688185",
        segment="负极材料", product="硅碳负极/石墨负极",
        capacity_current=30, capacity_unit="万吨/年",
        utilization=0.70, capacity_building=20,
        production_date="2026Q2",
        status="在产",
        notes="负极材料全球龙头，硅碳负极已量产供货固态电池"
    ),
    CapacityEntry(
        company="璞泰来", ticker="603659",
        segment="负极材料", product="石墨负极/硅碳负极",
        capacity_current=25, capacity_unit="万吨/年",
        utilization=0.75, capacity_building=15,
        status="在产",
        notes="负极+隔膜+涂覆一体化，硅碳负极量产中"
    ),
    CapacityEntry(
        company="中科电气", ticker="300035",
        segment="负极材料", product="石墨负极",
        capacity_current=15, capacity_unit="万吨/年",
        utilization=0.60, capacity_building=10,
        production_date="2026Q3",
        status="在产",
        notes="负极材料，出货量稳步增长"
    ),
])

# ── 隔膜 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="恩捷股份", ticker="002812",
        segment="隔膜", product="湿法隔膜",
        capacity_current=80, capacity_unit="亿平米/年",
        utilization=0.70, capacity_building=30,
        production_date="2026Q2",
        status="在产",
        notes="湿法隔膜全球龙头，产能利用率回升，海外扩产中"
    ),
    CapacityEntry(
        company="星源材质", ticker="300568",
        segment="隔膜", product="干法+湿法隔膜",
        capacity_current=40, capacity_unit="亿平米/年",
        utilization=0.65, capacity_building=15,
        status="在产",
        notes="干法隔膜龙头，湿法隔膜加速扩张，LGES/三星SDI供货"
    ),
])

# ── 电解液 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="天赐材料", ticker="002709",
        segment="电解液", product="锂电池电解液",
        capacity_current=50, capacity_unit="万吨/年",
        utilization=0.60, capacity_building=20,
        production_date="2026Q3",
        status="在产",
        notes="电解液全球龙头，一体化成本优势，半固态电解质量产"
    ),
    CapacityEntry(
        company="新宙邦", ticker="300037",
        segment="电解液", product="电解液/添加剂",
        capacity_current=25, capacity_unit="万吨/年",
        utilization=0.55, capacity_building=10,
        status="在产",
        notes="电解液高端化，海外客户占比提升，钠电电解液布局"
    ),
])

# ── 锂电设备 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="先导智能", ticker="300450",
        segment="锂电设备", product="锂电整线设备",
        capacity_current=100, capacity_unit="GW/年",
        utilization=0.75, capacity_building=0,
        status="在产",
        notes="锂电设备全球龙头，整线覆盖率90%+，海外扩产受益"
    ),
    CapacityEntry(
        company="赢合科技", ticker="300457",
        segment="锂电设备", product="锂电设备",
        capacity_current=60, capacity_unit="GW/年",
        utilization=0.70, capacity_building=0,
        status="在产",
        notes="涂布机/卷绕机头部，海外订单增长"
    ),
])

# ── 电芯/PACK ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="宁德时代", ticker="300750",
        segment="电芯/PACK", product="动力/储能电池",
        capacity_current=400, capacity_unit="GWh/年",
        utilization=0.80, capacity_building=150,
        production_date="2026Q4",
        status="在产",
        notes="全球动力电池龙头，麒麟电池/神行超充，2025年产能规划600GWh"
    ),
    CapacityEntry(
        company="比亚迪", ticker="002594",
        segment="电芯/PACK", product="动力/储能电池",
        capacity_current=300, capacity_unit="GWh/年",
        utilization=0.85, capacity_building=100,
        production_date="2026Q3",
        status="在产",
        notes="刀片电池自供+外供，储能业务爆发，海外工厂加速"
    ),
    CapacityEntry(
        company="亿纬锂能", ticker="300014",
        segment="电芯/PACK", product="消费/动力/储能电池",
        capacity_current=80, capacity_unit="GWh/年",
        utilization=0.75, capacity_building=60,
        production_date="2026Q2",
        status="在产",
        notes="全技术路线布局，4680大圆柱量产，荆门基地扩张"
    ),
])

# ── 减速器 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="绿的谐波", ticker="688017",
        segment="减速器", product="工业机器人减速器",
        capacity_current=50, capacity_unit="万台/年",
        utilization=0.80, capacity_building=30,
        production_date="2026Q2",
        status="在产",
        notes="国产谐波减速器龙头，2024年出货量+40%，打破哈默纳科垄断"
    ),
    CapacityEntry(
        company="双环传动", ticker="002472",
        segment="减速器", product="RV减速器",
        capacity_current=30, capacity_unit="万台/年",
        utilization=0.75, capacity_building=20,
        production_date="2026Q3",
        status="在产",
        notes="RV减速器国产替代，2024年进入人形机器人供应链"
    ),
    CapacityEntry(
        company="中大力德", ticker="002896",
        segment="减速器", product="减速器/伺服",
        capacity_current=20, capacity_unit="万台/年",
        utilization=0.70, capacity_building=10,
        status="在产",
        notes="中小型减速器，工业机器人+AGV+物流"
    ),
])

# ── 伺服驱动 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="汇川技术", ticker="300124",
        segment="伺服驱动", product="伺服系统/变频器",
        capacity_current=200, capacity_unit="万台/年",
        utilization=0.85, capacity_building=100,
        production_date="2026Q2",
        status="在产",
        notes="伺服驱动国内龙头，人形机器人伺服电机已送样"
    ),
    CapacityEntry(
        company="禾川科技", ticker="688255",
        segment="伺服驱动", product="伺服系统/PLC",
        capacity_current=80, capacity_unit="万台/年",
        utilization=0.75, capacity_building=40,
        status="在产",
        notes="PLC+伺服，产品进入人形机器人厂家"
    ),
    CapacityEntry(
        company="埃斯顿", ticker="002747",
        segment="伺服驱动", product="工业机器人/伺服",
        capacity_current=50, capacity_unit="万台/年",
        utilization=0.80, capacity_building=30,
        production_date="2026Q3",
        status="在产",
        notes="工业机器人本体+核心零部件，产能扩张中"
    ),
])

# ── 控制器 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="中控技术", ticker="688777",
        segment="控制器", product="DCS/PLC/工控系统",
        capacity_current=3, capacity_unit="万台/年",
        utilization=0.85, capacity_building=2,
        production_date="2026Q4",
        status="在产",
        notes="工控系统国内龙头，工业软件+AI布局，人形机器人控制器研发中"
    ),
    CapacityEntry(
        company="华中数控", ticker="300161",
        segment="控制器", product="数控系统/控制器",
        capacity_current=5, capacity_unit="万台/年",
        utilization=0.75, capacity_building=0,
        status="在产",
        notes="国产数控系统龙头，机器人控制器进入头部客户"
    ),
])

# ── 传感器 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="坤维科技", ticker="688122",
        segment="传感器", product="六维力传感器",
        capacity_current=5, capacity_unit="万台/年",
        utilization=0.80, capacity_building=10,
        production_date="2026Q2",
        status="在产",
        notes="六维力传感器是人形机器人手/足关节必备，国产替代空间大"
    ),
    CapacityEntry(
        company="敏芯股份", ticker="688286",
        segment="传感器", product="MEMS传感器",
        capacity_current=10, capacity_unit="亿颗/年",
        utilization=0.70, capacity_building=5,
        status="在产",
        notes="MEMS麦克风/压力传感器，布局机器人触觉传感器"
    ),
    CapacityEntry(
        company="华工科技", ticker="688001",
        segment="传感器", product="温度传感器/激光雷达",
        capacity_current=500, capacity_unit="万支/年",
        utilization=0.80, capacity_building=200,
        production_date="2026Q3",
        status="在产",
        notes="激光雷达传感器，车载+机器人感知"
    ),
])

# ── 机器人本体 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="机器人", ticker="300024",
        segment="机器人本体", product="工业机器人/AGV",
        capacity_current=1, capacity_unit="万台/年",
        utilization=0.80, capacity_building=0,
        status="在产",
        notes="国产工业机器人龙头，人形机器人整机研发中"
    ),
    CapacityEntry(
        company="埃斯顿", ticker="002747",
        segment="机器人本体", product="工业机器人本体",
        capacity_current=3, capacity_unit="万台/年",
        utilization=0.75, capacity_building=2,
        production_date="2026Q2",
        status="在产",
        notes="国产机器人本体出货量第一，焊接/搬运机器人"
    ),
    CapacityEntry(
        company="拓普集团", ticker="601689",
        segment="机器人本体", product="人形机器人关节模块",
        capacity_current=0.5, capacity_unit="万台/年",
        utilization=0.60, capacity_building=2,
        production_date="2027Q1",
        status="在建",
        notes="为T客户做人形机器人关节执行器，2025Q4小批量，2027年规划5万台"
    ),
])

# ── 高温合金/钛合金 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="钢研高纳", ticker="300034",
        segment="高温合金/钛合金", product="高温合金",
        capacity_current=1, capacity_unit="万吨/年",
        utilization=0.85, capacity_building=0.5,
        production_date="2026Q3",
        status="在产",
        notes="航发高温合金国内第一，单晶叶片已量产，供货航发动力/成发"
    ),
    CapacityEntry(
        company="西部超导", ticker="688122",
        segment="高温合金/钛合金", product="钛合金棒材/丝材",
        capacity_current=0.8, capacity_unit="万吨/年",
        utilization=0.80, capacity_building=0.3,
        production_date="2026Q2",
        status="在产",
        notes="钛合金龙头，供货航发/军机/无人机，QANTAS商飞供应商"
    ),
    CapacityEntry(
        company="中航重机", ticker="600765",
        segment="高温合金/钛合金", product="锻件/铸件",
        capacity_current=5, capacity_unit="万吨/年",
        utilization=0.75, capacity_building=2,
        production_date="2026Q4",
        status="在产",
        notes="航空锻件龙头，供应航发/军机/舰船，技改扩产中"
    ),
])

# ── 航发整机 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="航发动力", ticker="600893",
        segment="航发整机", product="军用航空发动机",
        capacity_current=0.3, capacity_unit="万台/年",
        utilization=0.90, capacity_building=0.1,
        production_date="2026Q4",
        status="在产",
        notes="航发唯一整机平台，涡扇-10/15/20系列量产，产能持续扩张"
    ),
    CapacityEntry(
        company="航发科技", ticker="600893",
        segment="航发整机", product="航发零部件/叶片",
        capacity_current=0.2, capacity_unit="万吨/年",
        utilization=0.85, capacity_building=0.1,
        status="在产",
        notes="航发盘/轴/机匣制造，外贸转包+国内航发"
    ),
])

# ── 军机/无人机 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="中航沈飞", ticker="600760",
        segment="军机/无人机", product="歼击机/无人机",
        capacity_current=50, capacity_unit="架/年",
        utilization=0.85, capacity_building=20,
        production_date="2026Q3",
        status="在产",
        notes="歼-16/鹘鹰量产，舰载机+无人机方向扩张"
    ),
    CapacityEntry(
        company="中航西飞", ticker="000768",
        segment="军机/无人机", product="运输机/预警机",
        capacity_current=30, capacity_unit="架/年",
        utilization=0.80, capacity_building=10,
        status="在产",
        notes="运-20/空警-500量产，军用大飞机唯一平台"
    ),
    CapacityEntry(
        company="航天彩虹", ticker="002389",
        segment="军机/无人机", product="军用无人机",
        capacity_current=200, capacity_unit="架/年",
        utilization=0.75, capacity_building=100,
        production_date="2026Q2",
        status="在产",
        notes="彩虹系列无人机龙头，内销+出口中东，订单饱满"
    ),
])

# ── 导弹/精确制导 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="洪都航空", ticker="600316",
        segment="导弹/精确制导", product="空空导弹/空地导弹",
        capacity_current=0.5, capacity_unit="万枚/年",
        utilization=0.80, capacity_building=0.3,
        production_date="2026Q4",
        status="在产",
        notes="国产导弹总装平台，PL-15/PL-10批量供货"
    ),
    CapacityEntry(
        company="北方导航", ticker="600435",
        segment="导弹/精确制导", product="制导系统/惯导",
        capacity_current=2, capacity_unit="万套/年",
        utilization=0.75, capacity_building=1,
        status="在产",
        notes="制导控制核心，精确制导武器惯导系统"
    ),
])

# ── 军工信息化 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="航天电器", ticker="002025",
        segment="军工信息化", product="军用连接器/线缆",
        capacity_current=5, capacity_unit="亿只/年",
        utilization=0.85, capacity_building=2,
        production_date="2026Q3",
        status="在产",
        notes="军用连接器龙头，航天科工集团背景，受益于装备信息化建设"
    ),
    CapacityEntry(
        company="中航光电", ticker="002179",
        segment="军工信息化", product="光连接器/电连接器",
        capacity_current=10, capacity_unit="亿只/年",
        utilization=0.90, capacity_building=5,
        production_date="2026Q2",
        status="在产",
        notes="中航系连接器龙头，军品占比高，扩产中"
    ),
])

# ── 商业航天 ──────────────────────────────────────────────
CAPACITY_DATABASE.extend([
    CapacityEntry(
        company="长光卫星", ticker="688048",
        segment="商业航天", product="遥感卫星",
        capacity_current=30, capacity_unit="颗/年",
        utilization=0.70, capacity_building=20,
        production_date="2026Q4",
        status="在产",
        notes="遥感卫星星座建设，吉林一号卫星批量生产"
    ),
    CapacityEntry(
        company="上海沪工", ticker="603880",
        segment="商业航天", product="火箭结构件/焊接",
        capacity_current=0.5, capacity_unit="万套/年",
        utilization=0.75, capacity_building=0.3,
        status="在产",
        notes="商业火箭结构件供应商，受益于国内商业航天快速扩张"
    ),
    CapacityEntry(
        company="航宇科技", ticker="688239",
        segment="商业航天", product="环锻件/冲压件",
        capacity_current=2, capacity_unit="万吨/年",
        utilization=0.80, capacity_building=1,
        production_date="2026Q3",
        status="在产",
        notes="环锻件用于火箭/卫星/导弹，商业航天订单增长"
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

    # ── 存储制造 ─────────────────────────────────────────────
    CyclePhase("存储制造", "过剩", "2022Q3", "2023Q4", -0.35, "急跌"),
    CyclePhase("存储制造", "去化", "2024Q1", "2024Q2", -0.15, "缓跌"),
    CyclePhase("存储制造", "紧缺", "2024Q3", None, 0.25, "急涨"),
    CyclePhase("存储制造", "紧缺", "2025Q1", None, 0.30, "上涨"),

    # ── HBM/高带宽存储 ──────────────────────────────────────
    CyclePhase("HBM/高带宽存储", "紧缺", "2023Q1", None, 0.40, "急涨"),
    CyclePhase("HBM/高带宽存储", "紧缺", "2025Q1", None, 0.45, "急涨"),

    # ── 存储封测 ─────────────────────────────────────────────
    CyclePhase("存储封测", "过剩", "2022Q4", "2023Q4", -0.25, "下跌"),
    CyclePhase("存储封测", "紧缺", "2024Q3", None, 0.15, "上涨"),

    # ── 模组/SSD ─────────────────────────────────────────────
    CyclePhase("模组/SSD", "过剩", "2022Q3", "2023Q2", -0.30, "急跌"),
    CyclePhase("模组/SSD", "紧缺", "2024Q3", None, 0.20, "上涨"),

    # ── 正极材料 ─────────────────────────────────────────────
    CyclePhase("正极材料", "过剩", "2023Q1", "2024Q2", -0.30, "下跌"),
    CyclePhase("正极材料", "去化", "2024Q3", "2025Q1", -0.10, "缓跌"),
    CyclePhase("正极材料", "均衡", "2025Q2", None, 0.0, "平稳"),

    # ── 负极材料 ─────────────────────────────────────────────
    CyclePhase("负极材料", "过剩", "2023Q2", "2024Q1", -0.25, "下跌"),
    CyclePhase("负极材料", "均衡", "2024Q2", "2025Q1", 0.0, "平稳"),
    CyclePhase("负极材料", "紧缺", "2025Q2", None, 0.10, "上涨"),

    # ── 隔膜 ─────────────────────────────────────────────────
    CyclePhase("隔膜", "过剩", "2023Q1", "2024Q2", -0.20, "下跌"),
    CyclePhase("隔膜", "去化", "2024Q3", "2025Q1", -0.10, "缓跌"),
    CyclePhase("隔膜", "均衡", "2025Q2", None, 0.0, "平稳"),

    # ── 电解液 ─────────────────────────────────────────────
    CyclePhase("电解液", "过剩", "2022Q4", "2024Q1", -0.35, "急跌"),
    CyclePhase("电解液", "去化", "2024Q2", "2025Q1", -0.10, "缓跌"),
    CyclePhase("电解液", "均衡", "2025Q2", None, 0.0, "平稳"),

    # ── 电芯/PACK ─────────────────────────────────────────────
    CyclePhase("电芯/PACK", "过剩", "2023Q2", "2024Q2", -0.25, "下跌"),
    CyclePhase("电芯/PACK", "去化", "2024Q3", "2025Q1", -0.10, "缓跌"),
    CyclePhase("电芯/PACK", "均衡", "2025Q2", None, 0.0, "平稳"),

    # ── 减速器 ─────────────────────────────────────────────
    CyclePhase("减速器", "紧缺", "2023Q1", None, 0.20, "上涨"),
    CyclePhase("减速器", "紧缺", "2025Q1", None, 0.25, "上涨"),

    # ── 伺服驱动 ─────────────────────────────────────────────
    CyclePhase("伺服驱动", "紧缺", "2024Q1", None, 0.18, "上涨"),

    # ── 控制器 ─────────────────────────────────────────────
    CyclePhase("控制器", "均衡", "2024Q1", None, 0.05, "平稳"),

    # ── 传感器 ─────────────────────────────────────────────
    CyclePhase("传感器", "紧缺", "2025Q1", None, 0.20, "上涨"),

    # ── 机器人本体 ─────────────────────────────────────────────
    CyclePhase("机器人本体", "紧缺", "2025Q1", None, 0.30, "急涨"),

    # ── 高温合金/钛合金 ─────────────────────────────────────────────
    CyclePhase("高温合金/钛合金", "紧缺", "2023Q1", "2025Q2", 0.15, "上涨"),
    CyclePhase("高温合金/钛合金", "均衡", "2025Q3", None, 0.02, "平稳"),

    # ── 航发整机 ─────────────────────────────────────────────
    CyclePhase("航发整机", "紧缺", "2023Q1", None, 0.20, "上涨"),
    CyclePhase("航发整机", "紧缺", "2025Q2", None, 0.25, "上涨"),

    # ── 军机/无人机 ─────────────────────────────────────────────
    CyclePhase("军机/无人机", "紧缺", "2024Q1", None, 0.20, "上涨"),

    # ── 导弹/精确制导 ─────────────────────────────────────────────
    CyclePhase("导弹/精确制导", "紧缺", "2024Q1", None, 0.25, "上涨"),

    # ── 军工信息化 ─────────────────────────────────────────────
    CyclePhase("军工信息化", "紧缺", "2024Q1", None, 0.15, "上涨"),

    # ── 商业航天 ─────────────────────────────────────────────
    CyclePhase("商业航天", "紧缺", "2024Q1", None, 0.30, "急涨"),
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
        # ── 半导体 ──────────────────────────────────────────────
        "硅片/晶圆": [("688126", "沪硅产业"), ("688432", "有研硅"), ("002129", "中环股份"), ("605358", "立昂微")],
        "晶圆代工": [("688981", "中芯国际"), ("688347", "华虹半导体"), ("TSM", "台积电")],
        "半导体设备": [("002371", "北方华创"), ("688012", "中微公司"), ("688072", "拓荆科技"), ("688120", "华海清科"), ("ASML", "ASML")],
        "封装测试": [("600584", "长电科技"), ("002156", "通富微电"), ("002185", "华天科技")],
        "光模块": [("300308", "中际旭创"), ("002281", "光迅科技"), ("300502", "新易盛"), ("300548", "博创科技"), ("300394", "天孚通信")],
        "光芯片": [("600703", "三安光电"), ("688498", "源杰科技"), ("688313", "仕佳光子")],
        "PCB/载板": [("002916", "深南电路"), ("600183", "生益科技"), ("688188", "南亚新材")],

        # ── 存储 ──────────────────────────────────────────────
        "存储制造": [("NAND", "长江存储"), ("DRAM", "合肥长鑫"), ("SMSN", "三星"), ("000660", "SK海力士"), ("MU", "美光")],
        "存储封测": [("002156", "通富微电"), ("002185", "华天科技"), ("600667", "太极实业")],
        "HBM/高带宽存储": [("000660", "SK海力士"), ("SMSN", "三星"), ("MU", "美光")],
        "模组/SSD": [("301308", "江波龙"), ("300542", "朗科科技")],

        # ── 锂电 ──────────────────────────────────────────────
        "正极材料": [("688005", "容百科技"), ("300073", "当升科技"), ("301358", "湖南裕能"), ("300769", "德方纳米")],
        "负极材料": [("688185", "贝特瑞"), ("603659", "璞泰来"), ("300035", "中科电气")],
        "隔膜": [("002812", "恩捷股份"), ("300568", "星源材质")],
        "电解液": [("002709", "天赐材料"), ("300037", "新宙邦")],
        "锂电设备": [("300450", "先导智能"), ("300457", "赢合科技")],
        "电芯/PACK": [("300750", "宁德时代"), ("002594", "比亚迪"), ("300014", "亿纬锂能")],

        # ── 机器人 ──────────────────────────────────────────────
        "减速器": [("688017", "绿的谐波"), ("002472", "双环传动"), ("002896", "中大力德")],
        "伺服驱动": [("300124", "汇川技术"), ("688255", "禾川科技"), ("002747", "埃斯顿")],
        "控制器": [("688777", "中控技术"), ("300161", "华中数控")],
        "传感器": [("688122", "坤维科技"), ("688286", "敏芯股份"), ("688001", "华工科技")],
        "机器人本体": [("300024", "机器人"), ("002747", "埃斯顿"), ("601689", "拓普集团")],

        # ── 军工/商业航天 ──────────────────────────────────────────────
        "高温合金/钛合金": [("300034", "钢研高纳"), ("688122", "西部超导"), ("600765", "中航重机")],
        "航发整机": [("600893", "航发动力")],
        "军机/无人机": [("600760", "中航沈飞"), ("000768", "中航西飞"), ("002389", "航天彩虹")],
        "导弹/精确制导": [("600316", "洪都航空"), ("600435", "北方导航")],
        "军工信息化": [("002025", "航天电器"), ("002179", "中航光电")],
        "商业航天": [("688048", "长光卫星"), ("603880", "上海沪工"), ("688239", "航宇科技")],
    }
    return mapping.get(segment, [])


def get_all_chain_segments() -> list[str]:
    """返回所有产业链环节"""
    return list(set(e.segment for e in CAPACITY_DATABASE))


def print_supply_chain_report():
    """打印完整供需链报告"""
    all_segments = list(set(e.segment for e in CAPACITY_DATABASE))
    print("=" * 80)
    print("📊 全产业链供需全景 (半导体+光通信+存储+锂电+机器人+军工)")
    print("=" * 80)

    for seg in sorted(all_segments):
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
