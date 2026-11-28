#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TV7 (Task 12) - Giả lập máy A và máy B kiểm tra đồng bộ VECTOR KHUÔN MẶT và HASH MẬT KHẨU ĐIỂM DANH
qua server THẬT.

Chạy (trong thư mục server, server đang chạy, đã có admin@hkdn.edu.vn / admin123):
    python face_sync_sim.py
    python face_sync_sim.py --base https://xxx.trycloudflare.com

Có thể thêm tài khoản giảng viên để kiểm tra phân quyền (ca F13):
    python face_sync_sim.py --lecturer-email lecturer@hkdn.edu.vn --lecturer-password lecturer123

Ca cần xem trực tiếp database dùng 'docker compose exec postgres psql' (cần Docker, chạy trong thư mục con
của repo; đổi thư mục chứa docker-compose.yml bằng --compose-dir). Không có Docker thì ca đó ghi BỎ QUA.

Ý nghĩa trạng thái:
    ĐẠT                  đúng như mong đợi
    KHÔNG ĐẠT            sai, cần gửi lỗi cho người phụ trách
    CHỜ TV3 (chưa sửa)   ca phụ thuộc việc TV3 sửa /sync/pull và băm mật khẩu thô (task 4);
                         khi TV3 xong mà vẫn không đạt thì đổi thành lỗi thật
    BỎ QUA               thiếu điều kiện chạy (không có Docker, không có tài khoản giảng viên)
    LỖI CHẠY             script gặp lỗi bất ngờ
"""
import argparse
import csv
import random
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DIM = 192      # số chiều vector khuôn mặt (MobileFaceNet)
TOL = 1e-4     # sai số cho phép khi so sánh số thực (server lưu float32)


def new_uuid():
    return str(uuid.uuid4())


def rand_vec():
    return [round(random.uniform(-1, 1), 6) for _ in range(DIM)]


def hash_checkin():
    """Hash giả dạng $checkin$ (máy Android sau khi nâng cấp mật khẩu điểm danh)."""
    return f"$checkin$1$600000${uuid.uuid4().hex[:16]}${uuid.uuid4().hex}"


def hash_pbkdf2():
    """Hash giả dạng pbkdf2_sha256$ (dạng cũ)."""
    return f"pbkdf2_sha256$600000${uuid.uuid4().hex[:16]}${uuid.uuid4().hex}"


def near(a, b):
    return (isinstance(a, list) and isinstance(b, list) and len(a) == len(b)
            and all(abs(float(x) - float(y)) < TOL for x, y in zip(a, b)))


class Clock:
    """Đồng hồ ảo: mỗi lần gọi tăng 2 giây, để thứ tự thời gian các thao tác luôn rõ ràng."""

    def __init__(self):
        self.t = 0

    def __call__(self):
        self.t += 2
        return (datetime.now(timezone.utc) + timedelta(seconds=self.t)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Api:
    def __init__(self, base, headers):
        self.v1 = base.rstrip("/") + "/api/v1"
        self.s = requests.Session()
        self.headers = headers

    @staticmethod
    def login(base, email, password):
        """Trả về header Bearer nếu đăng nhập được, ngược lại None."""
        r = requests.post(f"{base.rstrip('/')}/api/v1/auth/login",
                          json={"email": email, "password": password}, timeout=15)
        if r.status_code == 200:
            return {"Authorization": f"Bearer {r.json()['access_token']}"}
        return None

    def post(self, path, body):
        return self.s.post(f"{self.v1}{path}", json=body, headers=self.headers, timeout=30)

    def get(self, path, params):
        return self.s.get(f"{self.v1}{path}", params=params, headers=self.headers, timeout=30)


def latest_seq(api):
    r = api.get("/sync/pull", {"after_seq": 0, "limit": 1})
    r.raise_for_status()
    return r.json()["latest_seq"]


class Device:
    """Một máy giả lập: có con trỏ kéo về (after_seq) riêng và sổ sinh viên đã kéo về."""

    def __init__(self, name, api, start_seq):
        self.name, self.api, self.cursor = name, api, start_seq
        self.students = {}   # student_id -> bản ghi mới nhất đã kéo về
        self.seen = {}       # tên bảng -> mọi bản ghi đã kéo về (để kiểm tra trường nhạy cảm)

    def push(self, body):
        return self.api.post("/sync/push", body)

    def pull(self, limit=500):
        pages = 0
        while pages < 1000:
            r = self.api.get("/sync/pull", {"after_seq": self.cursor, "limit": limit})
            if r.status_code != 200:
                raise RuntimeError(f"pull lỗi HTTP {r.status_code}: {r.text[:200]}")
            b = r.json()
            pages += 1
            for table, rows in b["changes"].items():
                self.seen.setdefault(table, []).extend(rows)
                if table == "students":
                    for rec in rows:
                        old = self.students.get(rec["student_id"])
                        if old is None or rec["seq"] >= old["seq"]:
                            self.students[rec["student_id"]] = rec
            self.cursor = b["next_seq"]
            if not b["has_more"]:
                break
        return pages


def student_rec(sid, name, vec, pw, ts, u=None):
    rec = {"student_id": sid, "full_name": name, "uuid": u or new_uuid(),
           "updated_at": ts, "deleted_at": None}
    if vec is not None:
        rec["face_embedding"] = vec
    if pw is not None:
        rec["checkin_password"] = pw
    return rec


# ---------- Đọc trực tiếp database qua docker ----------
def db_query(sql, compose_dir):
    """Chạy một câu SQL, trả về danh sách dòng (chuỗi, các cột cách nhau bằng |). None nếu không chạy được."""
    cmd = ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres",
           "-d", "attendance_server", "-t", "-A", "-F", "|", "-c", sql]
    try:
        r = subprocess.run(cmd, cwd=compose_dir, capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return [line for line in r.stdout.strip().splitlines() if line]


def db_vector(sid, compose_dir):
    rows = db_query(f"SELECT face_embedding::text FROM students WHERE student_id='{sid}';", compose_dir)
    if not rows:
        return None
    try:
        return [float(x) for x in rows[0].strip().strip("[]").split(",")]
    except ValueError:
        return None


def to_map(rows):
    return dict(line.split("|", 1) for line in rows if "|" in line)


class Checklist:
    HEADER = ["Mã ca", "Kịch bản", "Kết quả mong đợi", "Kết quả thực tế", "Trạng thái",
              "Gửi lỗi cho", "Ghi chú", "Số thiết bị", "Thời điểm chạy"]

    def __init__(self):
        self.rows = []

    def add(self, code, title, expected, actual, ok, owner, wait=False):
        note = ""
        if ok is None:
            status = "BỎ QUA"
        elif ok:
            status = "ĐẠT"
        elif wait:
            status = "CHỜ TV3 (chưa sửa)"
            note = "Phụ thuộc task 4 của TV3 (/sync/pull trả vector, băm mật khẩu thô)"
        else:
            status = "KHÔNG ĐẠT"
        self.rows.append([code, title, expected, actual, status, owner if status == "KHÔNG ĐẠT" else "", note])
        print(f"[{status}] {code} - {title}\n      → {actual}")

    def error(self, code, title, expected, exc, owner):
        self.rows.append([code, title, expected, f"{type(exc).__name__}: {exc}", "LỖI CHẠY", owner, ""])
        print(f"[LỖI CHẠY] {code} - {title}\n      → {type(exc).__name__}: {exc}")

    def count(self, status):
        return sum(1 for r in self.rows if r[4] == status)

    def save(self, path, n_devices):
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(self.HEADER)
            for r in self.rows:
                w.writerow(r + [n_devices, now])


def run(api, lec_api, cdir):
    clock = Clock()
    start = latest_seq(api)
    A, B = Device("A", api, start), Device("B", api, start)
    tag = "ZV" + uuid.uuid4().hex[:5].upper()
    s1, s2, s3, s4, s5, s6, s7 = (f"{tag}{i:02d}" for i in range(1, 8))
    vec1, vec2 = rand_vec(), rand_vec()
    h1, h2 = hash_checkin(), hash_pbkdf2()
    keep = {}
    cl = Checklist()
    print(f"Chạy máy A, máy B; mã dữ liệu mẫu: {tag}\n")

    def case(code, title, expected, owner, fn, wait=False):
        try:
            ok, actual = fn()
            cl.add(code, title, expected, actual, ok, owner, wait)
        except Exception as e:  # một ca hỏng không làm dừng cả buổi chạy
            cl.error(code, title, expected, e, owner)

    no_psql = "Không chạy được psql (cần Docker, chạy trong thư mục con của repo, hoặc dùng --compose-dir)"
    rec1 = student_rec(s1, "SV vector 1", vec1, h1, clock())
    rec2 = student_rec(s2, "SV vector 2", vec2, h2, clock())

    # ================= PHÍA PUSH (chạy được ngay) =================
    def f01():
        r = A.push({"students": [rec1, rec2]})
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}: {r.text[:120]}"
        ap = r.json().get("applied", {})
        return ap.get("students") == 2, f"HTTP 200; server áp dụng: {ap}"
    case("F01", "Máy A đẩy 2 sinh viên kèm vector 192 số và hash mật khẩu điểm danh",
         "HTTP 200, áp dụng 2 sinh viên", "TV3", f01)

    def f02():
        rows = db_query(f"SELECT student_id, vector_dims(face_embedding) FROM students "
                        f"WHERE student_id IN ('{s1}','{s2}') ORDER BY student_id;", cdir)
        if rows is None:
            return None, no_psql
        got = to_map(rows)
        return (got.get(s1) == str(DIM) and got.get(s2) == str(DIM)), \
            f"Số chiều vector trên server: {got or 'không có dòng nào'}"
    case("F02", "Server đã lưu vector đủ 192 chiều", "Cả 2 sinh viên có vector 192 chiều", "TV3", f02)

    def f03():
        rows = db_query(f"SELECT student_id, checkin_password FROM students "
                        f"WHERE student_id IN ('{s1}','{s2}');", cdir)
        if rows is None:
            return None, no_psql
        got = to_map(rows)
        ok = got.get(s1) == h1 and got.get(s2) == h2
        shown = {k: (v[:14] + "...") for k, v in got.items()}
        return ok, ("Hash trên server giữ nguyên, khớp bản máy A gửi" if ok
                    else f"Hash trên server KHÁC bản đã gửi (bị băm lại?): {shown}")
    case("F03", "Hash mật khẩu điểm danh ($checkin$ và pbkdf2_sha256$) được lưu nguyên, không băm lại",
         "Hash trên server giống hệt hash đã gửi", "TV3", f03)

    def f04():
        r = A.push({"students": [student_rec(s3, "SV sai chieu", vec1[:-1], None, clock())]})
        cnt = db_query(f"SELECT COUNT(*) FROM students WHERE student_id='{s3}';", cdir)
        stored = cnt[0] if cnt else None
        ok = r.status_code in (400, 422) and stored in (None, "0")
        return ok, f"HTTP {r.status_code}; số dòng đã lưu: {stored if stored is not None else 'không kiểm tra được'}"
    case("F04", "Vector 191 số (sai chiều) bị từ chối và không được lưu", "HTTP 422, không có dòng nào", "TV3", f04)

    def f05():
        bad = list(vec1)
        bad[5] = "abc"
        r = A.push({"students": [student_rec(s4, "SV vector chu", bad, None, clock())]})
        cnt = db_query(f"SELECT COUNT(*) FROM students WHERE student_id='{s4}';", cdir)
        stored = cnt[0] if cnt else None
        ok = r.status_code in (400, 422) and stored in (None, "0")
        return ok, f"HTTP {r.status_code}; số dòng đã lưu: {stored if stored is not None else 'không kiểm tra được'}"
    case("F05", "Vector có giá trị không phải số bị từ chối và không được lưu", "HTTP 422, không có dòng nào",
         "TV3", f05)

    def f06():
        r = A.push({"students": [rec1]})   # gửi lặp y hệt
        cnt = db_query(f"SELECT COUNT(*) FROM students WHERE student_id='{s1}';", cdir)
        stored = cnt[0] if cnt else None
        ok = r.status_code == 200 and stored in (None, "1")
        return ok, f"HTTP {r.status_code}; số dòng trên server cho {s1}: {stored if stored is not None else 'không kiểm tra được'}"
    case("F06", "Máy A gửi lặp cùng một sinh viên có vector → không sinh dòng trùng", "Server chỉ có 1 dòng", "TV3", f06)

    def f07():
        t_old, t_mid, t_new = clock(), clock(), clock()
        u = new_uuid()
        va, vb, vc = rand_vec(), rand_vec(), rand_vec()
        r1 = A.push({"students": [student_rec(s5, "SV dang ky lai", va, None, t_mid, u)]})
        r2 = A.push({"students": [student_rec(s5, "SV dang ky lai", vb, None, t_new, u)]})
        after_new = db_vector(s5, cdir)
        r3 = A.push({"students": [student_rec(s5, "SV dang ky lai", vc, None, t_old, u)]})   # bản cũ hơn
        after_old = db_vector(s5, cdir)
        keep["vb"] = vb
        if not all(r.status_code == 200 for r in (r1, r2, r3)):
            return False, f"push lỗi HTTP {[r.status_code for r in (r1, r2, r3)]}"
        skipped = r3.json().get("skipped", {}).get("students")
        new_ok = after_new is None or near(after_new, vb)
        old_ok = skipped == 1 and (after_old is None or near(after_old, vb))
        return new_ok and old_ok, (f"Vector mới ghi đè vector cũ: {new_ok if after_new is not None else 'không kiểm tra được'}; "
                                   f"bản cũ hơn gửi sau bị bỏ qua (skipped={skipped}), vector giữ nguyên: "
                                   f"{old_ok if after_old is not None else 'không kiểm tra được'}")
    case("F07", "Đăng ký lại khuôn mặt: vector mới ghi đè, bản cũ hơn gửi sau bị bỏ qua",
         "Server giữ vector mới nhất theo updated_at", "TV3", f07)

    def f08():
        r = A.push({"students": [student_rec(s6, "SV mat khau tho", None, "123456", clock())]})
        rows = db_query(f"SELECT checkin_password FROM students WHERE student_id='{s6}';", cdir)
        if rows is None:
            return None, no_psql
        stored = rows[0] if rows else ""
        ok = r.status_code == 200 and stored != "123456" and stored.startswith(("pbkdf2_sha256$", "$checkin$"))
        shown = "mật khẩu thô (chưa băm)" if stored == "123456" else stored[:18] + "..."
        return ok, f"HTTP {r.status_code}; server lưu: {shown}"
    case("F08", "Máy gửi mật khẩu thô → server băm trước khi lưu", "Server lưu dạng hash, không lưu mật khẩu thô",
         "TV3", f08, wait=True)

    # ================= PHÍA PULL (phụ thuộc TV3 sửa /sync/pull) =================
    def f09():
        B.pull()
        rec = B.students.get(s1)
        if rec is None:
            return False, "Máy B không thấy sinh viên"
        fe = rec.get("face_embedding")
        if fe is None:
            return False, "Máy B thấy sinh viên nhưng KHÔNG có face_embedding (server đang ẩn khi pull)"
        ok = isinstance(fe, list) and len(fe) == DIM and near(fe, vec1)
        return ok, f"Máy B nhận vector {len(fe)} số; khớp vector máy A đã đẩy: {near(fe, vec1)}"
    case("F09", "Máy B kéo về → nhận đủ 192 số vector, giống hệt máy A", "192 số, khớp vector của A", "TV3", f09, wait=True)

    def f10():
        B.pull()
        a, b = B.students.get(s1), B.students.get(s2)
        pa = a.get("checkin_password") if a else None
        pb = b.get("checkin_password") if b else None
        ok = pa == h1 and pb == h2
        return ok, ("Máy B nhận đúng hash của cả 2 sinh viên" if ok
                    else f"Hash máy B nhận: {str(pa)[:14]!r}, {str(pb)[:14]!r} (không khớp hoặc không có)")
    case("F10", "Máy B kéo về → nhận hash mật khẩu điểm danh đúng như máy A đẩy ($checkin$ không bị băm lại)",
         "Hash giống hệt", "TV3", f10, wait=True)

    def f11():
        B.pull()
        bad = set()
        for table, rows in B.seen.items():
            for rec in rows:
                if table != "students":
                    bad |= {f"{table}.{k}" for k in ("face_embedding", "checkin_password") if k in rec}
                bad |= {f"{table}.{k}" for k in ("password", "reset_token") if k in rec}
        return not bad, f"Trường lộ ra ngoài phạm vi cho phép: {sorted(bad) or 'không có'}"
    case("F11", "Vector và hash chỉ có ở bảng students; password và reset_token không bao giờ được trả",
         "Không có trường nhạy cảm ngoài students", "TV4", f11)

    def f12():
        vb = keep.get("vb")
        if vb is None:
            return None, "Chưa có dữ liệu từ ca F07"
        B.pull()
        rec = B.students.get(s5)
        fe = rec.get("face_embedding") if rec else None
        return near(fe, vb), ("Máy B thấy vector mới sau khi đăng ký lại" if near(fe, vb)
                              else "Máy B không thấy vector mới (hoặc không có vector)")
    case("F12", "Đăng ký lại khuôn mặt ở máy A → máy B kéo về thấy vector mới", "Máy B có vector mới nhất",
         "TV3", f12, wait=True)

    def f13():
        if lec_api is None:
            return None, "Chưa đăng nhập được tài khoản giảng viên (dùng --lecturer-email, --lecturer-password)"
        code = f"{tag}SUB"
        r = A.push({
            "subjects": [{"subject_id": code, "subject_name": "Mon vector", "uuid": new_uuid(),
                          "updated_at": clock(), "deleted_at": None}],
            "students": [student_rec(s7, "SV ngoai mon", rand_vec(), hash_checkin(), clock())],
            "enrollments": [{"student_id": s7, "subject_id": code, "enrollment_status": "Enrolled",
                             "uuid": new_uuid(), "updated_at": clock(), "deleted_at": None}]})
        if r.status_code != 200:
            return False, f"push lỗi HTTP {r.status_code}: {r.text[:120]}"
        lec = Device("GV", lec_api, start)
        lec.pull()
        rec = lec.students.get(s7)
        return rec is None, ("Giảng viên không phụ trách môn này không nhận sinh viên (đúng)" if rec is None
                             else f"Giảng viên NHẬN được sinh viên ngoài môn, có vector: {'face_embedding' in rec}")
    case("F13", "Giảng viên không phụ trách môn → không nhận sinh viên và vector của môn đó",
         "Giảng viên không thấy sinh viên", "TV4", f13)

    return cl


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="http://localhost:5000", help="Địa chỉ server (không có /api/v1)")
    p.add_argument("--email", default="admin@hkdn.edu.vn")
    p.add_argument("--password", default="admin123")
    p.add_argument("--lecturer-email", default="lecturer@hkdn.edu.vn")
    p.add_argument("--lecturer-password", default="lecturer123")
    p.add_argument("--compose-dir", default="..", help="Thư mục chứa docker-compose.yml (mặc định: thư mục cha)")
    p.add_argument("--out", default="checklist_vector.csv")
    a = p.parse_args()

    try:
        admin_headers = Api.login(a.base, a.email, a.password)
    except requests.RequestException as e:
        sys.exit(f"Không kết nối được server tại {a.base}: {e}")
    if admin_headers is None:
        sys.exit("Đăng nhập admin thất bại (kiểm tra --email, --password, hoặc chạy seed_admin.py)")
    try:
        lec_headers = Api.login(a.base, a.lecturer_email, a.lecturer_password)
    except requests.RequestException:
        lec_headers = None
    if lec_headers is None:
        print("[!] Không đăng nhập được tài khoản giảng viên: ca F13 sẽ BỎ QUA.\n")

    cl = run(Api(a.base, admin_headers), Api(a.base, lec_headers) if lec_headers else None, a.compose_dir)
    cl.save(a.out, 2)
    bad = cl.count("KHÔNG ĐẠT") + cl.count("LỖI CHẠY")
    print(f"\nTổng: {len(cl.rows)} ca | đạt {cl.count('ĐẠT')} | chờ TV3 {cl.count('CHỜ TV3 (chưa sửa)')} | "
          f"bỏ qua {cl.count('BỎ QUA')} | lỗi thật {bad}")
    print(f"Đã lưu: {a.out}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
