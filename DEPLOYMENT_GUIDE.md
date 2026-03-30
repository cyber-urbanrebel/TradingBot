# ICT Trading Bot — Deployment Guide

## Local Setup (Windows)

### Prerequisites
- Python 3.10+ installed
- Internet connection (for exchange data)

### 1. Install Dependencies

```powershell
cd C:\Users\USER\OneDrive\Documents\TRADING_BOT
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install ccxt pandas numpy scikit-learn xgboost streamlit plotly ta schedule apscheduler python-dotenv colorama requests joblib
```

### 2. Configure Environment

Edit `.env` with your settings:

```env
# Exchange API keys (optional for backtesting — required for live trading)
EXCHANGE_API_KEY=your_binance_api_key
EXCHANGE_SECRET=your_binance_secret
EXCHANGE_SANDBOX=true          # ← keep true until you're confident

# Symbols
CRYPTO_SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT
FOREX_SYMBOLS=EUR/USD,GBP/USD

# Risk
RISK_PER_TRADE_PCT=1.0         # 1% of balance per trade
MAX_DAILY_LOSS_PCT=3.0         # stop trading after 3% daily loss
MAX_OPEN_TRADES=3
DEFAULT_RR_RATIO=3.0           # minimum 3:1 reward-to-risk
```

### 3. Run Commands

```powershell
# Always activate venv first
.\venv\Scripts\Activate.ps1

# Scan all symbols for ICT signals right now
python main.py scan

# Run a backtest
python main.py backtest --symbol BTC/USDT --candles 1000

# Start paper trading (simulated)
python main.py paper --interval 60

# Launch the Streamlit dashboard
python main.py dashboard

# Train the ML model (needs backtest data first)
python main.py train

# Live trading (REAL MONEY — requires API keys + confirmation)
python main.py live
```

---

## Cloud Deployment (VPS / Always-On Server)

### Option A: Linux VPS (DigitalOcean, Hetzner, AWS EC2)

#### 1. Provision a server
- Ubuntu 22.04+, 2 GB RAM minimum
- SSH access configured

#### 2. Upload the project

```bash
scp -r TRADING_BOT/ user@your-server-ip:~/TRADING_BOT/
```

#### 3. Setup on server

```bash
ssh user@your-server-ip
cd ~/TRADING_BOT

# Install Python
sudo apt update && sudo apt install -y python3 python3-venv python3-pip

# Create venv & install
python3 -m venv venv
source venv/bin/activate
pip install ccxt pandas numpy scikit-learn xgboost streamlit plotly ta schedule apscheduler python-dotenv colorama requests joblib
```

#### 4. Configure .env

```bash
cp .env.example .env
nano .env
# Fill in your exchange API keys
```

#### 5. Run as a background service with systemd

Create `/etc/systemd/system/trading-bot.service`:

```ini
[Unit]
Description=ICT Trading Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/TRADING_BOT
ExecStart=/home/your_username/TRADING_BOT/venv/bin/python main.py paper --interval 60
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot
sudo systemctl status trading-bot    # check it's running
sudo journalctl -u trading-bot -f    # view live logs
```

#### 6. Dashboard (optional — expose via reverse proxy)

```bash
# Run dashboard in background
nohup /home/your_username/TRADING_BOT/venv/bin/python -m streamlit run dashboard/app.py --server.port 8501 &
```

To expose publicly, add an Nginx reverse proxy:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

---

### Option B: Railway / Render (PaaS)

1. Push your project to a **private** GitHub repo (keep API keys in environment variables, NOT in code)
2. Connect to Railway or Render
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `python main.py paper --interval 60`
5. Add all `.env` variables in the platform's environment settings
6. For the dashboard, deploy a second service with: `streamlit run dashboard/app.py --server.port $PORT`

---

### Option C: Docker

Create a `Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py", "paper", "--interval", "60"]
```

Build & run:

```bash
docker build -t ict-bot .
docker run -d --env-file .env --name ict-bot ict-bot
```

---

## Security Checklist

- [ ] **Never commit `.env`** — it contains API keys. Add it to `.gitignore`
- [ ] **Use sandbox mode first** (`EXCHANGE_SANDBOX=true`) until strategy is proven
- [ ] **Set conservative risk**: 1% per trade, 3% max daily loss
- [ ] **Monitor logs**: check `logs/bot.log` regularly
- [ ] **Start with paper trading** before ever going live
- [ ] **Use IP whitelisting** on your exchange API key
- [ ] **Disable withdrawal permission** on API keys — only enable trading

## Architecture Overview

```
main.py                  ← CLI entry point
config/settings.py       ← .env loader
data/fetcher.py          ← OHLC candle fetcher (ccxt)
strategy/
  market_structure.py    ← Swing detection, BOS, CHoCH, bias
  pd_arrays.py           ← FVG, OB, Breakers, Liquidity, OTE
  ict_signals.py         ← Signal generator (combines all above)
ml/model.py              ← XGBoost signal confirmation
engine/
  risk_manager.py        ← Position sizing, daily limits, trailing stops
  backtester.py          ← Historical backtesting
  live_trader.py         ← Paper & live trading loop
dashboard/app.py         ← Streamlit UI
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError` | Activate venv: `.\venv\Scripts\Activate.ps1` |
| No signals generated | Try more candles, lower confidence, check symbol availability |
| Exchange error | Verify API keys in `.env`, check sandbox mode |
| Dashboard won't load | Run `pip install streamlit plotly` again |
| ML model returns 0.5 | Train it first: `python main.py train` |
