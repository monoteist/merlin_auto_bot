# Merlin Auction Bot

Telegram bot for automatic parsing of cars from Merlin auction and sending information to a Telegram chat with prices from DoneDeal.

## Requirements

- Python 3.11 or higher
- Telegram Bot Token
- Telegram Chat ID

## Installation

1. Clone the repository or navigate to the project directory:
```bash
cd merlin_auction
```

2. Create a virtual environment (recommended):
```bash
python -m venv venv
```

3. Activate the virtual environment:

**Windows:**
```bash
venv\Scripts\activate
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

4. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

1. Open `bot.py` and configure the following parameters:

```python
API_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"  # Your Telegram bot token
auction_chat_id = YOUR_CHAT_ID        # Chat ID for sending messages
```

2. Get a Telegram Bot Token:
   - Find [@BotFather](https://t.me/BotFather) on Telegram
   - Send the `/newbot` command and follow the instructions
   - Copy the received token

3. Get Chat ID:
   - Find [@userinfobot](https://t.me/userinfobot) on Telegram
   - Send the `/start` command
   - Copy your Chat ID

## Running

Start the bot:

```bash
python bot.py
```

After starting, the bot will wait for the `/run` command in Telegram. Send this command to the bot to start parsing the auction.

## Usage

1. Start the bot (see "Running" section)
2. In Telegram, send the `/run` command to the bot
3. The bot will start parsing the auction and send car information to the specified chat

## Features

- **Asynchronous parsing**: Fast data collection from all auction pages
- **Detailed information**: Automatic retrieval of additional data from car pages
- **DoneDeal prices**: Automatic search for average price on DoneDeal with fallback logic
- **Instant delivery**: Information about each car is sent to Telegram immediately after receiving the price

## Project structure

```
merlin_auction/
├── bot.py              # Main bot file
├── merlin.py           # Parsing and data processing logic
├── requirements.txt    # Project dependencies
└── README.md          # Documentation
```

## Dependencies

- `pyTelegramBotAPI` - for Telegram Bot API
- `beautifulsoup4` - for HTML parsing
- `requests` - for synchronous HTTP requests
- `aiohttp` - for asynchronous HTTP requests

## Notes

- The bot uses random User-Agents to simulate mobile devices
- Delays between requests are added to avoid blocking
- Fallback search strategies are used when DoneDeal price is unavailable

## Troubleshooting

If you encounter issues, check:
- Bot token and Chat ID are correct
- Internet connection is available
- Python version is 3.11 or higher
- All dependencies from requirements.txt are installed
