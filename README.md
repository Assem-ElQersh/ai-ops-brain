# AI Operations Brain (AOB)
### Customer Support Automation — End-to-End AI Pipeline

> A production-grade automation system that **observes, classifies, and resolves** incoming customer support tickets using LangChain agents, OpenAI, n8n orchestration, and real integrations — no human required for routine cases.

---

## Problem Statement

Home services companies receive hundreds of customer complaints daily. Manual triage is slow, inconsistent, and expensive. Critical issues (safety, legal threats, repeated failures) get lost in queues alongside minor feedback.

**AOB solves this** by autonomously processing every ticket: classifying urgency, drafting empathetic replies, sending automated emails, escalating critical cases to Slack, and logging every decision — all within seconds of submission.

---

## Architecture

```
                        ┌─────────────────────────────────────────────────────┐
                        │              AI Operations Brain                    │
                        │                                                     │
  Customer/Form ──POST──►  n8n Webhook  ──► Validate & Normalize             │
                        │       │                                             │
                        │       ▼                                             │
                        │  FastAPI Backend  (POST /tickets/webhook)           │
                        │       │                                             │
                        │       ▼                                             │
                        │  ┌─────────────────────────────────────────┐       │
                        │  │         LangChain ReAct Agent            │       │
                        │  │                                          │       │
                        │  │  1. query_customer_history  ──► PostgreSQL│      │
                        │  │  2. classify_ticket         ──► PostgreSQL│      │
                        │  │  3. draft_response          ──► PostgreSQL│      │
                        │  │  4. send_auto_reply         ──► SMTP/Email│      │
                        │  │  5. escalate_to_slack       ──► Slack API │      │
                        │  │     (if urgency: high/critical)           │      │
                        │  │  6. mark_resolved           ──► PostgreSQL│      │
                        │  └─────────────────────────────────────────┘       │
                        │                                                     │
                        │  Streamlit Dashboard  ◄──GET── FastAPI /tickets    │
                        │  (live monitoring, logs, manual submission)         │
                        └─────────────────────────────────────────────────────┘
```

### Layer Breakdown

| Layer | Component | Purpose |
|---|---|---|
| **Input** | n8n Webhook | Receives tickets from any source (form, CRM, API) |
| **Validation** | n8n Function Node | Validates and normalizes payload |
| **Orchestration** | FastAPI (Python) | Persists ticket, kicks off agent in background |
| **Intelligence** | LangChain ReAct Agent | Reasons over ticket, selects and executes tools |
| **LLM** | Mistral (mistral-small-latest) | Powers classification, response drafting, reasoning |
| **Memory** | PostgreSQL | Stores tickets, action logs, customer history |
| **Notifications** | aiosmtplib + httpx | Sends email replies + Slack escalation alerts |
| **Monitoring** | Streamlit | Live dashboard for ops team visibility |

---

## Tech Stack

| Tool | Role |
|---|---|
| **n8n** | Workflow orchestrator, webhook receiver |
| **FastAPI** | REST API backend |
| **LangChain** | ReAct agent framework + tool use |
| **Mistral AI** | Classification, reasoning, response drafting |
| **PostgreSQL** | Persistent storage (tickets, logs, history) |
| **SQLAlchemy** | ORM + migrations |
| **Streamlit** | Operations monitoring dashboard |
| **Docker Compose** | One-command deployment |

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/ai-ops-brain.git
cd ai-ops-brain

cp .env.example .env
# Edit .env — at minimum set MISTRAL_API_KEY (free at console.mistral.ai)
```

### 2. Run everything

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| FastAPI backend + docs | http://localhost:8000/docs |
| n8n workflow editor | http://localhost:5678 |
| Streamlit dashboard | http://localhost:8501 |

### 3. Import the n8n workflow

1. Open http://localhost:5678 (login: `admin` / `admin123`)
2. Go to **Workflows → Import from File**
3. Import `n8n/workflows/customer_support.json`
4. Activate the workflow

### 4. Submit a test ticket

```bash
curl -X POST http://localhost:8000/tickets/ \
  -H "Content-Type: application/json" \
  -d '{
    "customer_name": "Sarah Al-Hassan",
    "customer_email": "sarah@example.com",
    "subject": "Cleaning team never arrived — 3rd time",
    "message": "This is the third time nobody has shown up. I am demanding a refund and will contact consumer protection."
  }'
```

Or use the **Submit Ticket** tab in the Streamlit dashboard.

---

## How the Agent Works

The LangChain ReAct agent receives a ticket and autonomously executes this sequence:

```
1. query_customer_history  → checks if this is a repeat offender case
2. classify_ticket         → assigns urgency (low/medium/high/critical) + category
3. draft_response          → writes a professional, empathetic reply
4. send_auto_reply         → delivers reply via email
5. escalate_to_slack       → fires Slack alert (ONLY if high/critical)
6. mark_resolved           → closes the ticket with a resolution note
```

Every step writes to the database. No silent failures.

### Urgency Rules (built into system prompt)

| Urgency | Trigger |
|---|---|
| `critical` | Safety issues, service not delivered, legal threats |
| `high` | Payment disputes, worker misconduct, repeated complaints |
| `medium` | Quality issues, scheduling problems, first complaints |
| `low` | General feedback, feature requests, minor questions |

---

## API Reference

### POST `/tickets/`
Ingest a new ticket and start AI processing.

```json
{
  "customer_name": "string",
  "customer_email": "string",
  "subject": "string",
  "message": "string"
}
```

### GET `/tickets/`
List all tickets. Supports `?status=escalated&urgency=critical`.

### GET `/tickets/stats`
Aggregated counts by status + critical open count.

### GET `/tickets/{id}`
Full ticket detail with actions log.

### GET `/logs/actions`
All agent action logs (email sent, Slack alerts, classifications, etc.)

Full interactive docs at **http://localhost:8000/docs**.

---

## Project Structure

```
ai-ops-brain/
├── docker-compose.yml          # One-command orchestration
├── .env.example                # Configuration template
│
├── backend/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Settings (pydantic-settings)
│   ├── agents/
│   │   ├── support_agent.py    # LangChain ReAct agent
│   │   └── tools.py            # Agent tools (classify, email, slack, DB)
│   ├── api/
│   │   ├── tickets.py          # Ticket CRUD + webhook endpoint
│   │   └── logs.py             # Action log endpoints
│   ├── db/
│   │   ├── database.py         # SQLAlchemy engine + session
│   │   └── models.py           # ORM models (Ticket, ActionLog, SystemLog)
│   └── services/
│       ├── notifier.py         # Slack Incoming Webhook
│       └── email_service.py    # Async SMTP email
│
├── n8n/
│   └── workflows/
│       └── customer_support.json   # Importable n8n workflow
│
└── dashboard/
    └── app.py                  # Streamlit monitoring dashboard
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `MISTRAL_API_KEY` | ✅ | Mistral API key — free tier at [console.mistral.ai](https://console.mistral.ai), no credit card needed |
| `SLACK_WEBHOOK_URL` | Optional | Slack Incoming Webhook for escalations |
| `SMTP_HOST` | Optional | SMTP server (default: smtp.gmail.com) |
| `SMTP_USER` | Optional | SMTP username |
| `SMTP_PASSWORD` | Optional | SMTP app password |
| `POSTGRES_USER` | Optional | DB user (default: aob_user) |
| `POSTGRES_PASSWORD` | Optional | DB password (default: aob_password) |

If Slack/email is not configured, the system **logs a warning and continues** — it will not crash.

---

## What Makes This Production-Ready

- **Async processing** — tickets are acknowledged instantly (202 Accepted), agent runs in background
- **Error handling** — every tool catches exceptions and writes failure logs; agent marks ticket as `failed` if it crashes
- **Observability** — full action log per ticket, Streamlit dashboard with live data
- **Retry-safe** — agent re-reads ticket state from DB before each tool call
- **Real integrations** — actual SMTP email, actual Slack webhooks, actual PostgreSQL
- **Configurable** — all thresholds, prompts, and integrations are environment-variable driven
- **Separation of concerns** — n8n handles ingestion, Python handles intelligence, Streamlit handles visibility

---

## Demo Flow

1. Customer submits complaint via n8n webhook (or dashboard)
2. n8n validates → POSTs to `/tickets/webhook`
3. Backend saves ticket → background agent starts
4. Agent queries customer history → classifies as **CRITICAL**
5. Agent drafts empathetic reply → sends email to customer
6. Agent fires Slack alert to `#support-escalations`
7. Agent marks ticket resolved
8. Dashboard shows full audit trail: classification, email sent, Slack alert, timestamps

Total time from submission to email delivery: **~10 seconds**

---

## License

MIT
