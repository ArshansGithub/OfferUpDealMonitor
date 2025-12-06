# OfferUp Monitor

A Discord bot that monitors OfferUp searches and notifies you of new listings in real-time.

## Features
- Create monitoring tasks with custom queries, zip codes, and radius.
- Receive instant notifications in Discord when new items match your criteria.
- Manage tasks (enable/disable/delete) via Discord commands.
- Pagination support for viewing multiple tasks.
- MongoDB integration for persistent task storage.

## Prerequisites
- Python 3.11+
- [Poetry](https://python-poetry.org/) for dependency management
- A MongoDB database (local or Atlas)
- A Discord Bot Token

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd offerupmonitor
   ```

2. **Install dependencies:**
   ```bash
   poetry install
   ```

## Configuration

1. **Set up environment variables:**
   Copy the example environment file to `.env`:
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env`:**
   Open `.env` and fill in your secrets:
   ```env
   MONGO_URI=mongodb+srv://your_user:your_password@cluster.mongodb.net/offerup_bot?retryWrites=true&w=majority
   DISCORD_TOKEN=your_discord_bot_token
   OPENAI_API_KEY=your_openai_api_key
   PROXY_URL=http://your_proxy_url
   LOG_CHANNEL_ID=your_channel_id
   ```

## Usage

1. **Run the bot:**
   ```bash
   poetry run python -m offerupmonitor
   ```

2. **Discord Commands:**
   - `/monitor newtask` - Start the setup wizard for a new monitoring task.
   - `/monitor tasks` - View your currently active tasks.
   - `/monitor delete_task <task_id>` - Delete a specific task.
   - `/monitor update_task <task_id> <enable/disable>` - Enable or disable a task.
   - `/monitor refresh_task <task_id>` - Manually trigger a check for a specific task.

## License
MIT
