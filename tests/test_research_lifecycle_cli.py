from hypertrade.cli import _build_parser
from hypertrade.research_cli import research_request


def request(*args):
    return research_request(_build_parser().parse_args(["research", *args]))


def test_cli_start_targets_same_arc_service():
    method, path, body, headers = request("start", "研究趋势", "--symbol", "ETH-USDT-SWAP")
    assert (method, path) == ("POST", "/api/v1/arc/missions")
    assert body["objective"] == "研究趋势"
    assert body["symbols"] == ["ETH-USDT-SWAP"]
    assert "paper_preauth_approved" not in body


def test_cli_review_is_read_only():
    method, path, body, headers = request("review", "arc_1")
    assert method == "GET"
    assert path == "/api/v1/arc/missions/arc_1/paper-review"


def test_cli_approval_binds_review_hash_and_retry_key():
    digest = "a" * 64
    first = request(
        "decide", "arc_1", "--decision", "approve", "--reason", "reviewed", "--package-hash", digest
    )
    second = request(
        "decide", "arc_1", "--decision", "approve", "--reason", "reviewed", "--package-hash", digest
    )
    assert first == second
    assert first[1] == "/api/v1/arc/missions/arc_1/paper-review/decide"
    assert first[2]["package_hash"] == digest
    assert first[3]["Idempotency-Key"]


def test_cli_scope_is_optional_and_repeatable():
    assert request("start", "研究趋势")[2]["symbols"] == []
    assert request("start", "研究趋势", "--symbol", "SOL", "--symbol", "DOGE")[2]["symbols"] == [
        "SOL",
        "DOGE",
    ]
