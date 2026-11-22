import pytest

from types import SimpleNamespace

from app.repositories.sync_repository import SyncRepository

from app.repositories.sync_repository import _validate_embedding


def test_valid_embedding():
    result = _validate_embedding([0.1] * 192)

    assert len(result) == 192
    assert all(value == 0.1 for value in result)


@pytest.mark.parametrize("embedding", [
    [0.1] * 191,
    [0.1] * 193,
    [float("nan")] * 192,
    [float("inf")] * 192,
    [float("-inf")] * 192,
    [True] * 192,
    ["invalid"] * 192,
    "invalid",
])
def test_invalid_embedding(embedding):
    with pytest.raises(ValueError):
        _validate_embedding(embedding)


def test_nullable_embedding():
    assert _validate_embedding(None) is None

@pytest.mark.parametrize("value", [
    "123456",
    "",
    123456,
    True,
    [],
    {},
])
def test_checkin_password_rejects_invalid_input(value):
    student = SimpleNamespace(student_id="TEST001")

    with pytest.raises(ValueError, match="checkin_password"):
        SyncRepository._apply_fields(
            "students",
            student,
            {
                "student_id": "TEST001",
                "checkin_password": value,
            },
            incoming_updated_at=None,
            incoming_deleted_at=None,
            is_new=False,
        )