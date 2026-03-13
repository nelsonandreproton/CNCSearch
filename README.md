# CNCSearch

Pesquisa semântica de cânticos litúrgicos via Telegram bot + Web UI.

Envias um texto bíblico e recebes uma lista de cânticos ordenados por percentagem de
correspondência contextual, usando embeddings (Jina AI ou sentence-transformers local).

---

## Funcionalidades

- **Bot Telegram** — comando `/canticos` integrado num bot existente (GarminBot)
- **Web UI** (Bootstrap 5, autenticação por sessão)
  - CRUD de cânticos: título, letra, URL da pauta, momento litúrgico
  - Gestão de momentos litúrgicos
  - Importação em massa via CSV
  - Pesquisa de teste com filtro por momento
  - Configurações: número de resultados, similaridade mínima, password
  - Re-indexação de embeddings
- **HTTPS automático** via Caddy + sslip.io (sem domínio próprio)

---

## Requisitos

- Docker + Docker Compose v2
- Conta gratuita em [jina.ai](https://jina.ai) — 1M tokens/mês grátis
- GarminBot em `../GarminBot/` (mesmo servidor)

---

## Instalação

### 1. Clonar e configurar

```bash
git clone <repo-url> /opt/cncsearch
cd /opt/cncsearch
cp .env.example .env
```

### 2. Editar `.env`

```env
# ── Obrigatórios ──────────────────────────────────────────────────────────────
JINA_API_KEY=jina_xxxxxxxxxxxx          # conta em jina.ai
WEB_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
WEB_INITIAL_PASSWORD=muda-esta-password

# ── HTTPS ─────────────────────────────────────────────────────────────────────
# IP do servidor com traços: 5.10.20.30 → 5-10-20-30.sslip.io
CADDY_HOST=5-10-20-30.sslip.io
```

> **`WEB_SECRET_KEY` é obrigatório.** A aplicação recusa arrancar se não estiver definido.
> Gera uma chave aleatória:
> ```bash
> python3 -c "import secrets; print(secrets.token_hex(32))"
> ```

### 3. Integração com GarminBot

O `docker-compose.yml` do CNCSearch gere os 3 serviços: `cncsearch`, `caddy` e `garminbot`.
Antes de iniciar, para o GarminBot existente:

```bash
cd /opt/garminbot && docker compose down
cd /opt/cncsearch
```

Edita `../GarminBot/src/main.py` — adiciona estas linhas **depois** de `app = tg_bot.build_application()`:

```python
import os
_cncsearch_db = os.environ.get("CNCSEARCH_DATABASE_PATH")
if _cncsearch_db:
    try:
        from cncsearch.telegram.handler import register_canticos_handler
        register_canticos_handler(
            app,
            db_path=_cncsearch_db,
            embedding_provider=os.environ.get("CNCSEARCH_EMBEDDING_PROVIDER", "jina"),
            jina_api_key=os.environ.get("CNCSEARCH_JINA_API_KEY"),
        )
    except ImportError:
        logger.warning("CNCSearch não disponível — /canticos desactivado (PYTHONPATH configurado?)")
```

### 4. Iniciar

```bash
bash deploy.sh
```

Ou manualmente:

```bash
docker compose up -d --build
docker compose logs -f
```

---

## Deploy e actualizações

```bash
bash deploy.sh
```

O script faz `git pull`, reconstrói as imagens e reinicia os serviços.

---

## Acesso

Após o primeiro arranque, o Caddy emite automaticamente um certificado Let's Encrypt.

- **Web UI:** `https://<CADDY_HOST>` (ex: `https://5-10-20-30.sslip.io`)
- **Utilizador:** `admin` (ou o valor de `web_username` nas Definições)
- **Password:** valor de `WEB_INITIAL_PASSWORD` (muda nas Definições após o primeiro login)

---

## Comando no Telegram

```
/canticos [N] [-m momento] texto bíblico
```

| Exemplo | Resultado |
|---|---|
| `/canticos João 3:16` | Top N (configurado nas Definições) de todos os momentos |
| `/canticos 5 João 3:16` | Top 5 |
| `/canticos -m Comunhão João 3:16` | Filtrado por momento "Comunhão" |
| `/canticos 5 -m Entrada João 3:16` | Top 5 filtrado por momento "Entrada" |

- O **N** e o **momento** são ambos opcionais e independentes.
- Se o momento não existir, o bot informa.
- `N` e `min_similarity` por defeito são configuráveis na página Definições.

---

## Formato CSV para importação

```csv
title,lyrics,sheet_url,moment
"Tanto Amor","Verso 1\nVerso 2\nRefrão","https://app.resucito.es/cantico/123","Comunhão"
"Salmo 22","O Senhor é o meu pastor...",,"Salmo"
"Outro Cântico","Letra aqui","",""
```

| Campo | Obrigatório | Notas |
|---|---|---|
| `title` | Sim | Título do cântico |
| `lyrics` | Sim | Letra; `\n` é convertido em quebra de linha |
| `sheet_url` | Não | URL da pauta (ex: app.resucito.es) |
| `moment` | Não | Nome do momento litúrgico; criado automaticamente se não existir |

- Codificação: UTF-8 (com ou sem BOM)
- Ficheiro máximo: 5 MB

---

## Variáveis de ambiente

### CNCSearch (`.env`)

| Variável | Descrição | Padrão |
|---|---|---|
| `DATABASE_PATH` | Caminho para o ficheiro SQLite | `/data/cncsearch.db` |
| `EMBEDDING_PROVIDER` | `jina` ou `local` | `jina` |
| `JINA_API_KEY` | Chave API Jina (obrigatória se `jina`) | — |
| `WEB_SECRET_KEY` | **Obrigatório.** Segredo para assinar cookies de sessão | — |
| `WEB_INITIAL_PASSWORD` | Password no primeiro arranque | `admin` |
| `CADDY_HOST` | Hostname HTTPS (ex: `5-10-20-30.sslip.io`) | — |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |

### Injectadas no GarminBot (via docker-compose)

| Variável | Descrição |
|---|---|
| `CNCSEARCH_DATABASE_PATH` | Partilha o mesmo SQLite |
| `CNCSEARCH_EMBEDDING_PROVIDER` | Herda `EMBEDDING_PROVIDER` do `.env` |
| `CNCSEARCH_JINA_API_KEY` | Herda `JINA_API_KEY` do `.env` |

---

## Embeddings locais (sem Jina AI)

Para usar um modelo local em vez da API Jina:

1. Descomenta `sentence-transformers>=3.0.0` em `requirements.txt`
2. Define `EMBEDDING_PROVIDER=local` no `.env`
3. Na primeira pesquisa, o modelo `paraphrase-multilingual-mpnet-base-v2` (~420 MB) é descarregado automaticamente

A VM Hetzner CX23 (4 vCPU, 8 GB RAM) suporta sem problemas.

---

## Arquitectura

```
┌─────────────────────────────────────────────┐
│  docker-compose.yml (CNCSearch)             │
│                                             │
│  ┌──────────┐   ┌──────────┐   ┌─────────┐ │
│  │  caddy   │──▶│cncsearch │   │garminbot│ │
│  │  :80/443 │   │  :8080   │   │ polling │ │
│  └──────────┘   └────┬─────┘   └────┬────┘ │
│                       │              │      │
│              cncsearch_data (volume)─┘      │
└─────────────────────────────────────────────┘
```

- **Caddy** emite HTTPS via Let's Encrypt e faz proxy para `cncsearch:8080`
- **cncsearch** expõe a Web UI (FastAPI + Jinja2 + Bootstrap 5)
- **garminbot** monta o código-fonte do CNCSearch via PYTHONPATH e partilha o SQLite
- Os embeddings são gerados na criação/edição de cânticos; "Re-indexar" regenera todos

---

## Segurança

- Sessões assinadas com `itsdangerous` (HMAC-SHA1)
- Passwords em bcrypt
- `verify_password` sempre executa bcrypt (sem timing attack)
- Rate limiting no login: 5 tentativas / 5 minutos por IP
- Cookie de sessão: `httponly`, `samesite=strict`
- Headers: `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`
- `WEB_SECRET_KEY` é obrigatório — a app não arranca sem ele

---

## Logs

```bash
docker compose logs -f cncsearch    # Web UI
docker compose logs -f garminbot    # Bot Telegram (inclui /canticos)
docker compose logs -f caddy        # HTTPS proxy
```
