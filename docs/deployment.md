# 量化项目云服务器部署指南

## 环境要求

| 项目 | 要求 |
|------|------|
| OS | Ubuntu 22.04+ / macOS 13+ |
| Python | 3.11+ |
| 内存 | ≥8GB（推荐 16GB） |
| 磁盘 | ≥50GB SSD |
| 网络 | 能访问国内财经数据源 + HuggingFace（可选） |

---

## 一、快速安装（Ubuntu 22.04）

### 1. 系统依赖

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y \
  python3.11 python3.11-venv python3.11-dev \
  git curl build-essential libssl-dev zlib1g-dev libbz2-dev \
  libreadline-dev libsqlite3-dev libncurses5-dev libffi-dev \
  liblzma-dev libsnappy-dev
```

### 2. 项目克隆

```bash
git clone https://github.com/pcb-algo-wiki/quant-trading.git
cd quant-trading
```

### 3. 创建虚拟环境

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### 4. 安装依赖

```bash
# 稳定依赖（国内镜像）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 如果需要 sentence-transformers（需要访问 HuggingFace）
pip install sentence-transformers -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 5. 目录初始化

```bash
# 数据目录（SQLite、pkl缓存、向量库）
mkdir -p data/cache/vector_store data/cache/stocks data/cache/industry_events
mkdir -p results/events results/knowledge results/papers

# llmwiki 目录
mkdir -p llmwiki/wiki/{industry,company,policy}

# 日志目录
mkdir -p logs
```

### 6. 验证安装

```bash
cd ~/quant-trading
.venv/bin/python -c "
import akshare, pandas, sklearn, networkx, jieba
from knowledge.vector_store import VectorStore
from knowledge.retrieval import HybridRetriever
print('✅ 所有依赖正常')
"
```

---

## 二、数据初始化

首次部署需要填充基础数据（历史行情、新闻、产业链图谱）：

```bash
cd ~/quant-trading

# 1. 填充历史行情（需要交易日数据，ETF: 510300/510500/159915）
.venv/bin/python scripts/fill_historical_bars.py

# 2. 填充新闻和事件（从东方财富/新浪抓取实时数据）
.venv/bin/python scripts/fill_news_events.py

# 3. 构建产业链图谱（龙头公司 + 供应关系 + 政策节点）
.venv/bin/python scripts/build_industry_chain.py

# 4. 从新闻抽取实体构建知识图谱
.venv/bin/python scripts/build_knowledge_graph.py

# 5. 同步到 llmwiki Markdown 卡片
.venv/bin/python scripts/sync_llmwiki.py

# 6. 构建向量库（TF-IDF + SVD，85条news已向量化）
.venv/bin/python scripts/build_vector_store.py
```

---

## 三、Cron 定时任务配置

### 工作日实时数据（每5分钟）

```bash
# 编辑 crontab
crontab -e

# 添加以下行（路径替换为实际路径）：
*/5 9-15 * * 1-5 cd /home/ubuntu/quant-trading && /home/ubuntu/quant-trading/.venv/bin/python scripts/update_data_store.py >> logs/cron_5min.log 2>&1
*/5 9-15 * * 1-5 cd /home/ubuntu/quant-trading && /home/ubuntu/quant-trading/.venv/bin/python scripts/update_knowledge.py >> logs/cron_5min.log 2>&1
*/5 9-15 * * 1-5 cd /home/ubuntu/quant-trading && /home/ubuntu/quant-trading/.venv/bin/scripts/update_events.py >> logs/cron_5min.log 2>&1
*/5 9-15 * * 1-5 cd /home/ubuntu/quant-trading && /home/ubuntu/quant-trading/.venv/bin/python scripts/build_knowledge_graph.py >> logs/cron_5min.log 2>&1
*/5 9-15 * * 1-5 cd /home/ubuntu/quant-trading && /home/ubuntu/quant-trading/.venv/bin/python scripts/sync_llmwiki.py >> logs/cron_5min.log 2>&1
*/5 9-15 * * 1-5 cd /home/ubuntu/quant-trading && /home/ubuntu/quant-trading/.venv/bin/python scripts/build_vector_store.py >> logs/cron_5min.log 2>&1
```

> ⚠️ 注意：Hercules Agent 的 cron job 是在 Agent 侧管理的，上云后需要在服务器上用系统 crontab 替代，或保留 Agent 的 cron 功能（需要保持 Agent 运行）。

### 每日流程（工作日 07:50）

```bash
# 每日量化流水线
50 7 * * 1-5 cd /home/ubuntu/quant-trading && PUSHPLUS_TOKEN=your_token_here .venv/bin/python run.py --daily-pipeline >> logs/cron_daily.log 2>&1
```

### A股/美股每日扫描（工作日 08:00/08:30）

```bash
# A股扫描
0 8 * * 1-5 cd /home/ubuntu/quant-trading && PUSHPLUS_TOKEN=your_token_here .venv/bin/python scripts/stock_scan.py >> logs/cron_stock.log 2>&1
# 美股扫描
30 8 * * 1-5 cd /home/ubuntu/quant-trading && PUSHPLUS_TOKEN=your_token_here .venv/bin/python scripts/us_stock_scan.py >> logs/cron_us.log 2>&1
```

---

## 四、环境变量配置

```bash
# 创建 .env 文件（不要提交到 git）
cat > ~/quant-trading/.env << 'EOF'
# 微信推送（可选，不填则不推送）
PUSHPLUS_TOKEN=your_pushplus_token_here

# 雪球Cookie（可选，A股数据增强）
XUEQIU_COOKIE=your_xueqiu_cookie_here

# 聚宽数据（可选）
JQDATA_USER=your_jqdata_username
JQDATA_PASSWORD=your_jqdata_password

# GitHub（用于代码推送，如需要）
GITHUB_TOKEN=ghp_your_github_token_here
EOF

chmod 600 ~/quant-trading/.env
```

---

## 五、Nginx + Gunicorn Web 服务（可选）

```bash
# 安装 nginx + gunicorn
sudo apt-get install -y nginx
pip install gunicorn

# nginx 配置
sudo cat > /etc/nginx/sites-available/quant-trading << 'EOF'
server {
    listen 8080;
    server_name your_server_ip;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/quant-trading /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 启动 Flask + Gunicorn
cd ~/quant-trading
nohup .venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 'app:app' --timeout 120 --log-file logs/gunicorn.log &
```

---

## 六、Docker 部署（推荐）

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y \
    build-essential libssl-dev git curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 项目文件
COPY . .

# 数据目录
RUN mkdir -p data/cache/vector_store data/cache/stocks data/cache/industry_events
RUN mkdir -p results/events results/knowledge results/papers
RUN mkdir -p llmwiki/wiki/{industry,company,policy} logs

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "app:app"]
```

### docker-compose.yml

```yaml
version: '3.8'
services:
  quant:
    build: .
    restart: unless-stopped
    ports:
      - "8080:8000"
    volumes:
      - ./data:/app/data
      - ./results:/app/results
      - ./logs:/app/logs
      - ./llmwiki:/app/llmwiki
    environment:
      - PUSHPLUS_TOKEN=${PUSHPLUS_TOKEN}
    cron:
      enabled: true
```

### 构建和运行

```bash
docker build -t quant-trading .
docker run -d --name quant-trading \
  -p 8080:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/results:/app/results \
  -v $(pwd)/logs:/app/logs \
  -e PUSHPLUS_TOKEN=your_token \
  quant-trading
```

---

## 七、常见问题排查

### 1. akshare 抓不到数据

```bash
# 检查网络
curl -I https://push2.eastmoney.com

# 可能是Cookie过期，akshare某些接口需要登录Cookie
# 查看具体错误
.venv/bin/python -c "import akshare as ak; ak.stock_zh_a_spot_em()"
```

### 2. 向量库检索返回空

```bash
# 检查向量库是否构建
ls -la data/cache/vector_store/

# 检查 news_items 是否有数据
.venv/bin/python -c "
from data_store.db import get_connection
with get_connection() as conn:
    print(conn.execute('SELECT COUNT(*) FROM news_items').fetchone())
"
```

### 3. sentence-transformers 模型下载失败

```bash
# 设置镜像源
export HF_ENDPOINT=https://hf-mirror.com

# 或手动下载模型
.venv/bin/python -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('all-MiniLM-L6-v2')
print('✅ 模型加载成功')
"
```

### 4. SQLite 数据库被锁

```bash
# 杀掉所有占用进程
lsof data/cache/quant_data.db
kill -9 <PID>
```

---

## 八、迁移清单

从本机迁移到云服务器时，确保以下文件/目录已同步：

```
✅ requirements.txt           # Python 依赖
✅ .env                       # 环境变量（不含 Token）
✅ config.yaml                # 配置文件
✅ knowledge/                 # 知识图谱模块（含 industry_chain.py）
✅ data_store/                # 数据存储模块
✅ scripts/                   # 所有脚本（含 build_*.py）
✅ llmwiki/                  # Wiki 目录结构
✅ app.py / run.py           # 入口文件
✅ docs/                     # 文档

⏭️ data/cache/               # 首次部署时由脚本重建，不提交
⏭️ results/                  # 首次部署时由脚本重建，不提交
⏭️ .venv/                    # 云服务器上重新 pip install
⏭️ logs/                     # 运行时生成
```

---

## 九、网络说明

| 数据源 | 域名 | 用途 |
|--------|------|------|
| 东方财富 | push2.eastmoney.com | A股实时行情 |
| 新浪财经 | finance.sina.com.cn | 新闻/行情 |
| 同花顺 | q.10jqka.com.cn | 资金流向 |
| HuggingFace | hf-mirror.com（国内镜像） | 向量模型（可选）|
| GitHub | github.com | 代码同步 |
