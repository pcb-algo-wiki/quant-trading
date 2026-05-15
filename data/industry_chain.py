"""
data/industry_chain.py
=====================
产业链分析方法论 — 新趋势驱动的产业链分析框架

层次结构:
  Signal（信号识别）→ Map（产业链映射）→ Validate（量化验证）→ Loop（策略闭环）

核心思想:
  - 新趋势（政策/产品/资金）催生新产业链机会
  - 通过产业链图谱定位最受益环节
  - 用历史事件库验证规律，形成可复用的策略

⚠️ 注意:
  - 产业链图谱需要人工维护，持续迭代
  - 历史事件库是框架的核心资产
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True, parents=True)
EVENTS_DIR = CACHE_DIR / "industry_events"
EVENTS_DIR.mkdir(exist_ok=True, parents=True)


# ============ 产业链基础组件 ============

class TrendSignal(Enum):
    """趋势信号来源"""
    POLICY = "policy"           # 政策文件/补贴/禁运
    PRODUCT = "product"        # 新产品发布
    CAPITAL = "capital"        # 资金异常流动
    SENTIMENT = "sentiment"    # 市场情绪/分析师评级
    MACRO = "macro"            # 宏观数据变动


class ChainLevel(Enum):
    """产业链层级"""
    RAW_MATERIAL = "上游材料"      # 矿产、化工原料
    CORE_COMPONENT = "核心零部件" # 芯片、电池、传感器
    EQUIPMENT = "设备/工具"       # 生产设备、精密仪器
    MANUFACTURING = "制造/组装"   # OEM、代工
    DISTRIBUTION = "流通/渠道"    # 经销商、电商
    TERMINAL = "终端产品"         # 面向消费者的产品


@dataclass
class ChainNode:
    """产业链节点"""
    name: str                   # 节点名称
    level: ChainLevel           # 属于哪一层
    securities: List[str] = field(default_factory=list)  # 相关证券代码
    substitutes: List[str] = field(default_factory=list)   # 国产替代品牌
    bottleneck: float = 0.0    # 卡脖子程度 0~1
    capacity_util: float = 0.0 # 产能利用率 0~1


@dataclass
class IndustryChain:
    """完整产业链"""
    trend: str                  # 所属趋势名称
    nodes: List[ChainNode] = field(default_factory=list)
    cycle_months: int = 12      # 典型演绎周期
    policy_sensitivity: float = 0.5  # 政策敏感度 0~1

    def get_node(self, name: str) -> Optional[ChainNode]:
        for node in self.nodes:
            if node.name == name:
                return node
        return None

    def get_level(self, level: ChainLevel) -> List[ChainNode]:
        return [n for n in self.nodes if n.level == level]


# ============ 产业链图谱（预定义） ============
# 这是框架的核心资产，需要持续迭代更新

INDUSTRY_CHAINS: Dict[str, IndustryChain] = {}


def _init_chains():
    """初始化预定义产业链图谱"""
    global INDUSTRY_CHAINS

    # ---- AI人工智能 ----
    INDUSTRY_CHAINS["AI"] = IndustryChain(
        trend="AI人工智能",
        cycle_months=18,
        policy_sensitivity=0.7,
        nodes=[
            ChainNode("GPU/AI芯片", ChainLevel.CORE_COMPONENT,
                      securities=["NVDA", "AMD", "寒武纪", "海光信息"],
                      substitutes=["英伟达", "AMD"],
                      bottleneck=0.9),
            ChainNode("算力服务器", ChainLevel.MANUFACTURING,
                      securities=["浪潮信息", "华为", "中兴通讯"],
                      substitutes=["戴尔", "惠普"],
                      bottleneck=0.6),
            ChainNode("光模块/光通信", ChainLevel.CORE_COMPONENT,
                      securities=["中际旭创", "新易盛", "剑桥科技"],
                      bottleneck=0.5),
            ChainNode("数据中心/电力", ChainLevel.EQUIPMENT,
                      securities=["万国数据", "秦淮数据", "科华数据"],
                      bottleneck=0.4),
            ChainNode("云计算/IaaS", ChainLevel.DISTRIBUTION,
                      securities=["AWS", "Azure", "阿里云", "腾讯云"],
                      bottleneck=0.3),
            ChainNode("AI应用/软件", ChainLevel.TERMINAL,
                      securities=["OpenAI", "Anthropic", "百度", "科大讯飞"],
                      bottleneck=0.2),
            ChainNode("散热/液冷", ChainLevel.EQUIPMENT,
                      securities=["英维克", "申菱环境", "艾默生"],
                      bottleneck=0.5),
            ChainNode("PCB/覆铜板", ChainLevel.RAW_MATERIAL,
                      securities=["生益科技", "华正新材", "南亚新材"],
                      bottleneck=0.4),
        ]
    )

    # ---- 半导体/芯片 ----
    INDUSTRY_CHAINS["半导体"] = IndustryChain(
        trend="半导体国产替代",
        cycle_months=24,
        policy_sensitivity=0.95,
        nodes=[
            ChainNode("芯片设计/EDA", ChainLevel.CORE_COMPONENT,
                      securities=["华大九天", "概伦电子", "芯愿景"],
                      substitutes=["Synopsys", "Cadence"],
                      bottleneck=0.95),
            ChainNode("晶圆制造/代工", ChainLevel.MANUFACTURING,
                      securities=["中芯国际", "华虹半导体"],
                      substitutes=["台积电", "三星"],
                      bottleneck=0.95),
            ChainNode("封装测试", ChainLevel.MANUFACTURING,
                      securities=["长电科技", "通富微电", "华天科技"],
                      bottleneck=0.4),
            ChainNode("半导体设备", ChainLevel.EQUIPMENT,
                      securities=["北方华创", "中微公司", "拓荆科技"],
                      substitutes=["应用材料", "LAM"],
                      bottleneck=0.9),
            ChainNode("硅片/材料", ChainLevel.RAW_MATERIAL,
                      securities=["沪硅产业", "立昂微", "中环股份"],
                      bottleneck=0.7),
        ]
    )

    # ---- 新能源汽车 ----
    INDUSTRY_CHAINS["新能源车"] = IndustryChain(
        trend="新能源汽车",
        cycle_months=36,
        policy_sensitivity=0.8,
        nodes=[
            ChainNode("锂矿/碳酸锂", ChainLevel.RAW_MATERIAL,
                      securities=["赣锋锂业", "天齐锂业", "盐湖股份"],
                      bottleneck=0.8),
            ChainNode("钴镍/三元前驱体", ChainLevel.RAW_MATERIAL,
                      securities=["华友钴业", "格林美", "寒锐钴业"],
                      bottleneck=0.6),
            ChainNode("正极材料", ChainLevel.RAW_MATERIAL,
                      securities=["容百科技", "当升科技", "德方纳米"],
                      bottleneck=0.5),
            ChainNode("负极材料/石墨", ChainLevel.RAW_MATERIAL,
                      securities=["贝特瑞", "璞泰来", "杉杉股份"],
                      bottleneck=0.4),
            ChainNode("电解液/隔膜", ChainLevel.RAW_MATERIAL,
                      securities=["天赐材料", "新宙邦", "恩捷股份"],
                      bottleneck=0.4),
            ChainNode("动力电池", ChainLevel.CORE_COMPONENT,
                      securities=["宁德时代", "比亚迪", "中创新航"],
                      bottleneck=0.5),
            ChainNode("电池设备", ChainLevel.EQUIPMENT,
                      securities=["先导智能", "赢合科技", "杭可科技"],
                      bottleneck=0.6),
            ChainNode("电机/电控", ChainLevel.CORE_COMPONENT,
                      securities=["汇川技术", "卧龙电驱", "麦格米特"],
                      bottleneck=0.3),
            ChainNode("整车制造", ChainLevel.MANUFACTURING,
                      securities=["比亚迪", "理想汽车", "蔚来汽车", "小鹏汽车"],
                      bottleneck=0.2),
            ChainNode("充电桩/运营", ChainLevel.DISTRIBUTION,
                      securities=["特锐德", "星星充电", "国家电网"],
                      bottleneck=0.3),
        ]
    )

    # ---- 人形机器人 ----
    INDUSTRY_CHAINS["人形机器人"] = IndustryChain(
        trend="人形机器人",
        cycle_months=60,
        policy_sensitivity=0.9,
        nodes=[
            ChainNode("减速器", ChainLevel.CORE_COMPONENT,
                      securities=["绿的谐波", "来福谐波", "日本哈默纳科"],
                      substitutes=["日本哈默纳科", "纳博特斯克"],
                      bottleneck=0.95),
            ChainNode("伺服电机", ChainLevel.CORE_COMPONENT,
                      securities=["汇川技术", "禾川科技", "松下", "安川"],
                      substitutes=["西门子", "科尔摩根"],
                      bottleneck=0.8),
            ChainNode("控制器/芯片", ChainLevel.CORE_COMPONENT,
                      securities=["控制算法公司", "AI芯片公司"],
                      bottleneck=0.85),
            ChainNode("传感器/力控", ChainLevel.CORE_COMPONENT,
                      securities=["坤维科技", "敏芯股份", "TE Connectivity"],
                      bottleneck=0.9),
            ChainNode("轴承/关节", ChainLevel.EQUIPMENT,
                      securities=["人本集团", "五洲新春", "南方轴承"],
                      bottleneck=0.7),
            ChainNode("机器人整机", ChainLevel.MANUFACTURING,
                      securities=["Tesla Bot", "宇树科技", "傅利叶", "优必选"],
                      bottleneck=0.6),
            ChainNode("代工/组装", ChainLevel.MANUFACTURING,
                      securities=["富士康", "广达电脑"],
                      bottleneck=0.3),
        ]
    )

    # ---- 固态电池 ----
    INDUSTRY_CHAINS["固态电池"] = IndustryChain(
        trend="固态电池",
        cycle_months=48,
        policy_sensitivity=0.75,
        nodes=[
            ChainNode("固态电解质", ChainLevel.RAW_MATERIAL,
                      securities=["赣锋锂业", "宁德时代", "清陶能源"],
                      substitutes=["丰田", "三星SDI"],
                      bottleneck=0.95),
            ChainNode("正极材料", ChainLevel.RAW_MATERIAL,
                      securities=["容百科技", "当升科技"],
                      bottleneck=0.5),
            ChainNode("负极材料/锂金属", ChainLevel.RAW_MATERIAL,
                      securities=["贝特瑞", "三星SDI"],
                      bottleneck=0.8),
            ChainNode("固态电池制造", ChainLevel.MANUFACTURING,
                      securities=["赣锋锂业", "比亚迪", "QuantumScape"],
                      bottleneck=0.9),
            ChainNode("电池检测/回收", ChainLevel.EQUIPMENT,
                      securities=["宁德时代", "格林美"],
                      bottleneck=0.3),
        ]
    )

    # ---- 低空经济/无人机 ----
    INDUSTRY_CHAINS["低空经济"] = IndustryChain(
        trend="低空经济",
        cycle_months=36,
        policy_sensitivity=0.95,
        nodes=[
            ChainNode("eVTOL/飞行器", ChainLevel.MANUFACTURING,
                      securities=["亿航智能", "小鹏汇天", "Lilium", "Joby"],
                      substitutes=["Joby", "Archer"],
                      bottleneck=0.8),
            ChainNode("无人机整机", ChainLevel.MANUFACTURING,
                      securities=["大疆创新", "道通智能"],
                      bottleneck=0.7),
            ChainNode("核心零部件", ChainLevel.CORE_COMPONENT,
                      securities=["碳纤维材料", "电机电调", "飞控系统"],
                      bottleneck=0.6),
            ChainNode("通信/导航", ChainLevel.EQUIPMENT,
                      securities=["华为", "中兴通讯", "运营商"],
                      bottleneck=0.5),
            ChainNode("雷达/传感器", ChainLevel.CORE_COMPONENT,
                      securities=["禾赛科技", "速腾聚创"],
                      bottleneck=0.7),
            ChainNode("场景运营", ChainLevel.DISTRIBUTION,
                      securities=["顺丰无人机", "美团无人机"],
                      bottleneck=0.3),
        ]
    )

_init_chains()


# ============ 趋势事件记录 ============

@dataclass
class TrendEvent:
    """趋势事件"""
    date: str                   # 事件日期 YYYY-MM-DD
    signal_type: TrendSignal    # 信号来源
    trend: str                  # 所属趋势（如"AI"、"半导体"）
    title: str                  # 事件标题
    description: str            # 事件描述
    impacted_nodes: List[str] = field(default_factory=list)  # 受影响节点
    policy_strength: float = 0.5  # 政策力度 0~1
    market_response: str = ""    # 市场当时反应（事后记录）


class IndustryEventDB:
    """历史产业链事件库"""

    def __init__(self, chain_name: str):
        self.chain_name = chain_name
        self.db_path = EVENTS_DIR / f"{chain_name}_events.json"
        self.events: List[TrendEvent] = []
        self._load()

    def _load(self):
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.events = []
                    for e in data:
                        e = e.copy()
                        e['signal_type'] = TrendSignal(e['signal_type'])  # str → enum
                        self.events.append(TrendEvent(**e))
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                print(f"⚠️ 事件库损坏，已重置: {self.db_path} ({e})")
                self.events = []

    def _save(self):
        # 序列化时将枚举转为字符串
        with open(self.db_path, 'w', encoding='utf-8') as f:
            serialized = []
            for e in self.events:
                d = vars(e).copy()
                d['signal_type'] = e.signal_type.value  # enum → str
                serialized.append(d)
            json.dump(serialized, f, ensure_ascii=False, indent=2)

    def add_event(self, event: TrendEvent):
        self.events.append(event)
        self._save()

    def get_events(self, days: int = 365) -> List[TrendEvent]:
        """获取近days天的事件"""
        cutoff = datetime.now() - timedelta(days=days)
        return [e for e in self.events
                if datetime.strptime(e.date, '%Y-%m-%d') >= cutoff]

    def get_all_events(self) -> List[TrendEvent]:
        return self.events


def analyze_chain_opportunity(chain_name: str) -> dict:
    """
    分析某产业链的当前机会

    返回结构:
    {
        'chain': str,
        'hot_nodes': List[dict],   # 最受益节点（按国产替代率/政策/估值）
        'cycle_position': str,     # 'early' | 'mid' | 'late'
        'policy_score': float,     # 政策支持度
        'recommendation': str,     # 综合建议
    }
    """
    if chain_name not in INDUSTRY_CHAINS:
        return {'error': f'未知产业链: {chain_name}'}

    chain = INDUSTRY_CHAINS[chain_name]

    # 1. 按瓶颈程度排序（越卡脖子越受益）
    sorted_nodes = sorted(chain.nodes,
                         key=lambda n: n.bottleneck + chain.policy_sensitivity * 0.3,
                         reverse=True)

    hot_nodes = [{
        'name': n.name,
        'level': n.level.value,
        'bottleneck': n.bottleneck,
        'securities': n.securities[:5],  # 最多5个
        'top_pick': n.securities[0] if n.securities else '',
    } for n in sorted_nodes[:5]]

    # 2. 估算周期位置（基于已有事件）
    event_db = IndustryEventDB(chain_name)
    recent = event_db.get_events(days=180)
    cycle_position = 'early' if len(recent) < 3 else 'mid' if len(recent) < 8 else 'late'

    return {
        'chain': chain.trend,
        'cycle_months': chain.cycle_months,
        'policy_sensitivity': chain.policy_sensitivity,
        'cycle_position': cycle_position,
        'hot_nodes': hot_nodes,
        'total_events': len(event_db.get_all_events()),
        'recommendation': _generate_recommendation(chain, cycle_position)
    }


def _generate_recommendation(chain: IndustryChain, cycle_position: str) -> str:
    """生成综合建议"""
    if cycle_position == 'early':
        return f"📈 {chain.trend} 早期——布局上游材料/设备（高壁垒，高确定性）"
    elif cycle_position == 'mid':
        return f"🔄 {chain.trend} 中期——轮动到中游制造（产能释放，量升价跌）"
    else:
        return f"🏁 {chain.trend} 后期——关注下游应用/服务（竞争格局稳定）"


# ============ 趋势信号提取 ============

def detect_trend_signal(news_text: str, news_date: str = None) -> List[dict]:
    """
    从新闻文本中检测趋势信号

    匹配规则：
    1. 关键词匹配 → 映射到已有产业链
    2. 计算信号强度（政策类1.0 / 产品类0.8 / 资本类0.6）
    3. 输出受影响节点

    目前是规则匹配，未来可升级为NLP
    """
    news_date = news_date or datetime.now().strftime('%Y-%m-%d')
    signals = []

    # 关键词 → 产业链映射
    keyword_map = {
        "AI": ["人工智能", "大模型", "ChatGPT", "LLM", "AIGC", "生成式AI"],
        "半导体": ["芯片", "半导体", "光刻", "晶圆", "封装", "EUV", "28nm", "7nm", "3nm"],
        "新能源车": ["新能源汽车", "电动车", "锂电池", "动力电池", "充电桩", "续航"],
        "人形机器人": ["人形机器人", "具身智能", "Tesla Bot", "工业机器人", "协作机器人"],
        "固态电池": ["固态电池", "全固态", "半固态", "固态电解质"],
        "低空经济": ["低空经济", "eVTOL", "无人机", "飞行汽车", "城市空中交通"],
    }

    # 信号强度权重
    strength_map = {
        TrendSignal.POLICY: 1.0,      # 政策最强
        TrendSignal.PRODUCT: 0.8,     # 产品次之
        TrendSignal.CAPITAL: 0.6,     # 资本第三
        TrendSignal.MACRO: 0.4,       # 宏观最弱
    }

    for chain_key, keywords in keyword_map.items():
        for kw in keywords:
            if kw in news_text:
                chain = INDUSTRY_CHAINS.get(chain_key)
                if chain:
                    # 估算政策强度
                    policy_keywords = ["补贴", "扶持", "政策", "规划", "纲要", "禁运", "制裁", "国产替代"]
                    strength = 1.0 if any(pk in news_text for pk in policy_keywords) else 0.6

                    # 找最相关的节点
                    impacted = [n.name for n in chain.nodes if any(kw.lower() in n.name.lower() for _ in keywords)][:3]

                    signals.append({
                        'date': news_date,
                        'chain': chain.trend,
                        'chain_key': chain_key,
                        'keyword': kw,
                        'strength': strength,
                        'impacted_nodes': impacted or [n.name for n in chain.nodes[:2]],
                        'bottleneck_score': max([n.bottleneck for n in chain.nodes], default=0.5),
                        'news_title': '',  # 外部会填入真实标题
                    })
                break  # 同一产业链只记录一次

    return signals


# ============ 策略闭环 ============

@dataclass
class ChainSignal:
    """产业链综合信号"""
    chain: str
    timestamp: str
    cycle_position: str           # early | mid | late
    policy_score: float           # 0~1
    bottleneck_score: float       # 0~1
    valuation_score: float        # 0~1（未来接入估值数据）
    composite: float              # 综合得分
    action: str                   # buy | hold | rotate | exit
    target_nodes: List[str]       # 目标节点
    top_picks: List[str]          # 最看好的证券
    reason: str                  # 理由


def generate_chain_signal(chain_name: str) -> ChainSignal:
    """
    生成某产业链的完整信号

    信号生成逻辑:
    - composite = 政策信号(40%) + 瓶颈程度(30%) + 周期位置(20%) + 估值(10%)
    - action:
        early + high_composite → buy（上游材料/设备）
        mid + high_composite → rotate（中游制造）
        late → exit / hold（下游应用）
    """
    analysis = analyze_chain_opportunity(chain_name)
    if 'error' in analysis:
        raise ValueError(analysis['error'])

    chain = INDUSTRY_CHAINS[chain_name]

    # 综合得分计算
    policy_score = chain.policy_sensitivity
    bottleneck_score = np.mean([n.bottleneck for n in chain.nodes])

    # 周期位置得分
    cycle_scores = {'early': 0.9, 'mid': 0.6, 'late': 0.3}
    cycle_score = cycle_scores.get(analysis['cycle_position'], 0.5)

    composite = (
        policy_score * 0.4 +
        bottleneck_score * 0.3 +
        cycle_score * 0.2 +
        0.5 * 0.1  # 估值（占10%，暂用0.5中性值）
    )

    # 操作建议
    if analysis['cycle_position'] == 'early':
        action = 'buy'
        top_nodes = analysis['hot_nodes'][:2]
        reason = f"早期布局，政策+瓶颈双驱动（综合{composite:.2f}）"
    elif analysis['cycle_position'] == 'mid':
        action = 'rotate'
        top_nodes = analysis['hot_nodes'][2:4]
        reason = f"中期轮动，产能释放期（综合{composite:.2f}）"
    else:
        action = 'hold'
        top_nodes = analysis['hot_nodes'][-2:]
        reason = f"后期信号，格局稳定（综合{composite:.2f}）"

    return ChainSignal(
        chain=chain.trend,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M'),
        cycle_position=analysis['cycle_position'],
        policy_score=round(policy_score, 2),
        bottleneck_score=round(bottleneck_score, 2),
        valuation_score=0.5,
        composite=round(composite, 2),
        action=action,
        target_nodes=[n['name'] for n in top_nodes],
        top_picks=[n['top_pick'] for n in top_nodes if n['top_pick']],
        reason=reason,
    )


# ============ 工具函数 ============

def list_chains() -> List[str]:
    """列出所有已注册的产业链"""
    return list(INDUSTRY_CHAINS.keys())


def get_chain_info(chain_name: str) -> dict:
    """获取某产业链的详细信息"""
    if chain_name not in INDUSTRY_CHAINS:
        return {'error': f'未知产业链: {chain_name}'}
    chain = INDUSTRY_CHAINS[chain_name]
    return {
        'name': chain.trend,
        'cycle_months': chain.cycle_months,
        'policy_sensitivity': chain.policy_sensitivity,
        'nodes': [{
            'name': n.name,
            'level': n.level.value,
            'securities': n.securities,
            'bottleneck': n.bottleneck,
        } for n in chain.nodes]
    }


# ============ 主程序测试 ============

if __name__ == '__main__':
    print("=" * 70)
    print("  产业链分析框架 — 新趋势驱动")
    print("=" * 70)

    print("\n📦 已注册的产业链:")
    for k in list_chains():
        info = get_chain_info(k)
        print(f"  • {k}: {info['name']} ({len(info['nodes'])}个节点, 周期{info['cycle_months']}个月)")

    print("\n📊 各产业链机会分析:")
    for k in list_chains():
        r = analyze_chain_opportunity(k)
        print(f"\n  【{r['chain']}】")
        print(f"    周期位置: {r['cycle_position']} | 政策敏感度: {r['policy_sensitivity']}")
        print(f"    推荐: {r['recommendation']}")
        for i, n in enumerate(r['hot_nodes'][:3], 1):
            print(f"    {i}. {n['name']} (卡脖子{n['bottleneck']:.0%}) → {n['securities']}")

    print("\n🔍 趋势信号检测测试:")
    test_news = [
        "工信部发布新能源汽车产业发展规划，补贴延续至2027年",
        "OpenAI发布GPT-5，算力需求暴增，机构大幅买入AI芯片",
        "丰田宣布固态电池量产计划，续航突破1200公里",
    ]
    for news in test_news:
        signals = detect_trend_signal(news)
        print(f"\n  新闻: {news[:40]}...")
        if signals:
            for s in signals:
                print(f"    → {s['chain']} [{s['keyword']}] 强度{s['strength']:.1f}")
        else:
            print(f"    → 未匹配")

    print("\n📡 生成产业链信号:")
    for k in ['AI', '半导体', '新能源车']:
        sig = generate_chain_signal(k)
        print(f"\n  【{sig.chain}】 {sig.timestamp}")
        print(f"    综合得分: {sig.composite} | 操作: {sig.action}")
        print(f"    理由: {sig.reason}")
        print(f"    目标节点: {sig.target_nodes}")
        print(f"    首选: {sig.top_picks}")
