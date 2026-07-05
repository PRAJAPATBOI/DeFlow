import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SEED_ON_START"] = "false"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal, reset_database
from app.main import app
from app.models import Inventory, Product, Warehouse
from app.routers import auth as auth_router
from app.seed import DEMO_PASSWORD, _seed_master

EMAILS = {"admin": "admin@dealflow360.in", "manager": "manager@dealflow360.in", "rep": "arjun@dealflow360.in",
          "rep2": "sneha@dealflow360.in", "finance": "finance@dealflow360.in",
          "customer": "customer@aravalli.example"}


@pytest.fixture()
def db():
    reset_database()
    session = SessionLocal()
    _seed_master(session)
    # deterministic stock: 10 of every stocked product in every warehouse
    for inv in session.query(Inventory).all():
        inv.quantity, inv.reserved = 10, 0
    session.commit()
    auth_router._failed.clear()
    yield session
    session.close()


@pytest.fixture()
def client(db):
    with TestClient(app) as c:
        yield c


class Api:
    """Tiny helper: one logged-in session per demo role."""

    def __init__(self, client, db):
        self.client, self.db, self._tokens = client, db, {}

    def token(self, who):
        if who not in self._tokens:
            r = self.client.post("/api/auth/login", json={"email": EMAILS[who], "password": DEMO_PASSWORD})
            assert r.status_code == 200, r.text
            self._tokens[who] = r.json()["access_token"]
        return {"Authorization": f"Bearer {self._tokens[who]}"}

    def get(self, who, url, **kw):
        return self.client.get(f"/api{url}", headers=self.token(who), **kw)

    def post(self, who, url, json=None):
        return self.client.post(f"/api{url}", headers=self.token(who), json=json if json is not None else {})

    def put(self, who, url, json):
        return self.client.put(f"/api{url}", headers=self.token(who), json=json)

    def pid(self, sku):
        return self.db.query(Product).filter_by(sku=sku).one().id

    def wid(self, code):
        return self.db.query(Warehouse).filter_by(code=code).one().id

    def stock(self, sku, code):
        self.db.expire_all()
        return self.db.query(Inventory).filter_by(product_id=self.pid(sku), warehouse_id=self.wid(code)).one()

    def quote(self, lines, who="rep", customer_id=1, terms=30, title="Test deal"):
        body = {"title": title, "customer_id": customer_id, "payment_terms_days": terms,
                "lines": [{"product_id": self.pid(s), "quantity": q, "discount_percent": d} for s, q, d in lines]}
        r = self.post(who, "/quotations", body)
        assert r.status_code == 201, r.text
        return r.json()

    def to_sent(self, lines, **kw):
        """Create a quote, push it through whatever approvals it needs, then send it."""
        q = self.quote(lines, **kw)
        q = self.post("rep", f"/quotations/{q['id']}/submit").json()
        if q["status"] == "pending_manager":
            q = self.post("manager", f"/quotations/{q['id']}/approve").json()
        if q["status"] == "pending_finance":
            q = self.post("finance", f"/quotations/{q['id']}/approve").json()
        assert q["status"] == "approved", q["status"]
        q = self.post("rep", f"/quotations/{q['id']}/send").json()
        assert q["status"] == "sent" and q["portal_token"]
        return q


@pytest.fixture()
def api(client, db):
    return Api(client, db)
