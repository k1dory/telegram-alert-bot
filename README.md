# Telegram Alert Bot

Infrastructure monitoring bot for Telegram with ASCII dashboard, alerts, and auto-refresh.

## Features

- ASCII art dashboard with server metrics
- Real-time monitoring of servers and containers
- Alert notifications with cooldowns and grouping
- Auto-refresh every 30 seconds
- Interactive inline buttons
- User whitelist support
- 2FA confirmation for critical actions

## Installation

1. Clone the repository:
```bash
git clone https://github.com/k1dory/telegram-alert-bot.git
cd telegram-alert-bot
```

2. Create virtual environment and install dependencies:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

3. Configure the bot:
```bash
cp .env.example .env
# Edit .env and set your TELEGRAM_BOT_TOKEN
```

4. Run the bot:
```bash
python bot.py
```

## Configuration

Create `.env` file with the following variables:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
ALLOWED_USER_IDS=123456789,987654321
DASHBOARD_REFRESH_INTERVAL=30
DISCOVERY_MODE=auto
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| TELEGRAM_BOT_TOKEN | Bot API token from @BotFather | Required |
| ALLOWED_USER_IDS | Comma-separated user IDs (empty = allow all) | Empty |
| DASHBOARD_REFRESH_INTERVAL | Dashboard refresh interval in seconds | 30 |
| DISCOVERY_MODE | Container discovery mode (auto/manual) | auto |
| GATEWAY_URL | Gateway API URL | http://localhost:8080 |
| ALERT_MIN_LEVEL | Minimum alert level (info/warning/critical) | warning |

## Commands

| Command | Description |
|---------|-------------|
| /start | Welcome screen and main menu |
| /status | Live dashboard with auto-refresh |
| /servers | List all monitored servers |
| /alerts | View active alerts |
| /config | Bot settings |
| /help | Help information |

## Systemd Service (Linux)

Create `/etc/systemd/system/infra-bot.service`:

```ini
[Unit]
Description=Infra AI Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/telegram-alert-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
systemctl daemon-reload
systemctl enable infra-bot
systemctl start infra-bot
```

## Project Structure

```
telegram-alert-bot/
    bot.py          # Main bot module
    config.py       # Configuration (pydantic settings)
    dashboard.py    # ASCII dashboard renderer
    alerts.py       # Alert management
    discovery.py    # Container auto-discovery
    gateway_client.py # Gateway API client
    requirements.txt
    .env.example
```

## License

MIT
