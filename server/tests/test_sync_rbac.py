"""Integration tests for Sync RBAC using two ordinary ADMIN accounts.

Required environment:
  TEST_ADMIN_A_EMAIL, TEST_ADMIN_A_PASSWORD
  TEST_ADMIN_B_EMAIL, TEST_ADMIN_B_PASSWORD
  TEST_ADMIN_A_ID, TEST_ADMIN_B_ID

Run against an isolated test API/database only. These tests create persistent
records through HTTP; use a disposable database or clean up test data afterward.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.api


def _login(api, v1, email, password):
    response = api.post(
        f"{v1}/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )
    assert response.status_code == 200, (
        f"Login {email} failed: HTTP {response.status_code}: {response.text[:300]}"
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def rbac_users(api, v1):
    keys = [
        "TEST_ADMIN_A_EMAIL", "TEST_ADMIN_A_PASSWORD", "TEST_ADMIN_A_ID",
        "TEST_ADMIN_B_EMAIL", "TEST_ADMIN_B_PASSWORD", "TEST_ADMIN_B_ID",
    ]
    missing = [key for key in keys if not os.getenv(key)]
    if missing:
        pytest.skip("Missing RBAC test environment: " + ", ".join(missing))
    return {
        "a": {
            "id": os.environ["TEST_ADMIN_A_ID"],
            "headers": _login(api, v1, os.environ["TEST_ADMIN_A_EMAIL"], os.environ["TEST_ADMIN_A_PASSWORD"]),
        },
        "b": {
            "id": os.environ["TEST_ADMIN_B_ID"],
            "headers": _login(api, v1, os.environ["TEST_ADMIN_B_EMAIL"], os.environ["TEST_ADMIN_B_PASSWORD"]),
        },
    }


@pytest.fixture(scope="module")
def rbac_subjects(api, v1, rbac_users):
    """Create one owned subject per ADMIN via the public sync API."""
    result = {}
    for who in ("a", "b"):
        user = rbac_users[who]
        subject_id = f"RBAC_{who.upper()}_{uuid.uuid4().hex[:12].upper()}"
        subject_uuid = str(uuid.uuid4())
        response = api.post(
            f"{v1}/sync/push",
            headers=user["headers"],
            json={"subjects": [{
                "subject_id": subject_id,
                "subject_name": f"RBAC subject {who}",
                "instructor_id": user["id"],
                "created_by": user["id"],
                "uuid": subject_uuid,
            }]},
            timeout=10,
        )
        assert response.status_code == 200, (
            f"Cannot create subject {who}: HTTP {response.status_code}: {response.text[:500]}"
        )
        assert response.json()["applied"]["subjects"] == 1
        result[who] = {"id": subject_id, "uuid": subject_uuid}
    return result


def _all_pull_records(api, v1, headers, table_name):
    """Read every page, avoiding assumptions about the global seq size."""
    after_seq = 0
    records = []
    for _ in range(1000):
        response = api.get(
            f"{v1}/sync/pull",
            headers=headers,
            params={"after_seq": after_seq, "limit": 500},
            timeout=15,
        )
        assert response.status_code == 200, response.text[:500]
        body = response.json()
        records.extend(body["changes"].get(table_name, []))
        if not body.get("has_more"):
            return records
        next_seq = body.get("next_seq", after_seq)
        assert next_seq > after_seq, "Sync pagination did not advance"
        after_seq = next_seq

    pytest.fail("Too many Sync/Pull pages")


def _pull_subject_ids(api, v1, headers):
    rows = _all_pull_records(api, v1, headers, "subjects")
    return {row["subject_id"] for row in rows}


def test_admin_a_sees_own_subject(api, v1, rbac_users, rbac_subjects):
    ids = _pull_subject_ids(api, v1, rbac_users["a"]["headers"])
    assert rbac_subjects["a"]["id"] in ids


def test_admin_b_sees_own_subject(api, v1, rbac_users, rbac_subjects):
    ids = _pull_subject_ids(api, v1, rbac_users["b"]["headers"])
    assert rbac_subjects["b"]["id"] in ids


def test_admin_a_cannot_pull_b_subject(api, v1, rbac_users, rbac_subjects):
    ids = _pull_subject_ids(api, v1, rbac_users["a"]["headers"])
    assert rbac_subjects["b"]["id"] not in ids


def test_admin_b_cannot_pull_a_subject(api, v1, rbac_users, rbac_subjects):
    ids = _pull_subject_ids(api, v1, rbac_users["b"]["headers"])
    assert rbac_subjects["a"]["id"] not in ids


def _attempt_foreign_subject_update(api, v1, actor, target):
    response = api.post(
        f"{v1}/sync/push",
        headers=actor["headers"],
        json={
            "subjects": [{
                "subject_id": target["id"],
                "uuid": target["uuid"],
                "subject_name": "UNAUTHORIZED_RBAC_CHANGE",
                "updated_at": "2099-01-01T00:00:00Z",
            }]
        },
        timeout=10,
    )
    return response



def _pull_subject_ids(api, v1, headers):
    rows = _all_pull_records(api, v1, headers, "subjects")
    return {row["subject_id"] for row in rows}


def test_admin_a_sees_own_subject(api, v1, rbac_users, rbac_subjects):
    ids = _pull_subject_ids(api, v1, rbac_users["a"]["headers"])
    assert rbac_subjects["a"]["id"] in ids


def test_admin_b_sees_own_subject(api, v1, rbac_users, rbac_subjects):
    ids = _pull_subject_ids(api, v1, rbac_users["b"]["headers"])
    assert rbac_subjects["b"]["id"] in ids


def test_admin_a_cannot_pull_b_subject(api, v1, rbac_users, rbac_subjects):
    ids = _pull_subject_ids(api, v1, rbac_users["a"]["headers"])
    assert rbac_subjects["b"]["id"] not in ids


def test_admin_b_cannot_pull_a_subject(api, v1, rbac_users, rbac_subjects):
    ids = _pull_subject_ids(api, v1, rbac_users["b"]["headers"])
    assert rbac_subjects["a"]["id"] not in ids


def _attempt_foreign_subject_update(api, v1, actor, target):
    response = api.post(
        f"{v1}/sync/push",
        headers=actor["headers"],
        json={
            "subjects": [{
                "subject_id": target["id"],
                "uuid": target["uuid"],
                "subject_name": "UNAUTHORIZED_RBAC_CHANGE",
                "updated_at": "2099-01-01T00:00:00Z",
            }]
        },
        timeout=10,
    )
    return response



def _pull_subject_ids(api, v1, headers):
    rows = _all_pull_records(api, v1, headers, "subjects")
    return {row["subject_id"] for row in rows}


def test_admin_a_sees_own_subject(api, v1, rbac_users, rbac_subjects):
    ids = _pull_subject_ids(api, v1, rbac_users["a"]["headers"])
    assert rbac_subjects["a"]["id"] in ids


def test_admin_b_sees_own_subject(api, v1, rbac_users, rbac_subjects):
    ids = _pull_subject_ids(api, v1, rbac_users["b"]["headers"])
    assert rbac_subjects["b"]["id"] in ids


def test_admin_a_cannot_pull_b_subject(api, v1, rbac_users, rbac_subjects):
    ids = _pull_subject_ids(api, v1, rbac_users["a"]["headers"])
    assert rbac_subjects["b"]["id"] not in ids


def test_admin_b_cannot_pull_a_subject(api, v1, rbac_users, rbac_subjects):
    ids = _pull_subject_ids(api, v1, rbac_users["b"]["headers"])
    assert rbac_subjects["a"]["id"] not in ids


def _attempt_foreign_subject_update(api, v1, actor, target):
    response = api.post(
        f"{v1}/sync/push",
        headers=actor["headers"],
        json={
            "subjects": [{
                "subject_id": target["id"],
                "uuid": target["uuid"],
                "subject_name": "UNAUTHORIZED_RBAC_CHANGE",
                "updated_at": "2099-01-01T00:00:00Z",
            }]
        },
        timeout=10,
    )
    return response


def test_admin_a_cannot_modify_b_subject(api, v1, rbac_users, rbac_subjects):
    response = _attempt_foreign_subject_update(
        api, v1, rbac_users["a"], rbac_subjects["b"]
    )
    assert response.status_code == 403, response.text[:500]


def test_admin_b_cannot_modify_a_subject(api, v1, rbac_users, rbac_subjects):
    response = _attempt_foreign_subject_update(
        api, v1, rbac_users["b"], rbac_subjects["a"]
    )
    assert response.status_code == 403, response.text[:500]


