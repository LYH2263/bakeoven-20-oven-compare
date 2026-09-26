from sqlalchemy import func, select

from app.models.models import Batch, ConflictLog


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def preview(client, start_min: int, product_id: int = 1):
    return client.post(
        "/batches/preview", json={"product_id": product_id, "start_min": start_min}
    )


def oven_by_id(payload, oven_id: int):
    return next(o for o in payload["ovens"] if o["oven_id"] == oven_id)


def test_preview_overlap_lists_opponent_and_phases(client):
    r = preview(client, 660)
    assert r.status_code == 200
    o1 = oven_by_id(r.json(), 1)
    assert o1["available"] is False
    assert len(o1["conflicts"]) == 1
    c = o1["conflicts"][0]
    assert c["opponent_code"] == "BO-1030"
    assert c["opponent_product_name"] == "黄油可颂"
    assert c["opponent_phase"] == "bake"
    assert c["opponent_phase_label"] == "烘烤"
    assert (c["opponent_start_min"], c["opponent_end_min"]) == (655, 675)
    assert c["candidate_phase"] == "ferment"
    assert c["candidate_phase_label"] == "发酵"
    assert (c["candidate_start_min"], c["candidate_end_min"]) == (660, 700)


def test_preview_endpoint_touch_is_available(client):
    r = preview(client, 675)
    o1 = oven_by_id(r.json(), 1)
    assert o1["available"] is True
    assert o1["conflicts"] == []


def test_preview_free_ovens_available(client):
    o = preview(client, 660).json()["ovens"]
    for oven_id in (2, 3):
        row = oven_by_id({"ovens": o}, oven_id)
        assert row["available"] is True
        assert row["conflicts"] == []


def test_preview_endpoints_consistent(client):
    data = preview(client, 660).json()
    assert [o["oven_id"] for o in data["ovens"]] == [1, 2, 3]
    assert data["product_name"] == "乡村欧包"
    assert data["start_min"] == 660
    for o in data["ovens"]:
        assert o["ferment_end"] == 700
        assert o["bake_end"] == 735


def test_preview_does_not_write(client, db_session):
    batches_before = count(db_session, Batch)
    logs_before = count(db_session, ConflictLog)
    for start_min in (660, 675, 700):
        assert preview(client, start_min).status_code == 200
    assert count(db_session, Batch) == batches_before
    assert count(db_session, ConflictLog) == logs_before


def test_create_overlap_409_persists_nothing(client, db_session):
    batches_before = count(db_session, Batch)
    logs_before = count(db_session, ConflictLog)
    r = client.post(
        "/batches", json={"product_id": 1, "oven_id": 1, "start_min": 660}
    )
    assert r.status_code == 409
    body = r.json()
    assert body["oven_id"] == 1
    assert body["oven_label"] == "一层 1 号炉"
    assert body["conflicts"][0]["opponent_code"] == "BO-1030"
    assert "detail" in body and body["detail"]
    assert count(db_session, Batch) == batches_before
    assert count(db_session, ConflictLog) == logs_before


def test_create_success_only_one_oven(client, db_session):
    batches_before = count(db_session, Batch)
    r = client.post(
        "/batches", json={"product_id": 1, "oven_id": 3, "start_min": 660}
    )
    assert r.status_code == 200
    b = r.json()
    assert b["oven_id"] == 3
    assert b["ferment_end"] == 700
    assert b["bake_end"] == 735
    assert count(db_session, Batch) == batches_before + 1

    g = client.get("/gantt").json()
    new_blocks = [blk for blk in g if blk["code"] == b["code"]]
    assert len(new_blocks) == 2
    assert {blk["oven_id"] for blk in new_blocks} == {3}
    phases = sorted(blk["phase"] for blk in new_blocks)
    assert phases == ["bake", "ferment"]


def test_create_404_for_missing_product_or_oven(client):
    r = client.post("/batches", json={"product_id": 999, "oven_id": 1, "start_min": 660})
    assert r.status_code == 404
    r = client.post("/batches", json={"product_id": 1, "oven_id": 999, "start_min": 660})
    assert r.status_code == 404
    r = preview(client, 660, product_id=999)
    assert r.status_code == 404
