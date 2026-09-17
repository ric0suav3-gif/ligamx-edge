from nfl.ingest.api_sports import APINFLClient


def test_provider_errors_dict() -> None:
    errors = APINFLClient._provider_errors({"errors": {"game": "invalid"}})
    assert errors == ["game: invalid"]


def test_provider_errors_list() -> None:
    errors = APINFLClient._provider_errors({"errors": ["a", "b"]})
    assert errors == ["a", "b"]


def test_provider_errors_empty() -> None:
    assert APINFLClient._provider_errors({"errors": []}) == []
