from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Batch, ConflictLog, Oven, Product
from app.schemas.schemas import (
    BatchCreate,
    BatchOut,
    ConflictOut,
    GanttBlock,
    OvenOut,
    OvenPreview,
    PreviewConflict,
    PreviewOut,
    ProductOut,
    WindowOut,
)
from app.services.oven_engine import (
    Occupancy,
    RecipeDurations,
    build_occupancies,
    find_conflicts,
    next_free_window,
)

api_router = APIRouter()


def _recipe(p: Product) -> RecipeDurations:
    return RecipeDurations(p.ferment_min, p.bake_min)


def _load_occupancies(db: Session) -> tuple[list[Occupancy], dict[int, Batch]]:
    batches = db.scalars(select(Batch)).all()
    by_id = {b.id: b for b in batches}
    out: list[Occupancy] = []
    for b in batches:
        p = db.get(Product, b.product_id)
        if not p:
            continue
        out.extend(build_occupancies(b.oven_id, b.id, b.start_min, _recipe(p)))
    return out, by_id


def _all_occupancies(db: Session) -> list[Occupancy]:
    return _load_occupancies(db)[0]


def _batch_out(db: Session, b: Batch) -> BatchOut:
    p = db.get(Product, b.product_id)
    o = db.get(Oven, b.oven_id)
    ferment_end = b.start_min + (p.ferment_min if p else 0)
    bake_end = ferment_end + (p.bake_min if p else 0)
    return BatchOut(
        id=b.id,
        product_id=b.product_id,
        oven_id=b.oven_id,
        code=b.code,
        start_min=b.start_min,
        status=b.status,
        product_name=p.name if p else None,
        oven_label=o.label if o else None,
        ferment_end=ferment_end,
        bake_end=bake_end,
    )


@api_router.get("/health")
def health():
    return {"status": "ok"}


@api_router.get("/products", response_model=list[ProductOut])
def products(db: Session = Depends(get_db)):
    return db.scalars(select(Product).order_by(Product.id)).all()


@api_router.get("/ovens", response_model=list[OvenOut])
def ovens(db: Session = Depends(get_db)):
    return db.scalars(select(Oven).order_by(Oven.id)).all()


@api_router.get("/batches", response_model=list[BatchOut])
def batches(db: Session = Depends(get_db)):
    rows = db.scalars(select(Batch).order_by(Batch.start_min)).all()
    return [_batch_out(db, b) for b in rows]


@api_router.get("/batches/preview", response_model=PreviewOut)
def preview_batches(
    product_id: int,
    start_min: int = Query(ge=0, le=24 * 60 - 1),
    db: Session = Depends(get_db),
):
    """试排：对每座炉算出发酵止/烘烤止与冲突对手，只读不落库。"""
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "产品不存在")
    recipe = _recipe(product)
    existing, batches_by_id = _load_occupancies(db)
    ovens_out: list[OvenPreview] = []
    for oven in db.scalars(select(Oven).order_by(Oven.id)).all():
        candidates = build_occupancies(oven.id, -1, start_min, recipe)
        hits = find_conflicts(existing, candidates)
        conflicts: list[PreviewConflict] = []
        seen: set[tuple[int, str]] = set()
        for ex, _ in hits:
            key = (ex.batch_id, ex.phase)
            if key in seen:
                continue
            seen.add(key)
            opponent = batches_by_id.get(ex.batch_id)
            conflicts.append(
                PreviewConflict(
                    batch_id=ex.batch_id,
                    code=opponent.code if opponent else f"#{ex.batch_id}",
                    phase=ex.phase,
                    start_min=ex.interval.start,
                    end_min=ex.interval.end,
                )
            )
        ovens_out.append(
            OvenPreview(
                oven_id=oven.id,
                oven_label=oven.label,
                ferment_end=start_min + recipe.ferment_min,
                bake_end=start_min + recipe.total,
                available=not conflicts,
                conflicts=conflicts,
            )
        )
    return PreviewOut(product_id=product.id, start_min=start_min, ovens=ovens_out)


@api_router.post("/batches", response_model=BatchOut)
def create_batch(body: BatchCreate, db: Session = Depends(get_db)):
    product = db.get(Product, body.product_id)
    oven = db.get(Oven, body.oven_id)
    if not product or not oven:
        raise HTTPException(404, "产品或炉位不存在")
    recipe = _recipe(product)
    candidates = build_occupancies(oven.id, -1, body.start_min, recipe)
    existing, batches_by_id = _load_occupancies(db)
    hits = find_conflicts(existing, candidates)
    code = body.code or f"BO-{body.start_min}"
    if hits:
        ex, cand = hits[0]
        opponent = batches_by_id.get(ex.batch_id)
        opponent_code = opponent.code if opponent else f"#{ex.batch_id}"
        detail = (
            f"与批次 {opponent_code}(#{ex.batch_id}) 的 {ex.phase} 段重叠："
            f"[{cand.interval.start},{cand.interval.end})"
        )
        db.add(ConflictLog(batch_code=code, oven_id=oven.id, detail=detail))
        db.commit()
        raise HTTPException(409, detail)
    batch = Batch(
        product_id=product.id,
        oven_id=oven.id,
        code=code,
        start_min=body.start_min,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return _batch_out(db, batch)


@api_router.get("/gantt", response_model=list[GanttBlock])
def gantt(db: Session = Depends(get_db)):
    blocks: list[GanttBlock] = []
    for b in db.scalars(select(Batch).order_by(Batch.start_min)).all():
        p = db.get(Product, b.product_id)
        o = db.get(Oven, b.oven_id)
        if not p or not o:
            continue
        for occ in build_occupancies(b.oven_id, b.id, b.start_min, _recipe(p)):
            blocks.append(
                GanttBlock(
                    batch_id=b.id,
                    code=b.code,
                    oven_id=o.id,
                    oven_label=o.label,
                    phase=occ.phase,
                    start_min=occ.interval.start,
                    end_min=occ.interval.end,
                )
            )
    return blocks


@api_router.get("/conflicts", response_model=list[ConflictOut])
def conflicts(db: Session = Depends(get_db)):
    return db.scalars(select(ConflictLog).order_by(ConflictLog.id.desc())).all()


@api_router.get("/windows", response_model=list[WindowOut])
def windows(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "产品不存在")
    duration = product.ferment_min + product.bake_min
    existing = _all_occupancies(db)
    out: list[WindowOut] = []
    for oven in db.scalars(select(Oven).order_by(Oven.id)).all():
        w = next_free_window(existing, oven.id, duration, search_from=8 * 60, search_to=22 * 60)
        if w:
            out.append(
                WindowOut(
                    oven_id=oven.id,
                    oven_label=oven.label,
                    start_min=w.start,
                    end_min=w.end,
                    duration_min=duration,
                )
            )
    return out
