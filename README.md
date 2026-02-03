# Archive Bot

A Discord bot that monitors messages for URLs from configured sites and automatically creates archived versions using archive.today.

## Features

- **Automatic URL Detection**: Monitors messages for links to configured sites
- **Automatic Archiving**: Creates archive.today archives with browser rendering
- **CAPTCHA Solving**: Uses SolveCaptcha service to handle archive.today CAPTCHAs
- **Site Management**: Add/remove watched sites via Discord commands
- **SQLite Database**: Persistent storage for watched sites list (per-server)

## Setup

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" section and click "Add Bot"
4. Enable the following Privileged Gateway Intents:
   - **Message Content Intent** (required to read message content)
5. Copy the bot token

### 2. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your bot token:

```
DISCORD_TOKEN=your_bot_token_here
```

### 4. Invite the Bot to Your Server

1. Go to OAuth2 > URL Generator in the Developer Portal
2. Select scopes: `bot`, `applications.commands`
3. Select bot permissions:
   - Read Messages/View Channels
   - Send Messages
   - Embed Links
   - Read Message History
4. Use the generated URL to invite the bot

### 5. Run the Bot

**Option A: Run directly with Python**

```bash
python bot.py
```

**Option B: Run with Docker Compose**

First, edit `docker-compose.yml` and set your `DISCORD_TOKEN`:

```yaml
environment:
  - DISCORD_TOKEN=your_actual_token_here
```

Then run:

```bash
docker compose up -d
```

To view logs:

```bash
docker compose logs -f
```

To stop:

```bash
docker compose down
```

## Commands

All commands support both prefix (`!`) and slash (`/`) command formats.

### Site Management

| Command | Description | Permission Required |
|---------|-------------|---------------------|
| `!addsite <domain>` | Add a domain to the watch list | Manage Messages |
| `!removesite <domain>` | Remove a domain from the watch list | Manage Messages |
| `!listsites` | List all monitored sites | None |

### Archive Commands

| Command | Description |
|---------|-------------|
| `!archive <url>` | Get archive.today links for any URL |
| `!render <url>` | Create an archived version of a URL |

## Usage Examples

### Adding Sites to Watch

```
!addsite nytimes.com
!addsite wsj.com
!addsite washingtonpost.com
```

### How It Works

1. A user posts a message containing a URL like `https://www.nytimes.com/2024/article-title`
2. The bot detects the URL matches a configured watched site
3. The bot uses browser rendering to create an archive on archive.today
4. CAPTCHAs are automatically solved using the SolveCaptcha service
5. If successful, it replies with the archived link
6. If archiving fails, it provides manual archive.today links

## File Structure

```
archive_bot/
├── bot.py                      # Main bot file
├── database.py                 # SQLite database operations
├── archive_service.py          # Wayback Machine and archive.today integration
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker container definition
├── docker-compose.yml          # Docker Compose config (set token here)
├── docker-compose.example.yml  # Example Docker Compose config
├── rebuild.sh                  # Script to rebuild Docker container
├── .env.example                # Example environment file (for non-Docker use)
└── data/                       # Persistent data directory
    └── archive_bot.db          # SQLite database (auto-created)
```

## Common Sites to Watch

Here are some common sites you might want to add:

- `nytimes.com`
- `wsj.com`
- `washingtonpost.com`
- `ft.com`
- `economist.com`
- `bloomberg.com`
- `theatlantic.com`
- `newyorker.com`
- `wired.com`
- `medium.com`

## Troubleshooting

### Bot doesn't respond to messages
- Ensure "Message Content Intent" is enabled in the Developer Portal
- Check that the bot has permission to read and send messages in the channel

### Archive checks are slow
- The Wayback Machine can be slow to respond; this is normal
- The bot shows a typing indicator while checking

### "DISCORD_TOKEN not set" error
- **Docker**: Make sure you've set the token in `docker-compose.yml`
- **Python**: Make sure you've created the `.env` file with your token
- Check the token is correct and the bot is not disabled

## License

MIT
