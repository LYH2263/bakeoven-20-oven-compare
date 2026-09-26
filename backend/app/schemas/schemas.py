from datetime import datetime
from pydantic import BaseModel, Field


class ProductOut(BaseModel):
    id: int
    name: str
    ferment_min: int
    bake_min: int
    model_config = {"from_attributes": True}


class OvenOut(BaseModel):
    id: int
    label: str
    capacity_note: str
    model_config = {"from_attributes": True}


class BatchOut(BaseModel):
    id: int
    product_id: int
    oven_id: int
    code: str
    start_min: int
    status: str
    product_name: str | None = None
    oven_label: str | None = None
    ferment_end: int | None = None
    bake_end: int | None = None
    model_config = {"from_attributes": True}


class BatchCreate(BaseModel):
    product_id: int
    oven_id: int
    start_min: int = Field(ge=0, le=24 * 60 - 1)
    code: str | None = None


class PreviewRequest(BaseModel):
    product_id: int
    start_min: int = Field(ge=0, le=24 * 60 - 1)


class ConflictItem(BaseModel):
    # 对手（已占用炉的批次）
    opponent_batch_id: int
    opponent_code: str
    opponent_product_name: str | None = None
    opponent_phase: str  # ferment | bake
    opponent_phase_label: str  # 发酵 | 烘烤
    opponent_start_min: int
    opponent_end_min: int  # 半开
    # 候选（本次试排的本批段）
    candidate_phase: str
    candidate_phase_label: str
    candidate_start_min: int
    candidate_end_min: int


class PreviewOven(BaseModel):
    oven_id: int
    oven_label: str
    ferment_end: int
    bake_end: int
    available: bool  # 半开语义；端点相接为 True
    conflicts: list[ConflictItem] = []


class PreviewOut(BaseModel):
    product_id: int
    product_name: str
    start_min: int
    ovens: list[PreviewOven]


class ConflictReject(BaseModel):
    # POST /batches 创建时撞车的 409 结构化响应体
    detail: str
    oven_id: int
    oven_label: str
    start_min: int
    conflicts: list[ConflictItem]


class GanttBlock(BaseModel):
    batch_id: int
    code: str
    oven_id: int
    oven_label: str
    phase: str
    start_min: int
    end_min: int


class ConflictOut(BaseModel):
    id: int
    batch_code: str
    oven_id: int
    detail: str
    created_at: datetime
    model_config = {"from_attributes": True}


class WindowOut(BaseModel):
    oven_id: int
    oven_label: str
    start_min: int
    end_min: int
    duration_min: int
