"""End-to-end API tests covering auth, RBAC and the whole quote-to-cash flow."""
from datetime import timedelta

from app.models import utcnow
from app.seed import DEMO_PASSWORD

LOW = [("NET-SW48", 2, 5), ("SUB-CLD", 1, 0)]     # inside policy -> auto-approved
MEDIUM = [("SW-VIRT", 2, 27)]                      # 7 pts over the Software tier -> manager
HIGH = [("SRV-R750", 2, 25)]                       # deep discount + negative margin -> manager + finance


# ----------------------------------------------------------------------------- auth & RBAC
def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_login_returns_token_and_profile(client, db):
    r = client.post("/api/auth/login", json={"email": "ADMIN@dealflow360.in", "password": DEMO_PASSWORD})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin" and r.json()["access_token"]


def test_login_rejects_bad_password_and_unknown_user(client, db):
    assert client.post("/api/auth/login", json={"email": "admin@dealflow360.in", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ghost@x.io", "password": DEMO_PASSWORD}).status_code == 401


def test_login_is_throttled_after_repeated_failures(client, db):
    for _ in range(8):
        client.post("/api/auth/login", json={"email": "admin@dealflow360.in", "password": "wrong"})
    r = client.post("/api/auth/login", json={"email": "admin@dealflow360.in", "password": DEMO_PASSWORD})
    assert r.status_code == 429


def test_protected_routes_need_a_valid_token(client, db):
    assert client.get("/api/quotations").status_code == 401
    assert client.get("/api/quotations", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_public_registration_always_creates_a_customer(client, db):
    r = client.post("/api/auth/register", json={"name": "Asha Verma", "company": "Verma Traders",
                                                "email": "asha@verma.example", "password": "Str0ngPass!",
                                                "role": "admin"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "customer"
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/quotations", headers=headers).status_code == 403
    assert client.get("/api/portal/my/overview", headers=headers).json()["company"] == "Verma Traders"
    dup = client.post("/api/auth/register", json={"name": "Asha", "company": "X Co", "email": "asha@verma.example",
                                                  "password": "Str0ngPass!"})
    assert dup.status_code == 409


def test_registration_validates_password_length(client, db):
    r = client.post("/api/auth/register", json={"name": "Al", "company": "Co", "email": "a@b.co", "password": "short"})
    assert r.status_code == 422


def test_only_admin_manages_users(api):
    assert api.get("manager", "/users").status_code == 403
    r = api.post("admin", "/users", {"name": "New Rep", "email": "newrep@dealflow360.in", "password": "Passw0rd!",
                                     "role": "sales_rep"})
    assert r.status_code == 201
    uid = r.json()["id"]
    assert api.client.patch(f"/api/users/{uid}", headers=api.token("admin"),
                            json={"is_active": False}).json()["is_active"] is False
    login = api.client.post("/api/auth/login", json={"email": "newrep@dealflow360.in", "password": "Passw0rd!"})
    assert login.status_code == 403


def test_admin_cannot_lock_themselves_out(api):
    me = api.get("admin", "/auth/me").json()
    r = api.client.patch(f"/api/users/{me['id']}", headers=api.token("admin"), json={"role": "sales_rep"})
    assert r.status_code == 400


def test_change_password(api):
    bad = api.post("rep2", "/auth/change-password", {"current_password": "wrong", "new_password": "NewPassw0rd!"})
    assert bad.status_code == 400
    assert api.post("rep2", "/auth/change-password", {"current_password": DEMO_PASSWORD,
                                                      "new_password": "NewPassw0rd!"}).status_code == 200
    assert api.client.post("/api/auth/login", json={"email": "sneha@dealflow360.in",
                                                    "password": "NewPassw0rd!"}).status_code == 200


def test_role_permissions_on_master_data(api):
    product = {"sku": "TST-1", "name": "Test product", "category": "Servers", "price": 1000, "cost": 600}
    assert api.post("rep", "/products", product).status_code == 403
    assert api.post("manager", "/products", product).status_code == 201
    assert api.post("manager", "/products", product).status_code == 409       # duplicate SKU
    assert api.post("finance", "/customers", {"name": "Nope Ltd"}).status_code == 403
    assert api.post("rep", "/customers", {"name": "Fresh Lead Pvt Ltd", "region": "South"}).status_code == 201
    assert api.get("customer", "/products").status_code == 403


# ----------------------------------------------------------------------------- quoting
def test_preview_prices_without_saving_and_flags_policy_limits(api):
    body = {"customer_id": 1, "payment_terms_days": 30,
            "lines": [{"product_id": api.pid("SRV-R750"), "quantity": 2, "discount_percent": 25}]}
    r = api.post("rep", "/quotations/preview", body).json()
    assert r["pricing"]["subtotal"] == 1370000.0 and r["pricing"]["discount_total"] == 342500.0
    assert r["pricing"]["total"] == 1212450.0
    assert r["pricing"]["lines"][0]["max_discount"] == 12.0
    assert r["risk"]["level"] == "high" and r["risk"]["required_level"] == 2
    assert api.get("rep", "/quotations").json() == []


def test_create_edit_and_delete_a_draft(api):
    q = api.quote(LOW)
    assert q["status"] == "draft" and q["number"].startswith("Q-") and len(q["lines"]) == 2
    assert q["total"] == round(2 * 142000 * 0.95 * 1.18 + 18500 * 1.18, 2)
    body = {"title": "Renamed", "customer_id": 1, "payment_terms_days": 30,
            "lines": [{"product_id": api.pid("NET-AP6"), "quantity": 10, "discount_percent": 0}]}
    edited = api.put("rep", f"/quotations/{q['id']}", body).json()
    assert edited["title"] == "Renamed" and len(edited["lines"]) == 1 and edited["subtotal"] == 285000.0
    assert api.client.delete(f"/api/quotations/{q['id']}", headers=api.token("rep")).status_code == 204
    assert api.get("rep", f"/quotations/{q['id']}").status_code == 404


def test_quote_validation(api):
    bad_qty = {"title": "Bad", "customer_id": 1, "lines": [{"product_id": api.pid("NET-AP6"), "quantity": 0}]}
    assert api.post("rep", "/quotations", bad_qty).status_code == 422
    bad_disc = {"title": "Bad", "customer_id": 1,
                "lines": [{"product_id": api.pid("NET-AP6"), "quantity": 1, "discount_percent": 95}]}
    assert api.post("rep", "/quotations", bad_disc).status_code == 422
    assert api.post("rep", "/quotations", {"title": "Bad", "customer_id": 999, "lines": []}).status_code == 422
    empty = api.quote([])
    assert api.post("rep", f"/quotations/{empty['id']}/submit").status_code == 422


def test_reps_only_see_their_own_quotations(api):
    mine = api.quote(LOW, who="rep")
    assert api.get("rep2", f"/quotations/{mine['id']}").status_code == 404
    assert api.get("rep2", "/quotations").json() == []
    assert len(api.get("manager", "/quotations").json()) == 1


# ----------------------------------------------------------------------------- approvals
def test_low_risk_quote_is_auto_approved(api):
    q = api.post("rep", f"/quotations/{api.quote(LOW)['id']}/submit").json()
    assert q["status"] == "approved" and q["risk"]["level"] == "low"
    assert [e["action"] for e in q["events"]] == ["created", "submitted", "auto_approved"]
    assert api.get("manager", "/approvals/queue").json() == []


def test_medium_risk_needs_manager_only(api):
    q = api.post("rep", f"/quotations/{api.quote(MEDIUM)['id']}/submit").json()
    assert q["status"] == "pending_manager" and q["risk"]["level"] == "medium"
    queue = api.get("manager", "/approvals/queue").json()
    assert len(queue) == 1 and queue[0]["can_act"] is True
    assert api.get("finance", "/approvals/queue").json()[0]["can_act"] is False
    assert api.post("finance", f"/quotations/{q['id']}/approve").status_code == 403
    assert api.post("rep", f"/quotations/{q['id']}/approve").status_code == 403
    assert api.post("manager", f"/quotations/{q['id']}/approve").json()["status"] == "approved"


def test_high_risk_needs_manager_then_finance(api):
    q = api.post("rep", f"/quotations/{api.quote(HIGH)['id']}/submit").json()
    assert q["status"] == "pending_manager" and q["risk"]["level"] == "high"
    q = api.post("manager", f"/quotations/{q['id']}/approve", {"comment": "Strategic logo"}).json()
    assert q["status"] == "pending_finance"
    assert api.post("manager", f"/quotations/{q['id']}/approve").status_code == 403
    q = api.post("finance", f"/quotations/{q['id']}/approve").json()
    assert q["status"] == "approved" and q["approved_level"] == 2
    assert len(api.get("manager", "/approvals/history").json()) == 2


def test_reject_and_request_changes_require_a_comment(api):
    q = api.post("rep", f"/quotations/{api.quote(MEDIUM)['id']}/submit").json()
    assert api.post("manager", f"/quotations/{q['id']}/reject").status_code == 422
    back = api.post("manager", f"/quotations/{q['id']}/request-changes", {"comment": "Trim the discount"}).json()
    assert back["status"] == "draft"
    q = api.post("rep", f"/quotations/{q['id']}/submit").json()
    rejected = api.post("manager", f"/quotations/{q['id']}/reject", {"comment": "No budget for this"}).json()
    assert rejected["status"] == "rejected"
    assert api.post("rep", f"/quotations/{q['id']}/send").status_code == 409


def test_only_drafts_are_editable_and_revisions_copy_lines(api):
    q = api.post("rep", f"/quotations/{api.quote(LOW)['id']}/submit").json()
    body = {"title": "Sneaky edit", "customer_id": 1, "lines": []}
    assert api.put("rep", f"/quotations/{q['id']}", body).status_code == 409
    rev = api.post("rep", f"/quotations/{q['id']}/duplicate")
    assert rev.status_code == 201
    rev = rev.json()
    assert rev["status"] == "draft" and rev["version"] == 2 and rev["parent_id"] == q["id"]
    assert rev["total"] == q["total"] and rev["number"] != q["number"]


# ----------------------------------------------------------------------------- portal + negotiation
def test_portal_link_hides_internal_data_and_unsent_quotes(api):
    draft = api.quote(LOW)
    assert draft["portal_token"] is None
    sent = api.to_sent(LOW)
    r = api.client.get(f"/api/portal/quotes/{sent['portal_token']}")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == sent["total"] and body["can_respond"] is True
    for secret in ("unit_cost", "margin_percent", "risk", "cost_total", "events"):
        assert secret not in r.text
    assert api.client.get("/api/portal/quotes/not-a-real-token").status_code == 404


def test_customer_accepts_and_order_to_cash_runs(api):
    sent = api.to_sent(LOW)
    r = api.client.post(f"/api/portal/quotes/{sent['portal_token']}/accept", json={"name": "Rohit Bansal"})
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert api.client.post(f"/api/portal/quotes/{sent['portal_token']}/accept", json={}).status_code == 409

    # fulfilment: one shipment from the customer's own region, stock reserved
    orders = api.get("manager", "/fulfillment/orders").json()
    assert len(orders) == 1 and orders[0]["warehouse_code"] == "DEL" and orders[0]["status"] == "planned"
    assert api.stock("NET-SW48", "DEL").reserved == 2

    # billing: one-time invoice + pro-rated first recurring invoice + an active subscription
    invoices = api.get("finance", "/invoices").json()["invoices"]
    kinds = {i["kind"]: i for i in invoices}
    assert kinds["one_time"]["total"] == round(2 * 142000 * 0.95 * 1.18, 2)
    assert 0 < kinds["recurring"]["total"] <= round(18500 * 1.18, 2)
    subs = api.get("finance", "/subscriptions").json()
    assert subs["summary"]["active"] == 1 and subs["summary"]["mrr"] == 18500.0

    # shipping consumes the stock
    oid = orders[0]["id"]
    assert api.post("rep", f"/fulfillment/orders/{oid}/advance").status_code == 403
    assert api.post("manager", f"/fulfillment/orders/{oid}/advance").json()["status"] == "picking"
    assert api.post("manager", f"/fulfillment/orders/{oid}/advance").json()["status"] == "shipped"
    stock = api.stock("NET-SW48", "DEL")
    assert (stock.quantity, stock.reserved) == (8, 0)
    assert api.post("manager", f"/fulfillment/orders/{oid}/advance").json()["status"] == "delivered"
    assert api.post("manager", f"/fulfillment/orders/{oid}/advance").status_code == 409


def test_counter_offer_within_policy_updates_price_and_stays_with_customer(api):
    sent = api.to_sent([("NET-SW48", 2, 5)])
    token = sent["portal_token"]
    r = api.client.post(f"/api/portal/quotes/{token}/messages",
                        json={"name": "Rohit", "message": "Can you do 8%?", "proposed_discount": 8})
    assert r.json()["status"] == "negotiating"
    second = api.client.post(f"/api/portal/quotes/{token}/messages",
                             json={"name": "Rohit", "message": "Or 9?", "proposed_discount": 9})
    assert second.status_code == 409                       # one open counter-offer at a time
    q = api.get("rep", f"/quotations/{sent['id']}").json()
    mid = next(m["id"] for m in q["messages"] if m["offer_status"] == "open")
    impact = api.get("rep", f"/quotations/{sent['id']}/messages/{mid}/impact").json()
    assert impact["needs_reapproval"] is False and impact["revenue_delta"] < 0
    q = api.post("rep", f"/quotations/{sent['id']}/messages/{mid}/respond", {"accept": True}).json()
    assert q["status"] == "sent" and q["total"] == round(2 * 142000 * 0.92 * 1.18, 2) == impact["new_total"]


def test_counter_offer_beyond_policy_goes_back_for_approval(api):
    sent = api.to_sent([("NET-SW48", 2, 5)])
    token = sent["portal_token"]
    api.client.post(f"/api/portal/quotes/{token}/messages",
                    json={"name": "Rohit", "message": "22% and we sign", "proposed_discount": 22})
    q = api.get("rep", f"/quotations/{sent['id']}").json()
    mid = next(m["id"] for m in q["messages"] if m["offer_status"] == "open")
    assert api.get("rep", f"/quotations/{sent['id']}/messages/{mid}/impact").json()["needs_reapproval"] is True
    q = api.post("rep", f"/quotations/{sent['id']}/messages/{mid}/respond", {"accept": True}).json()
    assert q["status"] == "pending_manager"
    portal = api.client.get(f"/api/portal/quotes/{token}").json()
    assert portal["status"] == "under_revision" and portal["can_respond"] is False
    assert api.client.post(f"/api/portal/quotes/{token}/accept", json={}).status_code == 409
    api.post("manager", f"/quotations/{sent['id']}/approve")
    q = api.post("rep", f"/quotations/{sent['id']}/send").json()
    assert q["status"] == "sent" and q["portal_token"] == token
    assert api.client.post(f"/api/portal/quotes/{token}/accept", json={}).json()["status"] == "accepted"


def test_rejecting_a_counter_offer_keeps_the_original_price(api):
    sent = api.to_sent([("NET-SW48", 2, 5)])
    api.client.post(f"/api/portal/quotes/{sent['portal_token']}/messages",
                    json={"name": "Rohit", "message": "30%?", "proposed_discount": 30})
    q = api.get("rep", f"/quotations/{sent['id']}").json()
    mid = next(m["id"] for m in q["messages"] if m["offer_status"] == "open")
    q = api.post("rep", f"/quotations/{sent['id']}/messages/{mid}/respond",
                 {"accept": False, "comment": "Best we can do is the current price."}).json()
    assert q["status"] == "sent" and q["total"] == sent["total"]
    assert q["messages"][-1]["side"] == "internal"
    assert api.post("rep", f"/quotations/{sent['id']}/messages/{mid}/respond", {"accept": True}).status_code == 409


def test_customer_can_decline_and_rep_can_mark_lost_or_won(api):
    a = api.to_sent(LOW)
    r = api.client.post(f"/api/portal/quotes/{a['portal_token']}/decline", json={"name": "R", "reason": "Budget"})
    assert r.json()["status"] == "declined"
    b = api.to_sent(LOW)
    assert api.post("rep", f"/quotations/{b['id']}/mark-lost", {"reason": "Went silent"}).json()["status"] == "lost"
    c = api.to_sent(LOW)
    assert api.post("rep", f"/quotations/{c['id']}/mark-won").json()["status"] == "accepted"


def test_expired_quotes_cannot_be_accepted(api, db):
    from app.models import Quotation
    sent = api.to_sent(LOW)
    db.get(Quotation, sent["id"]).valid_until = utcnow().date() - timedelta(days=1)
    db.commit()
    assert api.client.get(f"/api/portal/quotes/{sent['portal_token']}").json()["status"] == "expired"
    assert api.client.post(f"/api/portal/quotes/{sent['portal_token']}/accept", json={}).status_code == 409
    assert api.get("rep", f"/quotations/{sent['id']}").json()["status"] == "expired"


def test_customer_account_sees_only_its_own_company(api):
    mine = api.to_sent(LOW, customer_id=1)
    api.to_sent(LOW, customer_id=2)
    api.quote(LOW, customer_id=1)                     # draft: never visible to the customer
    overview = api.get("customer", "/portal/my/overview").json()
    assert overview["company"] == "Aravalli Steel Works"
    assert [q["id"] for q in overview["quotations"]] == [mine["id"]]
    assert "risk_score" not in overview["quotations"][0]


# ----------------------------------------------------------------------------- fulfilment
def test_split_shipment_and_backorder_allocation(api):
    sent = api.to_sent([("SRV-T350", 26, 0)], customer_id=2)   # 10 per warehouse -> needs 3 + backorder
    plan = api.get("rep", f"/quotations/{sent['id']}/fulfillment-plan").json()
    assert plan["shipment_count"] == 3 and plan["shipments"][0]["code"] == "BOM"
    assert sum(s["units"] for s in plan["shipments"]) == 26
    assert plan["shipments"][-1]["units"] == 6 and plan["fully_allocated"]

    big = api.to_sent([("SRV-T350", 45, 0)], customer_id=2)
    api.post("rep", f"/quotations/{big['id']}/mark-won")
    orders = api.get("manager", f"/fulfillment/orders").json()
    back = [o for o in orders if o["status"] == "backorder"]
    assert len(orders) == 5 and len(back) == 1 and back[0]["units"] == 5
    # nothing to allocate yet
    r = api.post("manager", f"/fulfillment/orders/{back[0]['id']}/allocate").json()
    assert r["created"] == [] and r["remaining_backorder"] is True
    # receive stock, then release the backorder
    api.post("manager", "/inventory/adjust", {"warehouse_id": api.wid("BLR"), "product_id": api.pid("SRV-T350"),
                                              "delta": 8, "reason": "PO received"})
    r = api.post("manager", f"/fulfillment/orders/{back[0]['id']}/allocate").json()
    assert len(r["created"]) == 1 and r["created"][0]["units"] == 5 and r["remaining_backorder"] is False
    stock = api.stock("SRV-T350", "BLR")
    assert (stock.quantity, stock.reserved) == (18, 15)


def test_services_are_billed_but_never_shipped(api):
    sent = api.to_sent([("NET-FW90", 1, 0), ("SVC-INST", 2, 0)])
    plan = api.get("rep", f"/quotations/{sent['id']}/fulfillment-plan").json()
    assert plan["total_units"] == 1 and plan["backorder"] == [] and plan["fully_allocated"]
    api.post("rep", f"/quotations/{sent['id']}/mark-won")
    orders = api.get("manager", "/fulfillment/orders").json()
    assert len(orders) == 1 and [l["sku"] for l in orders[0]["lines"]] == ["NET-FW90"]
    invoice = api.get("finance", "/invoices").json()["invoices"][0]
    assert invoice["total"] == round((218000 + 2 * 45000) * 1.18, 2)        # the service is still invoiced
    body = {"warehouse_id": api.wid("BOM"), "product_id": api.pid("SVC-INST"), "delta": 5}
    assert api.post("manager", "/inventory/adjust", body).status_code == 422
    listed = {p["sku"]: p for p in api.get("rep", "/products").json()}
    assert listed["SVC-INST"]["is_stocked"] is False and "stock_available" not in listed["SVC-INST"]
    assert listed["NET-FW90"]["stock_available"] == 39 and listed["SUB-CLD"]["is_stocked"] is False


def test_stock_cannot_drop_below_reserved(api):
    sent = api.to_sent([("NET-FW90", 4, 0)])
    api.post("rep", f"/quotations/{sent['id']}/mark-won")
    body = {"warehouse_id": api.wid("DEL"), "product_id": api.pid("NET-FW90"), "delta": -8}
    assert api.post("manager", "/inventory/adjust", body).status_code == 409
    body["delta"] = -6
    assert api.post("manager", "/inventory/adjust", body).json()["available"] == 0
    assert api.post("rep", "/inventory/adjust", body).status_code == 403
    low = api.get("rep", "/inventory?low_only=true").json()
    assert any(r["sku"] == "NET-FW90" and r["warehouse"] == "DEL" for r in low)


# ----------------------------------------------------------------------------- billing
def _won_invoice(api, lines=(("NET-SW48", 2, 0),)):
    sent = api.to_sent(list(lines))
    api.post("rep", f"/quotations/{sent['id']}/mark-won")
    return api.get("finance", "/invoices").json()["invoices"][0]


def test_payments_partial_full_and_overpayment(api):
    inv = _won_invoice(api)
    assert inv["total"] == 335120.0 and inv["status"] == "issued"
    url = f"/invoices/{inv['id']}/payments"
    assert api.post("rep", url, {"amount": 100}).status_code == 403
    part = api.post("finance", url, {"amount": 135120, "method": "upi", "reference": "UTR1"}).json()
    assert part["status"] == "partially_paid" and part["balance"] == 200000.0
    assert api.post("finance", url, {"amount": 200000.01}).status_code == 409
    paid = api.post("finance", url, {"amount": 200000}).json()
    assert paid["status"] == "paid" and paid["balance"] == 0 and len(paid["payments"]) == 2
    assert api.post("finance", f"/invoices/{inv['id']}/void").status_code == 409
    summary = api.get("finance", "/invoices").json()["summary"]
    assert summary == {"billed": 335120.0, "collected": 335120.0, "outstanding": 0.0, "overdue": 0.0}


def test_void_and_overdue_invoices(api, db):
    from app.models import Invoice
    inv = _won_invoice(api)
    db.get(Invoice, inv["id"]).due_date = utcnow().date() - timedelta(days=5)
    db.commit()
    listed = api.get("finance", "/invoices?status=overdue").json()
    assert listed["invoices"][0]["days_overdue"] == 5 and listed["summary"]["overdue"] == 335120.0
    assert api.post("finance", f"/invoices/{inv['id']}/void").json()["status"] == "void"
    assert api.post("finance", f"/invoices/{inv['id']}/payments", {"amount": 10}).status_code == 409
    assert api.get("finance", "/invoices").json()["summary"]["outstanding"] == 0


def test_recurring_billing_run_and_subscription_lifecycle(api):
    sent = api.to_sent([("SUB-SOC", 1, 0), ("SUB-AMC", 2, 0)])
    api.post("rep", f"/quotations/{sent['id']}/mark-won")
    subs = api.get("finance", "/subscriptions").json()
    assert subs["summary"]["mrr"] == 85000 + 2 * 96000 / 3 and subs["summary"]["arr"] == subs["summary"]["mrr"] * 12
    assert api.get("manager", "/fulfillment/orders").json() == []      # nothing physical to ship

    assert api.post("finance", "/subscriptions/run-billing").json()["invoices_created"] == 0
    future = (utcnow().date() + timedelta(days=65)).isoformat()
    assert api.post("manager", "/subscriptions/run-billing", {"as_of": future}).status_code == 403
    run = api.post("finance", "/subscriptions/run-billing", {"as_of": future}).json()
    monthly = [i for i in run["invoices"] if i["total"] == round(85000 * 1.18, 2)]
    quarterly = [i for i in run["invoices"] if i["total"] == round(2 * 96000 * 1.18, 2)]
    assert len(monthly) in (2, 3) and len(quarterly) == 1
    assert api.post("finance", "/subscriptions/run-billing", {"as_of": future}).json()["invoices_created"] == 0

    soc = next(s for s in subs["subscriptions"] if s["sku"] == "SUB-SOC")
    assert api.post("finance", f"/subscriptions/{soc['id']}/pause").json()["status"] == "paused"
    assert api.post("finance", f"/subscriptions/{soc['id']}/pause").status_code == 409
    later = (utcnow().date() + timedelta(days=130)).isoformat()
    run = api.post("finance", "/subscriptions/run-billing", {"as_of": later}).json()
    assert all("SOC" not in str(i) for i in run["invoices"]) and run["invoices_created"] >= 1
    assert api.post("finance", f"/subscriptions/{soc['id']}/resume").json()["status"] == "active"
    cancelled = api.post("finance", f"/subscriptions/{soc['id']}/cancel").json()
    assert cancelled["status"] == "cancelled" and cancelled["next_billing_date"] is None and cancelled["mrr"] == 0
    assert api.post("finance", f"/subscriptions/{soc['id']}/resume").status_code == 409


def test_billing_schedule_projection(api):
    q = api.quote([("NET-SW48", 1, 0), ("SUB-CLD", 2, 0)])
    plan = api.get("rep", f"/quotations/{q['id']}/billing-schedule").json()
    assert plan["one_time_total"] == 167560.0 and plan["mrr"] == 37000.0
    assert plan["subscriptions"][0]["period_amount"] == 37000.0
    assert 12 <= len(plan["timeline"]) <= 13
    assert plan["first_year_value"] == round(sum(t["amount"] for t in plan["timeline"]), 2)


# ----------------------------------------------------------------------------- analytics & governance
def test_dashboard_deal_health_and_export(api):
    won = api.to_sent(LOW)
    api.post("rep", f"/quotations/{won['id']}/mark-won")
    lost = api.to_sent(LOW)
    api.post("rep", f"/quotations/{lost['id']}/mark-lost", {"reason": "No budget"})
    api.post("rep", f"/quotations/{api.quote(HIGH)['id']}/submit")
    api.quote(LOW, who="rep2")

    d = api.get("manager", "/reports/dashboard").json()
    assert d["kpis"]["won_deals"] == 1 and d["kpis"]["win_rate"] == 50.0 and d["kpis"]["open_deals"] == 2
    assert d["kpis"]["pending_approvals"] == 1 and d["kpis"]["mrr"] == 18500.0
    assert d["kpis"]["won_value"] == won["total"]
    assert {s["stage"]: s["count"] for s in d["funnel"]} == {"Draft": 1, "In approval": 1, "Approved": 0,
                                                             "With customer": 0, "Won": 1, "Lost": 1}
    assert len(d["monthly"]) == 6 and d["monthly"][-1]["won"] == won["total"]
    assert d["top_products"][0]["name"].startswith("48-Port")
    assert api.get("rep2", "/reports/dashboard").json()["kpis"]["won_deals"] == 0      # reps see their own book

    health = api.get("manager", "/reports/deal-health").json()
    assert len(health["deals"]) == 2
    risky = next(x for x in health["deals"] if x["status"] == "pending_manager")
    assert risky["health_score"] < 100 and any("risk" in r for r in risky["reasons"])

    csv = api.get("manager", "/reports/export/quotations.csv")
    assert csv.headers["content-type"].startswith("text/csv")
    assert len(csv.text.strip().splitlines()) == 5 and won["number"] in csv.text


def test_policy_settings_change_approval_routing(api):
    assert api.client.put("/api/settings", headers=api.token("manager"), json={"manager_threshold": 5}).status_code == 403
    bad = api.client.put("/api/settings", headers=api.token("admin"),
                         json={"manager_threshold": 60, "finance_threshold": 40})
    assert bad.status_code == 422
    q = api.quote(MEDIUM)
    assert q["risk"]["level"] == "medium"
    # raise the Software discount tier -> the same quote is now inside policy
    r = api.post("admin", "/discount-tiers", {"name": "Software", "category": "Software", "max_discount_percent": 30})
    assert r.status_code == 201
    assert api.get("rep", f"/quotations/{q['id']}").json()["risk"]["level"] == "low"
    assert api.post("rep", f"/quotations/{q['id']}/submit").json()["status"] == "approved"
    tiers = api.get("rep", "/discount-tiers").json()
    default = next(t for t in tiers if t["category"] is None)
    assert api.client.delete(f"/api/discount-tiers/{default['id']}", headers=api.token("admin")).status_code == 400


def test_audit_trail_records_who_did_what(api):
    q = api.post("rep", f"/quotations/{api.quote(MEDIUM)['id']}/submit").json()
    api.post("manager", f"/quotations/{q['id']}/approve")
    logs = api.get("manager", "/audit-logs").json()
    actions = [(l["action"], l["actor_name"]) for l in logs]
    assert ("quotation.approve", "Priya Sharma") in actions and ("quotation.submit", "Arjun Mehta") in actions
    assert api.get("rep", "/audit-logs").status_code == 403


def test_customer_360_and_upsells(api):
    won = api.to_sent(LOW)
    api.post("rep", f"/quotations/{won['id']}/mark-won")
    c = api.get("rep", "/customers/1").json()
    assert len(c["quotations"]) == 1 and len(c["invoices"]) == 2 and c["outstanding"] > 0
    listed = api.get("rep", "/customers?q=aravalli").json()
    assert len(listed) == 1 and listed[0]["won_value"] == won["total"]
    ideas = api.get("rep", f"/products/{api.pid('SRV-R750')}/upsells").json()
    assert 1 <= len(ideas) <= 4 and any(i["is_subscription"] for i in ideas)
    assert all(i["margin_delta"] > 0 for i in ideas)
