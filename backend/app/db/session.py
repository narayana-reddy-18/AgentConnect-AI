from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def _get_connect_args(database_url: str) -> dict[str, object]:
    database_host = make_url(database_url).host
    if not database_host or not database_host.lower().endswith(".tidbcloud.com"):
        return {}

    ca_certificate = Path(__file__).resolve().parents[2] / "isrgrootx1.pem"
    if not ca_certificate.is_file():
        raise FileNotFoundError(
            f"TiDB Cloud CA certificate not found: {ca_certificate}"
        )

    return {
        "ssl_ca": str(ca_certificate),
        "ssl_verify_cert": True,
        "ssl_verify_identity": True,
    }


database_url = settings.database_url.get_secret_value()
engine = create_engine(
    database_url,
    connect_args=_get_connect_args(database_url),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
