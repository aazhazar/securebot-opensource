# SecureBot Open Source

An advanced Discord security and anti-nuke bot equipped with features like mass ban protection, anti-bot, automod, and a dashboard API.

## Features

- **Anti-Nuke Protection:** Prevent mass bans, mass kicks, mass channel deletions, and role deletions.
- **Server Security:** Anti-bot, anti-webhook creation, and strict permission monitoring.
- **Automod & Anti-Spam:** Block bad words, invitiation links, and spamming automatically.

## Getting Started

### Prerequisites

- Python 3.8 or higher
- The following Python packages:
  - `discord.py`
  - `aiohttp`
  - `python-dotenv`

### Installation

1. Download or clone this repository.
2. Install the required dependencies:
   ```bash
   pip install discord.py aiohttp python-dotenv
   ```
3. Set up your `.env` file (see instructions below).
4. Start the bot:
   ```bash
   python main.py
   ```

---

## How to Change the Token

The bot uses a `.env` file to securely store its configuration. To add your token:

1. Open the `.env` file located in the project folder.
2. It should look like this:
   ```env
   TOKEN="YOUR_TOKEN_ID_HERE"
   ```
3. Replace `YOUR_TOKEN_ID_HERE` with your actual Discord Bot Token. You can find this on the [Discord Developer Portal](https://discord.com/developers/applications) under the **Bot** tab.

5. Save the `.env` file. **Never share this token with anyone!**

---

## How to Host on Orihost for Free

You can host this bot 24/7 for free using [Orihost](https://orihost.com/). Here is a step-by-step guide:

[![Orihost Hosting Tutorial](https://img.youtube.com/vi/m6bY9PMYaHg/0.jpg)](https://www.youtube.com/watch?v=m6bY9PMYaHg)

1. **Create an Account:** Go to [orihost.com](https://orihost.com/) and register for a free account.
2. **Create a Server:** Once logged into the dashboard/panel, click on **Create Server** (or similar).
3. **Select Environment:** Choose the free tier and select **Python** as your server type/egg.
4. **Upload Files:** Navigate to the **File Manager** on your new server. Upload all the files from this folder (especially `main.py`, `.env`, `security_config.json`, and `badword.json`).
5. **Configure Startup:** Go to the **Startup** or **Settings** tab. Ensure the startup command is set to run the bot:
   ```bash
   python main.py
   ```
   *(Note: Orihost may automatically install requirements if you provide a `requirements.txt` file. If so, create one with `discord.py`, `aiohttp`, and `python-dotenv` inside).*
6. **Start the Bot:** Go back to the **Console** tab and click **Start**. The console will show the bot coming online!

### Important Note on Intents
To ensure the bot works perfectly, go to the Discord Developer Portal, select your application, click on the **Bot** tab, and toggle **ON** all Privileged Gateway Intents (Presence Intent, Server Members Intent, and Message Content Intent).

---

## Author & Support

- **Developed by:** [aazdev.xyz](https://aazdev.xyz/)
- **Support me:** If you like this project and want to support me, consider buying a membership at [aazgroup.co/memberships](https://aazgroup.co/memberships)!

#   s e c u r e b o t - o p e n s o u r c e  