# Mac 部署说明

## 1. 克隆项目

```bash
git clone https://github.com/pcb-algo-wiki/quant-trading.git
cd quant-trading
```

## 2. 安装依赖

推荐使用 Python 3.11+：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. 配置 API Key

创建 `.env` 文件（**不要提交到 git**）：

```bash
cat > .env << 'EOF'
# 微信推送（PushPlus）
PUSHPLUS_TOKEN=482ac3816f124fd59aa2e5a921bca9f5

# 美股数据（Polygon.io）
POLYGON_API_KEY=zseHY9eupZvFPb8v4N0xsUI92dDgW_vw
EOF
```

## 4. 验证配置

```bash
python run.py --daily-pipeline --dry-run
```

## 5. 手动运行流水线

```bash
# 标准运行
python run.py --daily-pipeline

# 带微信推送
python run.py --daily-pipeline --notify

# 仅看实时新闻
python data/realtime_news.py
```

## 6. 设置定时任务（cron，每5分钟，交易时段）

编辑 crontab：

```bash
crontab -e
```

添加以下内容（根据你的实际路径修改）：

```cron
# 量化交易流水线 - 交易时段每5分钟刷新（北京时间 09:00-15:30）
# 注意：cron 用 UTC 时间，北京时间 = UTC+8
# 北京 09:00-11:30 = UTC 01:00-03:30
*/5 1,2,3 * * 1-5 cd /path/to/quant-trading && source .venv/bin/activate && python run.py --daily-pipeline --notify >> logs/cron.log 2>&1
# 北京 13:00-15:30 = UTC 05:00-07:30
*/5 5,6,7 * * 1-5 cd /path/to/quant-trading && source .venv/bin/activate && python run.py --daily-pipeline --notify >> logs/cron.log 2>&1
```

或者使用 **launchd**（Mac 推荐，更稳定）：

```bash
# 创建 launchd plist
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.quant.pipeline.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.quant.pipeline</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/quant-trading/.venv/bin/python</string>
        <string>/path/to/quant-trading/run.py</string>
        <string>--daily-pipeline</string>
        <string>--notify</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/quant-trading</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PUSHPLUS_TOKEN</key>
        <string>482ac3816f124fd59aa2e5a921bca9f5</string>
        <key>POLYGON_API_KEY</key>
        <string>zseHY9eupZvFPb8v4N0xsUI92dDgW_vw</string>
    </dict>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/path/to/quant-trading/logs/pipeline.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/quant-trading/logs/pipeline_err.log</string>
</dict>
</plist>
EOF

# 加载定时任务
launchctl load ~/Library/LaunchAgents/com.quant.pipeline.plist
```

> ⚠️ 把所有 `/path/to/quant-trading` 替换为你 Mac 上的实际路径，例如 `/Users/yourname/quant-trading`

## 7. 查看日志

```bash
tail -f logs/pipeline.log
tail -f logs/quant.log
```

## 8. 运行测试

```bash
python -m pytest -q
# 预期: 228 passed
```
