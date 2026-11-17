from pathlib import Path

from sqlalchemy.engine import make_url


def get_database_connect_args(database_url: str) -> dict[str, object]:
    database_host = make_url(database_url).host
    if (
        not database_host
        or not database_host.lower().endswith(".tidbcloud.com")
    ):
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
