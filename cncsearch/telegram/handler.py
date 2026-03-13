"""Telegram /canticos command handler.

Usage in GarminBot's main.py (after app = tg_bot.build_application()):

    import os
    from cncsearch.telegram.handler import register_canticos_handler
    register_canticos_handler(
        app,
        db_path=os.environ.get("CNCSEARCH_DATABASE_PATH", "./cncsearch_data/cncsearch.db"),
        embedding_provider=os.environ.get("CNCSEARCH_EMBEDDING_PROVIDER", "jina"),
        jina_api_key=os.environ.get("CNCSEARCH_JINA_API_KEY"),
    )

Command syntax:
    /canticos texto bíblico
    /canticos 5 texto bíblico
    /canticos -m comunhão texto bíblico
    /canticos 5 -m comunhão texto bíblico
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)


def _parse_args(args: list[str]) -> tuple[int | None, str | None, str]:
    """
    Parse: [N] [-m moment] text...
    Returns (n, moment_name, query_text).
    """
    n: int | None = None
    moment_name: str | None = None
    text_parts: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token == "-m" and i + 1 < len(args):
            moment_name = args[i + 1]
            i += 2
        elif n is None and token.isdigit():
            n = int(token)
            i += 1
        else:
            text_parts.append(token)
            i += 1
    return n, moment_name, " ".join(text_parts)


def _make_handler(
    db_path: str,
    embedding_provider: str,
    jina_api_key: str | None,
) -> Callable:
    """Factory: creates the /canticos handler closed over its dependencies."""
    from ..config import Config
    from ..database.repository import Repository
    from ..search.service import SearchService

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    config = Config(
        database_path=db_path,
        embedding_provider=embedding_provider,
        jina_api_key=jina_api_key,
        web_secret_key="",
        web_initial_password="",
        log_level="INFO",
    )
    repo = Repository(db_path)
    repo.init_database()
    search = SearchService(config, repo)

    async def canticos_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        args = context.args or []
        n, moment_name, query_text = _parse_args(args)

        if not query_text:
            await update.message.reply_text(
                "Uso: /canticos [N] [-m momento] texto bíblico\n"
                "Exemplo: /canticos 3 -m Comunhão João 3:16"
            )
            return

        # Resolve settings
        top_n = n if n is not None else int(repo.get_setting("top_n", "3"))
        min_sim = float(repo.get_setting("min_similarity", "0.40"))

        # Resolve moment
        moment_id: int | None = None
        if moment_name:
            moment = repo.get_moment_by_name(moment_name)
            if not moment:
                await update.message.reply_text(
                    f"⚠️ Momento <b>{moment_name}</b> não encontrado.\n"
                    "Consulta a lista em /momentos ou deixa sem o parâmetro -m.",
                    parse_mode="HTML",
                )
                return
            moment_id = moment.id

        # Run search in thread (may call Jina API or local model)
        try:
            results = await asyncio.to_thread(
                search.search, query_text, top_n, min_sim, moment_id
            )
        except Exception as exc:
            logger.error("Search failed: %s", exc, exc_info=True)
            await update.message.reply_text("❌ Erro ao pesquisar. Tenta novamente mais tarde.")
            return

        if not results:
            filter_note = f" com momento <b>{moment_name}</b>" if moment_name else ""
            await update.message.reply_text(
                f"⚠️ Nenhum cântico{filter_note} com correspondência suficiente "
                f"(mínimo {min_sim:.0%}) para:\n<i>{query_text}</i>",
                parse_mode="HTML",
            )
            return

        # Build response
        lines = [f"🎵 <b>Cânticos para:</b> <i>{query_text}</i>\n"]
        for i, r in enumerate(results, 1):
            moment_label = ""
            if r["moment_id"]:
                m = repo.get_moment(r["moment_id"])
                if m:
                    moment_label = f" <i>[{m.name}]</i>"

            lines.append(
                f"{i}. <b>{r['title']}</b> ({r['similarity']:.0%}){moment_label}"
            )
            if r["sheet_url"]:
                lines.append(f"   🎼 {r['sheet_url']}")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    return canticos_command


def register_canticos_handler(
    app: Application,
    db_path: str,
    embedding_provider: str = "jina",
    jina_api_key: str | None = None,
) -> None:
    """Register the /canticos command on an existing Application instance."""
    handler_fn = _make_handler(db_path, embedding_provider, jina_api_key)
    app.add_handler(CommandHandler("canticos", handler_fn))
    logger.info("CNCSearch /canticos handler registered (db=%s)", db_path)
