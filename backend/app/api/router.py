from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Batch, ConflictLog, Oven, Product
from app.schemas.schemas import (
    BatchCreate,
    BatchOut,
    ConflictItem,
    ConflictOut,
    ConflictReject,
    GanttBlock,
    OvenOut,
    PreviewOut,
    PreviewOven,
    PreviewRequest,
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

PHASE_LABELS = {"ferment": "发酵", "bake": "烘烤"}


def _recipe(p: Product) -> RecipeDurations:
    return RecipeDurations(p.ferment_min, p.bake_min)


def _all_occupancies(db: Session) -> list[Occupancy]:
    batches = db.scalars(select(Batch)).all()
    out: list[Occupancy] = []
    for b in batches:
        p = db.get(Product, b.product_id)
        if not p:
            continue
        out.extend(build_occupancies(b.oven_id, b.id, b.start_min, _recipe(p)))
    return out


def _batch_index(db: Session) -> dict[int, tuple[str, str | None]]:
    """batch_id -> (code, product_name)，供冲突结果补对手信息。"""
    index: dict[int, tuple[str, str | None]] = {}
    for b in db.scalars(select(Batch)).all():
        p = db.get(Product, b.product_id)
        index[b.id] = (b.code, p.name if p else None)
    return index


def _conflict_item(
    ex: Occupancy, cand: Occupancy, index: dict[int, tuple[str, str | None]]
) -> ConflictItem:
    code, pname = index.get(ex.batch_id, (f"#{ex.batch_id}", None))
    return ConflictItem(
        opponent_batch_id=ex.batch_id,
        opponent_code=code,
        opponent_product_name=pname,
        opponent_phase=ex.phase,
        opponent_phase_label=PHASE_LABELS.get(ex.phase, ex.phase),
        opponent_start_min=ex.interval.start,
        opponent_end_min=ex.interval.end,
        candidate_phase=cand.phase,
        candidate_phase_label=PHASE_LABELS.get(cand.phase, cand.phase),
        candidate_start_min=cand.interval.start,
        candidate_end_min=cand.interval.end,
    )


def _dedup_hits(
    hits: list[tuple[Occupancy, Occupancy]],
) -> list[tuple[Occupancy, Occupancy]]:
    """按对手批次/阶段与候选区间保序去重。"""
    seen: set[tuple] = set()
    out: list[tuple[Occupancy, Occupancy]] = []
    for ex, cand in hits:
        key = (
            ex.batch_id,
            ex.phase,
            ex.interval.start,
            ex.interval.end,
            cand.phase,
            cand.interval.start,
            cand.interval.end,
        )
        if key not in seen:
            seen.add(key)
            out.append((ex, cand))
    return out


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


@api_router.post("/batches/preview", response_model=PreviewOut)
def preview_batches(body: PreviewRequest, db: Session = Depends(get_db)):
    product = db.get(Product, body.product_id)
    if not product:
        raise HTTPException(404, "产品不存在")
    recipe = _recipe(product)
    existing = _all_occupancies(db)
    index = _batch_index(db)
    ovens: list[PreviewOven] = []
    for oven in db.scalars(select(Oven).order_by(Oven.id)).all():
        cands = build_occupancies(oven.id, -1, body.start_min, recipe)
        hits = _dedup_hits(find_conflicts(existing, cands))
        ovens.append(
            PreviewOven(
                oven_id=oven.id,
                oven_label=oven.label,
                ferment_end=cands[0].interval.end,
                bake_end=cands[1].interval.end,
                available=not hits,
                conflicts=[_conflict_item(ex, cand, index) for ex, cand in hits],
            )
        )
    return PreviewOut(
        product_id=product.id,
        product_name=product.name,
        start_min=body.start_min,
        ovens=ovens,
    )


@api_router.post("/batches", response_model=BatchOut, responses={409: {"model": ConflictReject}})
def create_batch(body: BatchCreate, db: Session = Depends(get_db)):
    product = db.get(Product, body.product_id)
    oven = db.get(Oven, body.oven_id)
    if not product or not oven:
        raise HTTPException(404, "产品或炉位不存在")
    recipe = _recipe(product)
    candidates = build_occupancies(oven.id, -1, body.start_min, recipe)
    existing = _all_occupancies(db)
    hits = _dedup_hits(find_conflicts(existing, candidates))
    if hits:
        index = _batch_index(db)
        reject = ConflictReject(
            detail="提交时炉位已被占用，本批未保存，请重新试排",
            oven_id=oven.id,
            oven_label=oven.label,
            start_min=body.start_min,
            conflicts=[_conflict_item(ex, cand, index) for ex, cand in hits],
        )
        return JSONResponse(status_code=409, content=reject.model_dump())
    code = body.code or f"BO-{body.start_min}"
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
