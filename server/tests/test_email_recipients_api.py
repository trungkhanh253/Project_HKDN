"""TV7 - Kiểm thử 5 API email báo cáo của môn học (Web).

  GET    /subjects/{subject_id}/email-recipients
  POST   /subjects/{subject_id}/email-recipients
  PUT    /subjects/{subject_id}/email-recipients/{email_id}
  DELETE /subjects/{subject_id}/email-recipients/{email_id}
  POST   /subjects/{subject_id}/send-report

Đặt vào server/tests/. Dùng fixture `api`, `v1` có sẵn trong conftest.py (như test_web_api.py).

CÁCH CHẠY (PowerShell, từ thư mục server):
    python -m pytest tests/test_email_recipients_api.py -q

BIẾN MÔI TRƯỜNG (đều tùy chọn):
    TEST_SUBJECT_ID          môn do LECTURER phụ trách (mặc định MH090)
    TEST_FOREIGN_SUBJECT_ID  môn của giảng viên KHÁC, để thử ADMIN bị chặn (không đặt thì test tự bỏ qua)
    RUN_SEND_REPORT=1        chạy ca gửi báo cáo thật (có thể gửi mail / đưa job vào worker); mặc định bỏ qua

Mỗi test tự tạo người nhận với email ngẫu nhiên dạng zt-xxxx@example.com và tự xóa sau khi xong,
nên chạy lại nhiều lần không để rác.

Mã HTTP theo hợp đồng trong openapi.yml: tạo 201, sửa 200, xóa 204, trùng email 409, sai dữ liệu 422,
send-report 202 kèm job_id, ADMIN sai quyền 403. Nếu server khác hợp đồng thì test đỏ: hoặc sửa server, hoặc sửa openapi.yml.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.api

SUPER_ADMIN = ("admin@hkdn.edu.vn", "admin123")
LECTURER = ("lecturer@hkdn.edu.vn", "lecturer123")
SUBJECT_ID = os.getenv("TEST_SUBJECT_ID", "MH090")
FOREIGN_SUBJECT_ID = os.getenv("TEST_FOREIGN_SUBJECT_ID")
MISSING_SUBJECT = "KHONG_TON_TAI_" + uuid.uuid4().hex[:6]

CREATED = (201,)           # POST tạo mới
UPDATED = (200,)           # PUT
DELETED = (204,)           # DELETE
BAD_INPUT = (400, 422)     # dữ liệu sai
ACCEPTED = (202,)           # send-report chạy nền, trả job_id


# ---------- tiện ích ----------
def _token(api, v1, creds):
    r = api.post(f"{v1}/auth/login", json={"email": creds[0], "password": creds[1]}, timeout=10)
    if r.status_code != 200:
        pytest.skip(f"Chưa đăng nhập được {creds[0]} (chạy seed_admin.py)")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def boss(api, v1):
    return _token(api, v1, SUPER_ADMIN)


@pytest.fixture(scope="module")
def lecturer(api, v1):
    return _token(api, v1, LECTURER)


def _url(v1, subject_id=SUBJECT_ID, email_id=None):
    base = f"{v1}/subjects/{subject_id}/email-recipients"
    return f"{base}/{email_id}" if email_id is not None else base


def _items(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in ("items", "data", "results", "recipients"):
            if isinstance(body.get(k), list):
                return body[k]
    return None


def _obj(body):
    """Bản ghi có thể được trả thẳng hoặc bọc trong data/item/recipient."""
    if isinstance(body, dict):
        for k in ("data", "item", "recipient"):
            if isinstance(body.get(k), dict):
                return body[k]
    return body


def _new_email():
    return f"zt-{uuid.uuid4().hex[:8]}@example.com"


def _create(api, v1, headers, email=None, name="ZT Nguoi nhan", subject_id=SUBJECT_ID):
    payload = {"email_address": email or _new_email(), "recipient_name": name}
    r = api.post(_url(v1, subject_id), headers=headers, json=payload, timeout=15)
    return r, payload


@pytest.fixture
def recipient(api, v1, boss):
    """Tạo một người nhận, trả về bản ghi (có email_id), tự xóa sau test."""
    r, payload = _create(api, v1, boss)
    assert r.status_code in CREATED, f"Tạo người nhận thất bại: HTTP {r.status_code} {r.text[:200]}"
    rec = _obj(r.json())
    assert rec.get("email_id") is not None, f"Phản hồi tạo không có email_id: {rec}"
    yield rec
    api.delete(_url(v1, SUBJECT_ID, rec["email_id"]), headers=boss, timeout=15)


# ---------- 401: thiếu / sai token ----------
@pytest.mark.parametrize("method,suffix", [
    ("GET", "email-recipients"),
    ("POST", "email-recipients"),
    ("PUT", "email-recipients/1"),
    ("DELETE", "email-recipients/1"),
    ("POST", "send-report"),
])
def test_without_token_is_401(api, v1, method, suffix):
    r = api.request(method, f"{v1}/subjects/{SUBJECT_ID}/{suffix}", json={}, timeout=10)
    assert r.status_code == 401, f"{method} {suffix} không đòi token: HTTP {r.status_code}"


def test_invalid_token_is_401(api, v1):
    r = api.get(_url(v1), headers={"Authorization": "Bearer not.a.real.token"}, timeout=10)
    assert r.status_code == 401


# ---------- GET danh sách ----------
def test_list_returns_list_of_recipients(api, v1, boss, recipient):
    r = api.get(_url(v1), headers=boss, timeout=15)
    assert r.status_code == 200, f"HTTP {r.status_code}"
    items = _items(r.json())
    assert items is not None, "Không tìm thấy danh sách trong JSON (mong items hoặc mảng)"
    assert recipient["email_id"] in {i.get("email_id") for i in items}, "Người nhận vừa tạo không có trong danh sách"
    for i in items:
        assert {"email_id", "email_address"} <= set(i), f"Thiếu trường trong bản ghi: {sorted(i)}"


def test_list_only_contains_this_subject(api, v1, boss, recipient):
    items = _items(api.get(_url(v1), headers=boss, timeout=15).json()) or []
    wrong = [i for i in items if i.get("subject_id") not in (None, SUBJECT_ID)]
    assert not wrong, f"Danh sách lẫn người nhận của môn khác: {wrong[:2]}"


def test_list_unknown_subject_is_404(api, v1, boss):
    r = api.get(_url(v1, MISSING_SUBJECT), headers=boss, timeout=15)
    assert r.status_code == 404, f"Môn không tồn tại nhưng nhận HTTP {r.status_code}"


# ---------- POST tạo ----------
def test_create_recipient_ok_and_visible_in_list(api, v1, boss):
    r, payload = _create(api, v1, boss, name="ZT Tao moi")
    try:
        assert r.status_code in CREATED, f"HTTP {r.status_code} {r.text[:200]}"
        rec = _obj(r.json())
        assert rec["email_address"] == payload["email_address"]
        assert rec.get("recipient_name") == "ZT Tao moi"
        assert rec.get("email_id") is not None
        ids = {i.get("email_id") for i in (_items(api.get(_url(v1), headers=boss, timeout=15).json()) or [])}
        assert rec["email_id"] in ids
    finally:
        if r.status_code in CREATED:
            api.delete(_url(v1, SUBJECT_ID, _obj(r.json())["email_id"]), headers=boss, timeout=15)


@pytest.mark.parametrize("bad", ["", "khong-phai-email", "thieu@", "@thieu.com", None, 123])
def test_create_rejects_invalid_email(api, v1, boss, bad):
    r = api.post(_url(v1), headers=boss, json={"email_address": bad, "recipient_name": "ZT"}, timeout=15)
    assert r.status_code in BAD_INPUT, f"Email {bad!r} sai nhưng nhận HTTP {r.status_code}"


def test_create_requires_email_address(api, v1, boss):
    r = api.post(_url(v1), headers=boss, json={"recipient_name": "ZT"}, timeout=15)
    assert r.status_code in BAD_INPUT, f"Thiếu email_address nhưng nhận HTTP {r.status_code}"


def test_create_duplicate_email_in_same_subject_is_rejected(api, v1, boss, recipient):
    """Trùng (subject_id, email_address) không được sinh thêm dòng thứ hai."""
    r, _ = _create(api, v1, boss, email=recipient["email_address"])
    assert r.status_code == 409, f"Trùng email phải trả 409 (theo openapi), nhận HTTP {r.status_code}"
    items = _items(api.get(_url(v1), headers=boss, timeout=15).json()) or []
    same = [i for i in items if i.get("email_address") == recipient["email_address"]]
    assert len(same) == 1, f"Trùng email vẫn sinh {len(same)} dòng"


def test_create_unknown_subject_is_404(api, v1, boss):
    r, _ = _create(api, v1, boss, subject_id=MISSING_SUBJECT)
    assert r.status_code == 404, f"Môn không tồn tại nhưng nhận HTTP {r.status_code}"


def test_create_trims_or_normalizes_nothing_unsafe(api, v1, boss):
    """Email có khoảng trắng đầu/cuối: hoặc bị cắt gọn, hoặc bị từ chối. Không được lưu nguyên khoảng trắng."""
    email = _new_email()
    r = api.post(_url(v1), headers=boss, json={"email_address": f"  {email}  ", "recipient_name": "ZT"}, timeout=15)
    if r.status_code in CREATED:
        rec = _obj(r.json())
        try:
            assert rec["email_address"] == email, f"Lưu nguyên khoảng trắng: {rec['email_address']!r}"
        finally:
            api.delete(_url(v1, SUBJECT_ID, rec["email_id"]), headers=boss, timeout=15)
    else:
        assert r.status_code in BAD_INPUT


# ---------- PUT sửa ----------
def test_update_recipient_name_and_selected(api, v1, boss, recipient):
    r = api.put(_url(v1, SUBJECT_ID, recipient["email_id"]), headers=boss,
                json={"recipient_name": "ZT Da sua", "is_selected": False}, timeout=15)
    assert r.status_code in UPDATED, f"HTTP {r.status_code} {r.text[:200]}"
    items = _items(api.get(_url(v1), headers=boss, timeout=15).json()) or []
    cur = next((i for i in items if i.get("email_id") == recipient["email_id"]), None)
    assert cur is not None, "Mất bản ghi sau khi sửa"
    assert cur.get("recipient_name") == "ZT Da sua"
    assert cur.get("is_selected") in (False, 0)


def test_update_email_address_ok(api, v1, boss, recipient):
    new = _new_email()
    r = api.put(_url(v1, SUBJECT_ID, recipient["email_id"]), headers=boss, json={"email_address": new}, timeout=15)
    assert r.status_code in UPDATED, f"HTTP {r.status_code}"
    items = _items(api.get(_url(v1), headers=boss, timeout=15).json()) or []
    cur = next(i for i in items if i.get("email_id") == recipient["email_id"])
    assert cur["email_address"] == new


def test_update_rejects_invalid_email(api, v1, boss, recipient):
    r = api.put(_url(v1, SUBJECT_ID, recipient["email_id"]), headers=boss,
                json={"email_address": "khong-phai-email"}, timeout=15)
    assert r.status_code in BAD_INPUT, f"HTTP {r.status_code}"


def test_update_cannot_move_recipient_to_other_subject(api, v1, boss, recipient):
    """Gửi subject_id khác trong body không được chuyển người nhận sang môn khác."""
    api.put(_url(v1, SUBJECT_ID, recipient["email_id"]), headers=boss,
            json={"subject_id": MISSING_SUBJECT, "recipient_name": "ZT"}, timeout=15)
    items = _items(api.get(_url(v1), headers=boss, timeout=15).json()) or []
    assert recipient["email_id"] in {i.get("email_id") for i in items}, "Người nhận biến khỏi môn gốc sau PUT"


def test_update_unknown_email_id_is_404(api, v1, boss):
    r = api.put(_url(v1, SUBJECT_ID, 99999999), headers=boss, json={"recipient_name": "ZT"}, timeout=15)
    assert r.status_code == 404, f"HTTP {r.status_code}"


def test_update_with_email_id_of_other_subject_is_404(api, v1, boss, recipient):
    """email_id có thật nhưng thuộc môn khác: gọi qua môn này phải 404, không được sửa nhầm."""
    r = api.put(_url(v1, MISSING_SUBJECT, recipient["email_id"]), headers=boss,
                json={"recipient_name": "ZT"}, timeout=15)
    assert r.status_code == 404, f"HTTP {r.status_code}"


# ---------- DELETE ----------
def test_delete_removes_from_list(api, v1, boss):
    r, _ = _create(api, v1, boss)
    assert r.status_code in CREATED
    eid = _obj(r.json())["email_id"]
    d = api.delete(_url(v1, SUBJECT_ID, eid), headers=boss, timeout=15)
    assert d.status_code in DELETED, f"HTTP {d.status_code}"
    items = _items(api.get(_url(v1), headers=boss, timeout=15).json()) or []
    assert eid not in {i.get("email_id") for i in items}, "Đã xóa nhưng vẫn còn trong danh sách"


def test_delete_twice_second_is_404(api, v1, boss):
    r, _ = _create(api, v1, boss)
    eid = _obj(r.json())["email_id"]
    api.delete(_url(v1, SUBJECT_ID, eid), headers=boss, timeout=15)
    again = api.delete(_url(v1, SUBJECT_ID, eid), headers=boss, timeout=15)
    assert again.status_code == 404, f"Xóa lần hai nhận HTTP {again.status_code}"


def test_delete_unknown_email_id_is_404(api, v1, boss):
    r = api.delete(_url(v1, SUBJECT_ID, 99999999), headers=boss, timeout=15)
    assert r.status_code == 404


def test_deleted_recipient_syncs_as_deleted_to_devices(api, v1, boss):
    """Xóa trên Web là xóa mềm: app phải nhận được qua /sync/pull (deleted_at có giá trị), không biến mất lặng lẽ."""
    head = api.get(f"{v1}/sync/pull", headers=boss, params={"after_seq": 0, "limit": 1}, timeout=30)
    if head.status_code != 200 or "latest_seq" not in head.json():
        pytest.skip(f"/sync/pull không cho lấy latest_seq (HTTP {head.status_code})")
    cursor = head.json()["latest_seq"]          # chỉ xét thay đổi xảy ra SAU mốc này
    r, payload = _create(api, v1, boss)
    assert r.status_code in CREATED
    eid = _obj(r.json())["email_id"]
    assert api.delete(_url(v1, SUBJECT_ID, eid), headers=boss, timeout=15).status_code in DELETED
    found = None
    for _ in range(50):
        pull = api.get(f"{v1}/sync/pull", headers=boss, params={"after_seq": cursor, "limit": 500}, timeout=30)
        assert pull.status_code == 200, f"/sync/pull trả HTTP {pull.status_code}"
        body = pull.json()
        for row in (body.get("changes") or {}).get("email_recipients", []):
            if row.get("email_address") == payload["email_address"]:
                found = row                      # lấy bản mới nhất của bản ghi này
        cursor = body["next_seq"]
        if not body.get("has_more"):
            break
    assert found is not None, "Bản ghi vừa tạo và xóa không xuất hiện trong /sync/pull"
    assert found.get("deleted_at"), "Xóa trên Web nhưng pull không báo deleted_at: app sẽ không biết đã xóa"


# ---------- Phân quyền ----------
def test_admin_can_manage_recipients_of_own_subject(api, v1, lecturer):
    r, _ = _create(api, v1, lecturer)
    try:
        assert r.status_code in CREATED, f"ADMIN không thêm được người nhận môn của mình: HTTP {r.status_code}"
    finally:
        if r.status_code in CREATED:
            api.delete(_url(v1, SUBJECT_ID, _obj(r.json())["email_id"]), headers=lecturer, timeout=15)


def test_admin_cannot_touch_other_lecturers_subject(api, v1, lecturer, boss):
    if not FOREIGN_SUBJECT_ID:
        pytest.skip("Đặt TEST_FOREIGN_SUBJECT_ID = môn của giảng viên khác để chạy ca này")
    assert api.get(_url(v1, FOREIGN_SUBJECT_ID), headers=lecturer, timeout=15).status_code == 403
    r, _ = _create(api, v1, lecturer, subject_id=FOREIGN_SUBJECT_ID)
    assert r.status_code == 403, f"ADMIN thêm được người nhận vào môn người khác: HTTP {r.status_code}"
    assert api.post(f"{v1}/subjects/{FOREIGN_SUBJECT_ID}/send-report", headers=lecturer, json={}, timeout=15
                    ).status_code == 403, "ADMIN gửi được báo cáo của môn người khác"


def test_super_admin_can_manage_any_subject(api, v1, boss):
    r, _ = _create(api, v1, boss)
    try:
        assert r.status_code in CREATED
    finally:
        if r.status_code in CREATED:
            api.delete(_url(v1, SUBJECT_ID, _obj(r.json())["email_id"]), headers=boss, timeout=15)


# ---------- Dữ liệu nhạy cảm ----------
def test_responses_do_not_expose_sensitive_fields(api, v1, boss, recipient):
    text = api.get(_url(v1), headers=boss, timeout=15).text.lower()
    for bad in ("password", "reset_token", "face_embedding", "checkin_password"):
        assert bad not in text, f"Danh sách người nhận lộ trường nhạy cảm: {bad}"


# ---------- POST send-report ----------
def test_send_report_unknown_subject_is_404(api, v1, boss):
    r = api.post(f"{v1}/subjects/{MISSING_SUBJECT}/send-report", headers=boss, json={}, timeout=15)
    assert r.status_code == 404, f"HTTP {r.status_code}"


def test_send_report_with_no_selected_recipients_is_rejected(api, v1, boss, recipient):
    """Không có người nhận nào được chọn thì không được báo thành công giả."""
    api.put(_url(v1, SUBJECT_ID, recipient["email_id"]), headers=boss, json={"is_selected": False}, timeout=15)
    items = _items(api.get(_url(v1), headers=boss, timeout=15).json()) or []
    if any(i.get("is_selected") in (True, 1) for i in items):
        pytest.skip("Môn thử còn người nhận khác đang được chọn; dùng môn trống để chạy ca này")
    r = api.post(f"{v1}/subjects/{SUBJECT_ID}/send-report", headers=boss, json={}, timeout=15)
    assert r.status_code in (400, 404, 409, 422), \
        f"Không có người nhận được chọn nhưng nhận HTTP {r.status_code}"


@pytest.mark.parametrize("body", [
    {"date_from": "khong-phai-ngay"},
    {"date_to": "2026-13-45"},
    {"date_from": "2026-11-30", "date_to": "2026-11-01"},   # từ ngày sau đến ngày
])
def test_send_report_rejects_invalid_dates(api, v1, boss, recipient, body):
    r = api.post(f"{v1}/subjects/{SUBJECT_ID}/send-report", headers=boss, json=body, timeout=15)
    assert r.status_code == 422, f"Ngày sai {body} nhưng nhận HTTP {r.status_code} (mong 422)"


@pytest.mark.skipif(os.getenv("RUN_SEND_REPORT") != "1",
                    reason="Ca gửi thật: đặt RUN_SEND_REPORT=1 (có thể gửi mail hoặc đưa job vào worker)")
def test_send_report_accepted_with_selected_recipient(api, v1, boss, recipient):
    api.put(_url(v1, SUBJECT_ID, recipient["email_id"]), headers=boss, json={"is_selected": True}, timeout=15)
    r = api.post(f"{v1}/subjects/{SUBJECT_ID}/send-report", headers=boss, json={}, timeout=60)
    assert r.status_code in ACCEPTED, f"HTTP {r.status_code} {r.text[:200]}"
    job_id = r.json().get("job_id")
    assert job_id, "Phản hồi 202 phải có job_id"
    j = api.get(f"{v1}/jobs/{job_id}", headers=boss, timeout=15)
    assert j.status_code == 200 and j.json().get("status"), f"Tra cứu job thất bại: HTTP {j.status_code}"
