"""Analytics: executive dashboard, deal-health scoring and CSV export."""
import csv
import io
from collections import defaultdict

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Invoice, QStatus, Quotation, QuotationEvent, Role, Subscription, User, utcnow
from ..security import internal_user
from ..serializers import f, invoice_out, iso, quotation_summary
from ..services import billing, workflow
from ..services.billing import add_months

router = APIRouter(tags=["reports"])

STAGES = [("Draft", (QStatus.DRAFT,)), ("In approval", (QStatus.PENDING_MANAGER, QStatus.PENDING_FINANCE)),
          ("Approved", (QStatus.APPROVED,)), ("With customer", (QStatus.SENT, QStatus.NEGOTIATING)),
          ("Won", (QStatus.ACCEPTED,)), ("Lost", QStatus.CLOSED_LOST)]


def _scoped_quotes(db: Session, user: User) -> list[Quotation]:
    query = db.query(Quotation)
    if user.role == Role.REP:
        query = query.filter(Quotation.rep_id == user.id)
    return query.all()


def _win_rate(won: int, lost: int) -> float:
    return round(won / (won + lost) * 100, 1) if won + lost else 0.0


@router.get("/reports/dashboard")
def dashboard(user: User = Depends(internal_user), db: Session = Depends(get_db)):
    workflow.expire_stale(db)
    quotes = _scoped_quotes(db, user)
    today = utcnow().date()
    won = [q for q in quotes if q.status == QStatus.ACCEPTED]
    lost = [q for q in quotes if q.status in QStatus.CLOSED_LOST]
    open_ = [q for q in quotes if q.status in QStatus.OPEN]
    quote_ids = {q.id for q in quotes}

    invoices = [i for i in db.query(Invoice).all() if user.role != Role.REP or i.quotation_id in quote_ids]
    inv_rows = [invoice_out(i, today) for i in invoices if i.status != "void"]
    subs = [s for s in db.query(Subscription).all() if user.role != Role.REP or s.quotation_id in quote_ids]
    mrr = sum(f(billing.subscription_mrr(s)) for s in subs)
    cycle = [(q.closed_at - q.created_at).days for q in won if q.closed_at]

    kpis = {
        "pipeline_value": round(sum(f(q.total) for q in open_), 2), "open_deals": len(open_),
        "won_value": round(sum(f(q.total) for q in won), 2), "won_deals": len(won),
        "win_rate": _win_rate(len(won), len(lost)),
        "avg_deal_size": round(sum(f(q.total) for q in won) / len(won), 2) if won else 0,
        "avg_cycle_days": round(sum(cycle) / len(cycle), 1) if cycle else 0,
        "mrr": round(mrr, 2), "arr": round(mrr * 12, 2),
        "outstanding": round(sum(r["balance"] for r in inv_rows), 2),
        "overdue": round(sum(r["balance"] for r in inv_rows if r["status"] == "overdue"), 2),
        "pending_approvals": sum(1 for q in quotes if q.status in (QStatus.PENDING_MANAGER, QStatus.PENDING_FINANCE)),
        "avg_margin": round(sum(f(q.margin_percent) for q in won) / len(won), 1) if won else 0,
    }

    funnel = [{"stage": name, "count": sum(1 for q in quotes if q.status in statuses),
               "value": round(sum(f(q.total) for q in quotes if q.status in statuses), 2)}
              for name, statuses in STAGES]

    months = [add_months(today.replace(day=1), -i) for i in range(5, -1, -1)]
    monthly = []
    for start in months:
        end = add_months(start, 1)
        in_month = lambda d: d is not None and start <= (d.date() if hasattr(d, "date") else d) < end  # noqa: E731
        monthly.append({
            "month": start.strftime("%b %y"),
            "quoted": round(sum(f(q.total) for q in quotes if in_month(q.created_at)), 2),
            "won": round(sum(f(q.total) for q in won if in_month(q.closed_at)), 2),
            "invoiced": round(sum(f(i.total) for i in invoices if i.status != "void" and in_month(i.issue_date)), 2),
            "collected": round(sum(f(p.amount) for i in invoices for p in i.payments if in_month(p.paid_at)), 2),
        })

    product_rev, category_disc = defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0.0])
    for q in won:
        for line in q.lines:
            entry = product_rev[line.product.name]
            entry[0] += f(line.line_total)
            entry[1] += line.quantity
            gross = f(line.unit_price) * line.quantity
            category_disc[line.product.category][0] += gross
            category_disc[line.product.category][1] += gross - f(line.line_total)
    top_products = [{"name": name, "revenue": round(rev, 2), "units": units}
                    for name, (rev, units) in sorted(product_rev.items(), key=lambda kv: -kv[1][0])[:6]]
    discount_by_category = [{"category": cat, "list_value": round(gross, 2), "discount_given": round(disc, 2),
                             "avg_discount_percent": round(disc / gross * 100, 1) if gross else 0}
                            for cat, (gross, disc) in sorted(category_disc.items())]

    reps = defaultdict(lambda: {"won": 0, "lost": 0, "won_value": 0.0, "pipeline": 0.0})
    for q in quotes:
        entry = reps[q.rep.name]
        if q.status == QStatus.ACCEPTED:
            entry["won"] += 1
            entry["won_value"] += f(q.total)
        elif q.status in QStatus.CLOSED_LOST:
            entry["lost"] += 1
        else:
            entry["pipeline"] += f(q.total)
    leaderboard = sorted(({"rep": name, "won_deals": v["won"], "won_value": round(v["won_value"], 2),
                           "pipeline": round(v["pipeline"], 2), "win_rate": _win_rate(v["won"], v["lost"])}
                          for name, v in reps.items()), key=lambda r: -r["won_value"])

    events_q = db.query(QuotationEvent).join(Quotation)
    if user.role == Role.REP:
        events_q = events_q.filter(Quotation.rep_id == user.id)
    activity = [{"id": e.id, "action": e.action, "actor_name": e.actor_name, "comment": e.comment,
                 "created_at": iso(e.created_at), "quotation_id": e.quotation_id, "number": e.quotation.number,
                 "customer_name": e.quotation.customer.name}
                for e in events_q.order_by(QuotationEvent.created_at.desc(), QuotationEvent.id.desc()).limit(10)]

    loss_reasons = defaultdict(int)
    for q in lost:
        loss_reasons[q.status] += 1

    return {"kpis": kpis, "funnel": funnel, "monthly": monthly, "top_products": top_products,
            "discount_by_category": discount_by_category, "leaderboard": leaderboard, "activity": activity,
            "loss_breakdown": [{"status": k, "count": v} for k, v in sorted(loss_reasons.items())]}


def score_deal(q: Quotation, now) -> dict:
    """Health score (0-100) for an open deal, with the reasons and a suggested next step."""
    score, reasons = 100, []
    idle_days = (now - q.updated_at).days
    if idle_days > 5:
        penalty = min(30, (idle_days - 5) * 3)
        score -= penalty
        reasons.append(f"No activity for {idle_days} days")
    risk = f(q.risk_score)
    if risk >= 25:
        score -= min(25, int(risk / 4))
        reasons.append(f"{q.risk_level.title()} commercial risk ({risk:.0f})")
    if q.valid_until:
        left = (q.valid_until - now.date()).days
        if left <= 7 and q.status in (QStatus.SENT, QStatus.NEGOTIATING, QStatus.APPROVED):
            score -= 20 if left <= 3 else 10
            reasons.append(f"Expires in {max(left, 0)} day(s)")
    if any(m.offer_status == "open" for m in q.messages):
        score -= 15
        reasons.append("Customer counter-offer is unanswered")
    if q.status in (QStatus.PENDING_MANAGER, QStatus.PENDING_FINANCE) and q.submitted_at:
        hours = (now - q.submitted_at).total_seconds() / 3600
        if hours > 48:
            score -= 15
            reasons.append(f"Stuck in approval for {int(hours // 24)} days")
    score = max(0, score)
    actions = {
        QStatus.DRAFT: "Finish the quote and submit it",
        QStatus.PENDING_MANAGER: "Nudge the Sales Manager for approval",
        QStatus.PENDING_FINANCE: "Nudge Finance for approval",
        QStatus.APPROVED: "Send the quotation to the customer",
        QStatus.SENT: "Follow up with the customer",
        QStatus.NEGOTIATING: "Respond to the customer's counter-offer",
    }
    return {**quotation_summary(q), "health_score": score, "reasons": reasons,
            "health": "healthy" if score >= 75 else "at_risk" if score >= 50 else "critical",
            "idle_days": idle_days, "next_action": actions.get(q.status, "")}


@router.get("/reports/deal-health")
def deal_health(user: User = Depends(internal_user), db: Session = Depends(get_db)):
    workflow.expire_stale(db)
    now = utcnow()
    deals = sorted((score_deal(q, now) for q in _scoped_quotes(db, user) if q.status in QStatus.OPEN),
                   key=lambda d: d["health_score"])
    summary = {h: {"count": sum(1 for d in deals if d["health"] == h),
                   "value": round(sum(d["total"] for d in deals if d["health"] == h), 2)}
               for h in ("healthy", "at_risk", "critical")}
    return {"summary": summary, "deals": deals}


@router.get("/reports/export/quotations.csv")
def export_quotations(user: User = Depends(internal_user), db: Session = Depends(get_db)):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Number", "Title", "Customer", "Sales rep", "Status", "Subtotal", "Discount", "Tax", "Total",
                     "Margin %", "Risk score", "Risk level", "Created", "Valid until", "Closed"])
    for q in sorted(_scoped_quotes(db, user), key=lambda x: x.id):
        writer.writerow([q.number, q.title, q.customer.name, q.rep.name, q.status, f(q.subtotal),
                         f(q.discount_total), f(q.tax_total), f(q.total), f(q.margin_percent), f(q.risk_score),
                         q.risk_level, q.created_at.date(), q.valid_until or "",
                         q.closed_at.date() if q.closed_at else ""])
    buffer.seek(0)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="dealflow360-quotations.csv"'})
