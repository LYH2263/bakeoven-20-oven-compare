import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SEED_ON_EMPTY"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Batch, Oven, Product

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


def _seed():
    """1 号炉 09:00 已有一炉乡村欧包：发酵 [540,580) 烘烤 [580,615)；2 号炉空。"""
    db = TestingSession()
    try:
        p1 = Product(name="乡村欧包", ferment_min=40, bake_min=35)
        p2 = Product(name="布朗尼", ferment_min=0, bake_min=30)
        o1 = Oven(label="1 号炉")
        o2 = Oven(label="2 号炉")
        db.add_all([p1, p2, o1, o2])
        db.flush()
        db.add(Batch(product_id=p1.id, oven_id=o1.id, code="BO-0900", start_min=540))
        db.commit()
        return p1.id, p2.id, o1.id, o2.id
    finally:
        db.close()


def _batch_count():
    return len(client.get("/api/batches").json())


def test_preview_lists_every_oven_without_writing():
    p1, _, o1, o2 = _seed()
    before = _batch_count()
    gantt_before = client.get("/api/gantt").json()

    r = client.get(f"/api/batches/preview?product_id={p1}&start_min=600")
    assert r.status_code == 200
    ovens = {o["oven_id"]: o for o in r.json()["ovens"]}
    assert set(ovens) == {o1, o2}

    busy = ovens[o1]
    assert busy["available"] is False
    assert busy["ferment_end"] == 640 and busy["bake_end"] == 675
    assert [(c["code"], c["phase"]) for c in busy["conflicts"]] == [("BO-0900", "bake")]
    assert busy["conflicts"][0]["start_min"] == 580
    assert busy["conflicts"][0]["end_min"] == 615

    free = ovens[o2]
    assert free["available"] is True
    assert free["conflicts"] == []
    assert free["ferment_end"] == 640 and free["bake_end"] == 675

    # 预览只读：批次条数与甘特不变
    assert _batch_count() == before
    assert client.get("/api/gantt").json() == gantt_before


def test_preview_touching_endpoint_is_available():
    p1, _, o1, _ = _seed()
    # 既有烘烤段 580–615，新批 615 开工：端点相接不算重叠
    r = client.get(f"/api/batches/preview?product_id={p1}&start_min=615")
    assert r.status_code == 200
    ovens = {o["oven_id"]: o for o in r.json()["ovens"]}
    assert ovens[o1]["available"] is True
    assert ovens[o1]["conflicts"] == []


def test_create_on_free_oven_creates_only_that_oven():
    p1, _, o1, o2 = _seed()
    r = client.post(
        "/api/batches",
        json={"product_id": p1, "oven_id": o2, "start_min": 600},
    )
    assert r.status_code == 200
    created = r.json()
    assert created["oven_id"] == o2
    # 批次页可对照试排时列出的止点
    assert created["ferment_end"] == 640
    assert created["bake_end"] == 675

    assert _batch_count() == 2
    gantt = client.get("/api/gantt").json()
    new_blocks = [b for b in gantt if b["batch_id"] == created["id"]]
    assert new_blocks
    # 其他炉的甘特不出现这批
    assert {b["oven_id"] for b in new_blocks} == {o2}
    assert all(b["oven_id"] == o1 for b in gantt if b["batch_id"] != created["id"])


def test_create_on_overlapping_oven_persists_nothing_and_names_opponent():
    p1, _, o1, _ = _seed()
    before = _batch_count()
    gantt_before = client.get("/api/gantt").json()

    r = client.post(
        "/api/batches",
        json={"product_id": p1, "oven_id": o1, "start_min": 600},
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "BO-0900" in detail
    assert "bake" in detail

    # 整次不落库：批次条数与甘特都不变
    assert _batch_count() == before
    assert client.get("/api/gantt").json() == gantt_before


def test_create_touching_existing_batch_is_accepted():
    p1, _, o1, _ = _seed()
    r = client.post(
        "/api/batches",
        json={"product_id": p1, "oven_id": o1, "start_min": 615},
    )
    assert r.status_code == 200
    assert _batch_count() == 2
