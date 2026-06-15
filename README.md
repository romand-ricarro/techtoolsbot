# techtoolsbot

A Discord bot for onboarding team members to internal tech tools — delivering intro messages, running quizzes, tracking completions, and logging results to Google Sheets.

## What it does

- Sends configurable intro messages to new team members via DM or channel
- Runs interactive quizzes (questions loaded from `questions.json`) with session tracking
- Logs quiz results and badge completions to a Google Sheet
- Prevents re-runs via per-user cooldowns and active session tracking
- Supports slash commands via `app_commands`
- Maps Discord user IDs to internal usernames via `mappings.json`

## Project structure

```
techtoolsbot.py         # Main bot — slash commands, quiz flow, Google Sheets logging
intro_messages.json     # Configurable intro message content
messages.json           # General bot messages
questions.json          # Quiz questions and answers
mappings.json           # Discord ID → internal username mappings
toolsbotconfig.py       # Bot configuration
test_sheets.py          # Test script for Google Sheets connectivity
credentials/            # Google service account credentials (not committed)
requirements.txt
```

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```
DISCORD_TOKEN=your_discord_bot_token
CHANNEL_ID=your_channel_id
GUILD_ID=your_guild_id
SPREADSHEET_ID=your_google_sheet_id
WORKSHEET_NAME=Sheet1
SERVICE_ACCOUNT_FILE=credentials/credentials.json
```

## Usage

```bash
python techtoolsbot.py
```
