import io
import time
import pytest

pytestmark = pytest.mark.api

# GIáº¢ Äá»ŠNH cá»™t CSV theo báº£ng student (student_id, full_name, class_name).
# Káº¿ hoáº¡ch nÃ³i import cÃ³ 3 loáº¡i (Sinh viÃªn, MÃ´n há»c, Giáº£ng viÃªn); cÃ¡ch chá»n loáº¡i chÆ°a rÃµ.
VALID_CSV = (
    "student_id,full_name,class_name\n"
    "TEST0001,Nguyen Van A,CLS01\n"
    "TEST0002,Tran Thi B,CLS01\n"
)


def _upload(api, v1, content, headers, name="students.csv"):
    return api.post(
        f"{v1}/import/csv",
        files={"file": (name, io.BytesIO(content.encode("utf-8")), "text/csv")},
        headers=headers,
        timeout=10,
    )


def test_import_without_file_returns_400(api, v1, auth):
    r = api.post(f"{v1}/import/csv", headers=auth, timeout=5)
    assert r.status_code == 400


def test_import_returns_202_and_job_id(api, v1, auth):
    r = _upload(api, v1, VALID_CSV, auth)
    assert r.status_code == 202
    assert "job_id" in r.json()


def test_job_reaches_terminal_state(api, v1, auth):
    r = _upload(api, v1, VALID_CSV, auth)
    assert r.status_code == 202, f"Upload tháº¥t báº¡i: HTTP {r.status_code}"
    job_id = r.json()["job_id"]
    status = None
    for _ in range(30):  # chá» tá»‘i Ä‘a ~30s
        r = api.get(f"{v1}/jobs/{job_id}", headers=auth, timeout=5)
        assert r.status_code == 200
        status = r.json().get("status")
        if status in ("finished", "failed"):
            break
        time.sleep(1)
    assert status == "finished", f"Job káº¿t thÃºc vá»›i tráº¡ng thÃ¡i: {status}"


def test_unknown_job_returns_404_in_standard_error_format(api, v1, auth):
    r = api.get(f"{v1}/jobs/does-not-exist-123", headers=auth, timeout=5)
    assert r.status_code == 404
    assert "application/json" in r.headers.get("Content-Type", ""), \
        "404 nÃªn tráº£ JSON, hiá»‡n lÃ  trang HTML máº·c Ä‘á»‹nh (route cÃ³ thá»ƒ chÆ°a tá»“n táº¡i)"
    err = r.json().get("error", {})
    assert "code" in err and "message" in err

