import io
import time
import pytest

pytestmark = pytest.mark.api

# GIẢ ĐỊNH cột CSV theo bảng student (student_id, full_name, class_name).
# Kế hoạch nói import có 3 loại (Sinh viên, Môn học, Giảng viên); cách chọn loại
# (field "type"?) chưa rõ, cần Người 2 xác nhận.
VALID_CSV = (
    "student_id,full_name,class_name\n"
    "TEST0001,Nguyen Van A,CLS01\n"
    "TEST0002,Tran Thi B,CLS01\n"
)


def _upload(api, v1, content, name="students.csv"):
    return api.post(
        f"{v1}/import/csv",
        files={"file": (name, io.BytesIO(content.encode("utf-8")), "text/csv")},
        timeout=10,
    )


def test_import_without_file_returns_400(api, v1):
    r = api.post(f"{v1}/import/csv", timeout=5)
    assert r.status_code == 400


def test_import_returns_202_and_job_id(api, v1):
    r = _upload(api, v1, VALID_CSV)
    assert r.status_code == 202
    assert "job_id" in r.json()


def test_job_reaches_terminal_state(api, v1):
    r = _upload(api, v1, VALID_CSV)
    assert r.status_code == 202, f"Upload thất bại: HTTP {r.status_code}"
    job_id = r.json()["job_id"]
    status = None
    for _ in range(30):  # chờ tối đa ~30s
        r = api.get(f"{v1}/jobs/{job_id}", timeout=5)
        assert r.status_code == 200
        status = r.json().get("status")
        if status in ("finished", "failed"):
            break
        time.sleep(1)
    assert status == "finished", f"Job kết thúc với trạng thái: {status}"


def test_unknown_job_returns_404_in_standard_error_format(api, v1):
    r = api.get(f"{v1}/jobs/does-not-exist-123", timeout=5)
    assert r.status_code == 404
    assert "application/json" in r.headers.get("Content-Type", ""), \
        "404 nên trả JSON, hiện là trang HTML mặc định (route có thể chưa tồn tại)"
    # Kế hoạch: định dạng lỗi thống nhất {"error": {"code", "message"}}
    err = r.json().get("error", {})
    assert "code" in err and "message" in err
