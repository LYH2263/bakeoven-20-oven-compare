import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Batch, ConflictLog, Oven, Product


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    p1 = Product(name="乡村欧包", ferment_min=40, bake_min=35)
    p2 = Product(name="黄油可颂", ferment_min=25, bake_min=20)
    p3 = Product(name="布朗尼", ferment_min=0, bake_min=30)
    o1 = Oven(label="一层 1 号炉", capacity_note="")
    o2 = Oven(label="一层 2 号炉", capacity_note="")
    o3 = Oven(label="二层石板炉", capacity_note="")
    db.add_all([p1, p2, p3, o1, o2, o3])
    db.flush()
    db.add_all([
        Batch(product_id=p1.id, oven_id=o1.id, code="BO-0900", start_min=540),
        Batch(product_id=p2.id, oven_id=o1.id, code="BO-1030", start_min=630),
        Batch(product_id=p3.id, oven_id=o2.id, code="BO-1000", start_min=600),
    ])
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass  # 会话随测试结束统一关闭

    app.dependency_overrides[get_db] = override_get_db
    yield db
    app.dependency_overrides.clear()
    db.close()


@pytest.fixture()
def client(db_session):
    return TestClient(app)
