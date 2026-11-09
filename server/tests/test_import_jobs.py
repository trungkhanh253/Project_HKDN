import io
import time
import pytest

pytestmark = pytest.mark.api

# GIẢ ĐỊNH tên cột CSV theo bảng student (student_id, full_name, class_name);
# sửa lại cho khớp với Người 2 (nhóm Server) khi có API import thật
VALID_CSV = (
    "student_id,full_name,class_name\n"
    "TEST0001,Nguyen Van A,CLS01\n"
    "TEST0002,Tran Thi B,CLS01\n"
)


def _upload(api, base_url, content, name="students.csv"):
    return api.post(
        f"{base_url}/import/csv",
        files={"file": (name, io.BytesIO(content.encode("utf-8")), "text/csv")},
        timeout=10,
    )


def test_import_without_file_returns_400(api, base_url):
    r = api.post(f"{base_url}/import/csv", timeout=5)
    assert r.status_code == 400


def test_import_returns_202_and_job_id(api, base_url):
    r = _upload(api, base_url, VALID_CSV)
    assert r.status_code == 202
    assert "job_id" in r.json()


def test_job_reaches_terminal_state(api, base_url):
    r = _upload(api, base_url, VALID_CSV)
    assert r.status_code == 202, f"Upload thất bại: HTTP {r.status_code}"
    job_id = r.json()["job_id"]
    status = None
    for _ in range(30):  # chờ tối đa ~30s
        r = api.get(f"{base_url}/jobs/{job_id}", timeout=5)
        assert r.status_code == 200
        status = r.json().get("status")
        if status in ("finished", "failed"):
            break
        time.sleep(1)
    assert status == "finished", f"Job kết thúc với trạng thái: {status}"


def test_unknown_job_returns_404(api, base_url):
    r = api.get(f"{base_url}/jobs/does-not-exist-123", timeout=5)
    assert r.status_code == 404
    # 404 mặc định của Flask là HTML; API đúng nghĩa phải trả JSON (giả định, trao đổi với Người 2)
    assert "application/json" in r.headers.get("Content-Type", ""), \
        "404 nên trả JSON, hiện đang là trang HTML mặc định (route có thể chưa tồn tại)"
