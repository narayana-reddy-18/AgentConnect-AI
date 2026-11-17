from pathlib import Path

from app.db.session import _get_connect_args


def test_tidb_cloud_connection_uses_verified_ca_certificate():
    certificate_path = Path(__file__).resolve().parents[1] / "isrgrootx1.pem"
    database_url = (
        "mysql+pymysql://gateway01.region.prod.aws.tidbcloud.com:4000/"
        "agentconnect_db"
    )

    assert certificate_path.is_file()
    assert _get_connect_args(database_url) == {
        "ssl_ca": str(certificate_path),
        "ssl_verify_cert": True,
        "ssl_verify_identity": True,
    }


def test_local_mysql_connection_does_not_require_tls():
    assert (
        _get_connect_args("mysql+pymysql://127.0.0.1/agentconnect_db")
        == {}
    )
