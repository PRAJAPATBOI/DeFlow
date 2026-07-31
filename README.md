# DealFlow360

**A B2B quote-to-cash platform** — configure and price quotations, route risky deals through
approvals, negotiate with customers in a self-service portal, split shipments across warehouses,
and bill one-time and recurring revenue.

Built by **Ramesh Prajapat** · FastAPI · SQLAlchemy · Astro · React · Tailwind CSS

![Dashboard](docs/screenshots/dashboard.png)

---

## What it does

| Stage | What happens | Where |
|---|---|---|
| **Quote** | Reps build quotations with live pricing, GST, margin and a risk score that updates as they type. Cross-sell suggestions are ranked by margin. | Quotations → New |
| **Approve** | A 0–100 risk score (discount over policy, margin erosion, credit exposure, payment terms) decides the route: auto-approve, Sales Manager, or Manager → Finance. | Approvals |
| **Negotiate** | The customer opens a secure link — no login — and can accept, decline, message, or raise a counter-offer. The rep sees the revenue, margin and risk impact before answering. Counter-offers that exceed what was approved go back for approval. | Customer portal |
| **Fulfil** | On acceptance the order is split across warehouses (fewest shipments first, then cheapest freight) and stock is reserved. Shortfalls become backorders that can be released when stock arrives. | Fulfilment, Inventory |
| **Bill** | One-time items are invoiced immediately. Each recurring line becomes a subscription billed on the 1st, with a day-level pro-rated first invoice. | Invoices, Subscriptions |
| **Collect & learn** | Record full or partial payments, track overdue receivables, and watch win rate, MRR/ARR, discount leakage, cash conversion and deal health. | Reports, Deal Health |
| **Govern** | Admins tune discount tiers and approval thresholds, manage users and roles, and review an append-only audit trail. | Governance |

<table>
<tr>
<td><img src="docs/screenshots/quotations.png" alt="Pipeline board"></td>
<td><img src="docs/screenshots/quotation.png" alt="Quote builder"></td>
</tr>
<tr>
<td><img src="docs/screenshots/approvals.png" alt="Approvals queue"></td>
<td><img src="docs/screenshots/reports.png" alt="Reports"></td>
</tr>
</table>

## Quick start

Requirements: **Python 3.12+** and **Node.js 20+**.

```bash
# 1. Backend
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2. Frontend (one-off build; FastAPI serves the result)
cd ../frontend
npm install
npm run build

# 3. Run
cd ../backend
uvicorn app.main:app --port 8000
```

Open **http://localhost:8000**. On first start the app creates a SQLite database and loads a
demo dataset (38 deals with six months of history). API docs live at `/api/docs`.

### Demo accounts

Password for all of them: `Demo@1234` (the sign-in page has one-click buttons).

| Role | Email | Can |
|---|---|---|
| Administrator | `admin@dealflow360.in` | Everything, including policy and user management |
| Sales Manager | `manager@dealflow360.in` | Approve medium-risk deals, manage catalogue, stock and shipments |
| Sales Rep | `arjun@dealflow360.in`, `sneha@dealflow360.in` | Build, send and negotiate their own quotations |
| Finance | `finance@dealflow360.in` | Final sign-off on high-risk deals, payments, billing runs |
| Customer | `customer@aravalli.example` | Portal only: their own quotations and invoices |

### Developing

Run the API and the Astro dev server side by side; `/api` is proxied, so there is no CORS setup.

```bash
cd backend  && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev          # http://localhost:4321
```

Reset the demo data at any time with `python -m app.seed --reset` (from `backend/`).

## Architecture

```mermaid
flowchart LR
    subgraph Browser
        UI[Astro pages + React views]
        Portal[Customer portal]
    end
    subgraph FastAPI
        R[Routers<br/>auth · catalog · quotations<br/>operations · reports · portal]
        S[Services<br/>pricing & risk · workflow<br/>fulfilment · billing]
        M[(SQLAlchemy models)]
    end
    UI -- JWT / JSON --> R
    Portal -- secure link token --> R
    R --> S --> M
    M --> DB[(SQLite / PostgreSQL)]
```

- **Routers are thin.** All business rules live in `backend/app/services` as plain functions, which
  is why the seeder can replay real history through them and the unit tests need no HTTP.
- **One deployable.** FastAPI serves the built frontend, so production is a single process and
  a single origin. `Dockerfile` and `docker-compose.yml` package it with PostgreSQL.
- **No frontend data mocks.** Every screen reads from the API.

```
backend/
  app/
    main.py            app factory, static hosting, error handling
    config.py          environment settings
    models.py          18 tables
    schemas.py         request validation (Pydantic v2)
    serializers.py     response shaping; strips cost/margin/risk for customers
    security.py        bcrypt, JWT, role dependencies
    routers/           auth, catalog, quotations, operations, reports, portal
    services/
      pricing.py       Decimal pricing engine + blended risk score
      workflow.py      quotation state machine, negotiation, audit
      fulfillment.py   multi-warehouse split planner, reservations, backorders
      billing.py       invoices, proration, recurring billing, payments
    seed.py            demo data, generated by running the real workflow
  alembic/             database migrations
  tests/               56 tests (engines + end-to-end API)
frontend/
  src/
    pages/             one .astro file per route
    views/             React screens
    components/        app shell, UI kit, SVG charts (no chart library)
    lib/               API client, formatting
e2e/                   browser tests (Puppeteer against local Chrome/Edge)
```

## How the engines work

### Quotation lifecycle

```mermaid
stateDiagram-v2
    [*] --> draft
    draft --> approved: submit (low risk)
    draft --> pending_manager: submit (medium / high)
    pending_manager --> approved: manager approves (medium)
    pending_manager --> pending_finance: manager approves (high)
    pending_finance --> approved: finance approves
    pending_manager --> draft: changes requested
    pending_manager --> rejected
    pending_finance --> rejected
    approved --> sent: send to customer
    sent --> negotiating: counter-offer
    negotiating --> sent: rep answers
    negotiating --> pending_manager: accepted counter exceeds approval
    sent --> accepted: customer accepts
    sent --> declined
    sent --> expired: validity ends
    accepted --> [*]: orders + invoices + subscriptions
```

Reps cannot approve their own quotations, rejections require a comment, and only drafts are
editable — anything else is revised by creating a new version.

### Risk score

| Signal | Max points | Rule |
|---|---|---|
| Discount over policy | 40 | 4 points per % above the category's discount tier, weighted by line value |
| Margin erosion | 30 | 2 points per % below the minimum blended margin (default 25%) |
| Credit exposure | 25 | Starts when the deal passes 50% of the customer's credit limit; a deal above the limit always needs a manager |
| Payment terms | 15 | Credit days beyond net-30, scaling to net-90 |

Score < 25 auto-approves, 25–54 needs a Sales Manager, 55+ needs Manager then Finance. Tiers and
thresholds are editable under **Governance** and take effect on all open quotations.

### Split fulfilment

For the physical lines of a won deal the planner picks a single warehouse if one can cover
everything (preferring the customer's region, which is cheaper and faster). Otherwise it
repeatedly takes the warehouse that covers the most outstanding units, breaking ties on freight
cost. Stock is reserved on acceptance and deducted on shipment; reserved stock can never be
written off below the committed quantity.

### Subscription billing

Billing is anchored to the 1st of the month. A subscription starting on the 16th of a 30-day
month is invoiced 15/30 of one month's price, then full periods from the next 1st. Quarterly and
annual plans pro-rate on their monthly equivalent. The billing run is idempotent — running it
twice for the same date never double-bills — and paused subscriptions are not back-billed.

## Security

- Passwords hashed with bcrypt; JWT bearer sessions; failed sign-ins throttled per account.
- Role checks on every endpoint. Reps only see their own quotations, orders and invoices.
- Public sign-up can only ever create a customer-portal account.
- Customer responses never contain cost, margin, risk or the internal approval trail.
- Portal links use a 192-bit random token and stop working when the quotation is withdrawn.
- `ENVIRONMENT=production` refuses to start with the default secret key.

Configuration is by environment variable — see [`backend/.env.example`](backend/.env.example).

## Testing

```bash
cd backend && python -m pytest          # 56 tests, ~30 s, in-memory SQLite
```

The suite covers the pricing arithmetic, every risk band, proration edge cases (month-end, year
boundary), the split planner, authentication and role permissions, the full approval matrix,
negotiation and re-approval, order-to-cash, payments, billing runs and reporting.

Browser tests drive the real UI with one isolated session per role. With the app running on
port 8000:

```bash
cd e2e && npm install
npm run smoke     # opens every page, fails on any console error or failed API call
npm run flow      # rep → manager → customer portal → fulfilment → finance → governance → mobile
```

CI (`.github/workflows/ci.yml`) runs the backend tests, verifies migrations and builds the frontend.

## PostgreSQL & Docker

```bash
# PostgreSQL without Docker
set DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/dealflow360
alembic upgrade head
uvicorn app.main:app --port 8000

# Everything in containers
set SECRET_KEY=<long random string>
docker compose up --build
```

## API overview

Interactive documentation: `http://localhost:8000/api/docs`

| Area | Endpoints |
|---|---|
| Auth | `POST /api/auth/login` · `register` · `change-password` · `GET /api/auth/me` · `/api/users` |
| Master data | `/api/customers` · `/api/products` · `/api/products/{id}/upsells` · `/api/warehouses` · `/api/inventory` |
| Quotations | `/api/quotations` CRUD · `preview` · `submit` · `approve` · `reject` · `request-changes` · `send` · `mark-won` · `mark-lost` · `duplicate` |
| Negotiation | `/api/quotations/{id}/messages` · `…/{message_id}/impact` · `…/{message_id}/respond` |
| What-if | `/api/quotations/{id}/fulfillment-plan` · `/api/quotations/{id}/billing-schedule` |
| Operations | `/api/fulfillment/orders` · `/api/invoices` · `/api/invoices/{id}/payments` · `/api/subscriptions` · `run-billing` |
| Analytics | `/api/reports/dashboard` · `deal-health` · `export/quotations.csv` |
| Governance | `/api/settings` · `/api/discount-tiers` · `/api/audit-logs` |
| Portal | `/api/portal/quotes/{token}` · `accept` · `decline` · `messages` · `/api/portal/my/overview` |
