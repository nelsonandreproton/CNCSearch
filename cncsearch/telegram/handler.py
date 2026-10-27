"""Telegram /canticos and /canticos_paroquia command handlers.

Usage in GarminBot's main.py (after app = tg_bot.build_application()):

    import os
    from cncsearch.telegram.handler import register_canticos_handler
    register_canticos_handler(
        app,
        db_path=os.environ.get("CNCSEARCH_DATABASE_PATH", "./cncsearch_data/cncsearch.db"),
        embedding_provider=os.environ.get("CNCSEARCH_EMBEDDING_PROVIDER", "jina"),
        jina_api_key=os.environ.get("CNCSEARCH_JINA_API_KEY"),
    )

Command syntax (both /canticos and /canticos_paroquia):
    /canticos texto bíblico
    /canticos 5 texto bíblico
    /canticos -m comunhão texto bíblico
    /canticos 5 -m comunhão texto bíblico

Literal word/phrase search (/letra and /letra_paroquia):
    /letra palavra outra            -> canticos containing all the words
    /letra "frase exacta"           -> canticos containing the exact phrase
    /letra 15 -m "Ação de Graças" amor "pão da vida"
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
from typing import Callable

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)

_TEXT_DEFAULT_N = 10
_TEXT_MAX_N = 30
_TELEGRAM_MAX_CHARS = 3900  # hard limit is 4096; keep margin for the footer


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


def _parse_text_args(raw: str) -> tuple[int | None, str | None, list[str]]:
    """
    Parse: [N] [-m moment] words and/or "quoted phrases".
    Returns (n, moment_name, terms); each quoted phrase is a single term.
    """
    from ..search.text import tokenize

    tokens = tokenize(raw)
    n: int | None = None
    moment_name: str | None = None
    terms: list[str] = []
    i = 0
    while i < len(tokens):
        token, quoted = tokens[i]
        if not quoted and token == "-m" and i + 1 < len(tokens):
            moment_name = tokens[i + 1][0]
            i += 2
        elif not quoted and n is None and not terms and token.isdigit():
            n = int(token)
            i += 1
        else:
            terms.append(token)
            i += 1
    return n, moment_name, terms


def _make_handler(
    db_path: str,
    embedding_provider: str,
    jina_api_key: str | None,
    source: str,
) -> Callable:
    """Factory: creates a search handler scoped to a given source."""
    from ..config import Config
    from ..database.repository import Repository
    from ..search.service import SearchService

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

    source_label = "Paróquia" if source == "paroquia" else "Caminho"
    command_name = "canticos_paroquia" if source == "paroquia" else "canticos"

    async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        args = context.args or []
        n, moment_name, query_text = _parse_args(args)

        if not query_text:
            await update.message.reply_text(
                f"Uso: /{command_name} [N] [-m momento] texto bíblico\n"
                f"Exemplo: /{command_name} 3 João 3:16"
            )
            return

        top_n = n if n is not None else int(repo.get_setting("top_n", "3"))
        min_sim = float(repo.get_setting("min_similarity", "0.40"))

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

        # Expand biblical references once (reused for display and embedding)
        from ..bible.lookup import expand_query
        expanded = await asyncio.to_thread(expand_query, query_text)
        verse_text = expanded[len(query_text):].strip() if expanded != query_text else None

        try:
            results = await asyncio.to_thread(
                search.search, query_text, top_n, min_sim, moment_id,
                expanded,   # pre-expanded to avoid double API call
                source,
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

        moment_cache: dict[int, str] = {}
        lines = [f"🎵 <b>Cânticos {source_label} para:</b> <i>{query_text}</i>"]
        if verse_text:
            lines.append(f"<blockquote>{verse_text}</blockquote>")
        lines.append("")
        for i, r in enumerate(results, 1):
            moment_names = []
            for mid in r.get("moment_ids", []):
                if mid not in moment_cache:
                    m = repo.get_moment(mid)
                    moment_cache[mid] = m.name if m else ""
                if moment_cache[mid]:
                    moment_names.append(moment_cache[mid])
            moment_label = f" <i>[{', '.join(moment_names)}]</i>" if moment_names else ""

            lines.append(
                f"{i}. <b>{r['title']}</b> ({r['similarity']:.0%}){moment_label}"
            )
            if r["sheet_url"]:
                lines.append(f"   🎼 {r['sheet_url']}")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    return _handler


def _make_text_handler(db_path: str, source: str) -> Callable:
    """Factory: creates a literal word/phrase search handler scoped to a given source."""
    from ..database.repository import Repository
    from ..search.text import text_search

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    repo = Repository(db_path)
    repo.init_database()

    source_label = "Paróquia" if source == "paroquia" else "Caminho"
    command_name = "letra_paroquia" if source == "paroquia" else "letra"

    async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        n, moment_name, terms = _parse_text_args(" ".join(context.args or []))
        if not terms:
            await update.message.reply_text(
                f"Uso: /{command_name} [N] [-m momento] palavras ou \"frase exacta\"\n"
                f"Exemplos:\n"
                f"/{command_name} misericórdia\n"
                f"/{command_name} \"pão da vida\"\n"
                f"/{command_name} 20 -m Comunhão amor \"pão da vida\""
            )
            return

        limit = min(n if n is not None else _TEXT_DEFAULT_N, _TEXT_MAX_N)

        moment_id: int | None = None
        if moment_name:
            moment = repo.get_moment_by_name(moment_name)
            if not moment:
                await update.message.reply_text(
                    f"⚠️ Momento <b>{html.escape(moment_name)}</b> não encontrado.\n"
                    "Consulta a lista em /momentos ou deixa sem o parâmetro -m.",
                    parse_mode="HTML",
                )
                return
            moment_id = moment.id

        try:
            canticos = await asyncio.to_thread(repo.get_canticos, source)
            if moment_id is not None:
                canticos = [c for c in canticos if any(m.id == moment_id for m in c.moments)]
            matches, total = text_search(canticos, terms, limit)
        except Exception as exc:
            logger.error("Text search failed: %s", exc, exc_info=True)
            await update.message.reply_text("❌ Erro ao pesquisar. Tenta novamente mais tarde.")
            return

        query_label = html.escape(" ".join(f"\"{t}\"" if " " in t else t for t in terms))
        if not matches:
            filter_note = f" com momento <b>{html.escape(moment_name)}</b>" if moment_name else ""
            await update.message.reply_text(
                f"⚠️ Nenhum cântico {source_label}{filter_note} contém: <i>{query_label}</i>",
                parse_mode="HTML",
            )
            return

        header = f"🔎 <b>Cânticos {source_label} com:</b> <i>{query_label}</i>"
        if total > len(matches):
            header += f"\n<i>{len(matches)} de {total} resultados</i>"
        lines = [header, ""]
        length = len(header)
        shown = 0
        for i, m in enumerate(matches, 1):
            c = m.cantico
            moment_names = [mo.name for mo in c.moments]
            moment_label = f" <i>[{html.escape(', '.join(moment_names))}]</i>" if moment_names else ""
            block = [f"{i}. <b>{html.escape(c.title)}</b>{moment_label}"]
            if m.snippet:
                snippet = "".join(
                    f"<b>{html.escape(t)}</b>" if hit else html.escape(t) for t, hit in m.snippet
                )
                block.append(f"   <i>{snippet}</i>")
            if c.sheet_url:
                block.append(f"   🎼 {html.escape(c.sheet_url)}")
            block_len = sum(len(b) + 1 for b in block)
            if length + block_len > _TELEGRAM_MAX_CHARS:
                break
            lines.extend(block)
            length += block_len
            shown += 1

        if shown < total:
            lines.append("")
            lines.append(f"<i>… mais {total - shown}. Refina a pesquisa ou usa /{command_name} N …</i>")

        await update.message.reply_text(
            "\n".join(lines), parse_mode="HTML", disable_web_page_preview=True
        )

    return _handler


def register_canticos_handler(
    app: Application,
    db_path: str,
    embedding_provider: str = "jina",
    jina_api_key: str | None = None,
) -> None:
    """Register /canticos, /canticos_paroquia (semantic) and /letra, /letra_paroquia
    (literal word/phrase) on an existing Application."""
    caminho_fn = _make_handler(db_path, embedding_provider, jina_api_key, source="caminho")
    paroquia_fn = _make_handler(db_path, embedding_provider, jina_api_key, source="paroquia")

    app.add_handler(CommandHandler("canticos", caminho_fn))
    app.add_handler(CommandHandler("canticos_paroquia", paroquia_fn))
    app.add_handler(CommandHandler("letra", _make_text_handler(db_path, source="caminho")))
    app.add_handler(CommandHandler("letra_paroquia", _make_text_handler(db_path, source="paroquia")))
    logger.info(
        "CNCSearch /canticos, /canticos_paroquia, /letra, /letra_paroquia handlers registered (db=%s)",
        db_path,
    )
