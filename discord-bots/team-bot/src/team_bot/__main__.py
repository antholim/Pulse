"""Entry point: ``python -m team_bot`` (or the ``team-bot`` script)."""

from __future__ import annotations

import logging
import sys

import discord
from dotenv import load_dotenv

from team_bot.bot import TeamBot
from team_bot.config import ConfigError, Settings
from team_bot.services.github import GitHubService, build_client
from team_bot.services.storage import Storage


def main() -> None:
    load_dotenv()
    discord.utils.setup_logging(level=logging.INFO)
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        logging.getLogger("team_bot").error("%s. See .env.example.", exc)
        sys.exit(1)

    storage = Storage(settings.db_path)
    github = GitHubService(
        build_client(settings.github_auth), settings.repo_owner, settings.repo_name
    )
    bot = TeamBot(settings, storage, github)
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
