#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TV7 - Mô phỏng 3-6 thiết bị đồng bộ qua server THẬT, ghi kết quả vào CSV "Checklist nghiệm thu".

Mỗi "thiết bị" là một client độc lập: có sổ dữ liệu riêng (giả lập SQLite), hàng đợi gửi (outbox)
và con trỏ kéo về (after_seq) riêng. Chúng chỉ nói chuyện với nhau qua /sync/push và /sync/pull.

Chạy (trong thư mục server, server đang chạy, đã chạy seed_admin.py):
    python multi_device_sim.py --devices 4
Kết quả: in ra màn hình và lưu file checklist_nghiem_thu.csv (mở bằng Excel).
Dữ liệu mẫu có mã bắt đầu bằng chữ Z + 5 ký tự ngẫu nhiên, mỗi lần chạy một mã mới.
"""
import argparse
import csv
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TABLES = ["admin", "subjects", "students", "enrollments", "checkin_history", "email_recipients"]


def new_uuid():
    return str(uuid.uuid4())


class Clock:
    """Đồng hồ ảo: mỗi lần gọi tăng thêm 2 giây, để thứ tự thời gian của các thao tác luôn rõ ràng."""

    def __init__(self):
        self.t = 0

    def __call__(self):
        self.t += 2
        return (datetime.now(timezone.utc) + timedelta(seconds=self.t)).strftime("%Y-%m-%dT%H:%M:%SZ")


class NetworkDown(Exception):
    pass


class SyncError(Exception):
    pass


class Api:
    def __init__(self, base, email, password):
        self.v1 = base.rstrip("/") + "/api/v1"
        self.s = requests.Session()
        self.headers = {}
        try:
            r = self.s.post(f"{self.v1}/auth/login", json={"email": email, "password": password}, timeout=10)
        except requests.RequestException as e:
            sys.exit(f"Không kết nối được server tại {base}: {e}")
        if r.status_code == 200:
            self.headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        else:
            print(f"[!] Đăng nhập thất bại (HTTP {r.status_code}); chạy tiếp không kèm token.")

    def _h(self, device):
        h = dict(self.headers)
        if device:
            h["X-Device-Id"] = device  # chỉ là nhãn để dễ tra log; server hiện không dùng
        return h

    def post(self, path, body, device=""):
        return self.s.post(f"{self.v1}{path}", json=body, headers=self._h(device), timeout=30)

    def get(self, path, params, device=""):
        return self.s.get(f"{self.v1}{path}", params=params, headers=self._h(device), timeout=30)


def latest_seq(api):
    r = api.get("/sync/pull", {"after_seq": 0, "limit": 1})
    r.raise_for_status()
    return r.json()["latest_seq"]


def server_rows(api, since, table, pred):
    """Đọc thẳng từ server (như một máy mới tinh) để đếm bản ghi thật sự có trên server."""
    out, cur = [], since
    while True:
        r = api.get("/sync/pull", {"after_seq": cur, "limit": 500})
        r.raise_for_status()
        b = r.json()
        out += [rec for rec in b["changes"].get(table, []) if pred(rec)]
        cur = b["next_seq"]
        if not b["has_more"]:
            return out


class Device:
    def __init__(self, name, api, start_seq, clock):
        self.name, self.api, self.clock = name, api, clock
        self.cursor = start_seq
        self.store = {t: {} for t in TABLES}   # dữ liệu cục bộ (giả lập SQLite trên máy)
        self.outbox = []                       # thao tác chờ gửi: [(bảng, bản ghi)]
        self.online = True

    # ---- khóa của từng bảng trong "SQLite" ----
    @staticmethod
    def key(table, rec):
        if table == "students":
            return rec["student_id"]
        if table == "subjects":
            return rec["subject_id"]
        if table == "enrollments":
            return (rec["student_id"], rec["subject_id"])
        return rec["uuid"]

    def _save(self, table, rec):
        self.store[table][self.key(table, rec)] = rec
        self.outbox.append((table, dict(rec)))
        return rec

    # ---- thao tác của người dùng (ghi vào sổ cục bộ + hàng đợi) ----
    def add_subject(self, code, name):
        return self._save("subjects", {"subject_id": code, "subject_name": name, "uuid": new_uuid(),
                                       "updated_at": self.clock(), "deleted_at": None})

    def add_student(self, sid, name, ts=None):
        return self._save("students", {"student_id": sid, "full_name": name, "uuid": new_uuid(),
                                       "updated_at": ts or self.clock(), "deleted_at": None})

    def edit_student(self, sid, name, ts=None):
        rec = dict(self.store["students"][sid])
        rec.update(full_name=name, updated_at=ts or self.clock())
        return self._save("students", rec)

    def delete_student(self, sid, ts=None):
        ts = ts or self.clock()
        rec = dict(self.store["students"][sid])
        rec.update(updated_at=ts, deleted_at=ts)
        return self._save("students", rec)

    def enroll(self, sid, code):
        return self._save("enrollments", {"student_id": sid, "subject_id": code,
                                          "enrollment_status": "Enrolled", "uuid": new_uuid(),
                                          "updated_at": self.clock(), "deleted_at": None})

    def checkin(self, sid, code, ts=None, checkin_id=None):
        rec = {"student_id": sid, "subject_id": code, "checkin_time": "07:30:00",
               "checkin_date": date.today().isoformat(), "uuid": new_uuid(),
               "updated_at": ts or self.clock(), "deleted_at": None}
        if checkin_id is not None:
            rec["checkin_id"] = checkin_id
        return self._save("checkin_history", rec)

    # ---- đồng bộ ----
    def push(self):
        if not self.online:
            raise NetworkDown(self.name)
        if not self.outbox:
            return {"applied": {}, "skipped": {}}
        body = {}
        for t, rec in self.outbox:
            body.setdefault(t, []).append(rec)
        r = self.api.post("/sync/push", body, self.name)
        if r.status_code != 200:
            raise SyncError(f"push lỗi HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        self.outbox.clear()  # chỉ xóa hàng đợi SAU KHI server xác nhận thành công
        return data

    def pull(self, limit=500):
        if not self.online:
            raise NetworkDown(self.name)
        pages = 0
        while True:
            r = self.api.get("/sync/pull", {"after_seq": self.cursor, "limit": limit}, self.name)
            if r.status_code != 200:
                raise SyncError(f"pull lỗi HTTP {r.status_code}: {r.text[:200]}")
            b = r.json()
            pages += 1
            for t, rows in b["changes"].items():
                for rec in rows:
                    k = self.key(t, rec)
                    old = self.store[t].get(k)
                    if old is None or old["updated_at"] <= rec["updated_at"]:
                        self.store[t][k] = rec  # bản mới hơn (hoặc bằng) thì thắng
            self.cursor = b["next_seq"]
            if not b["has_more"]:
                return pages

    # ---- đọc dữ liệu để so sánh ----
    def students(self, tag):
        return {k: r.get("full_name") for k, r in self.store["students"].items()
                if k.startswith(tag) and not r.get("deleted_at")}

    def checkin_uuids(self):
        return {r["uuid"] for r in self.store["checkin_history"].values() if not r.get("deleted_at")}


def sync_all(devs):
    for d in devs:
        if d.online and d.outbox:
            d.push()
    for d in devs:
        if d.online:
            d.pull()


class Checklist:
    def __init__(self):
        self.rows = []

    def add(self, code, title, expected, actual, ok, owner, known=None):
        if ok:
            status = "ĐẠT"
        elif known:
            status = "KHÔNG ĐẠT (lỗi đã biết)"
        else:
            status = "KHÔNG ĐẠT"
        note = known or ""
        self.rows.append([code, title, expected, actual, status, owner if not ok else "", note])
        print(f"[{status}] {code} - {title}\n      → {actual}")

    def error(self, code, title, expected, exc, owner):
        self.rows.append([code, title, expected, f"{type(exc).__name__}: {exc}", "LỖI CHẠY", owner, ""])
        print(f"[LỖI CHẠY] {code} - {title}\n      → {type(exc).__name__}: {exc}")

    def failed(self):
        return [r for r in self.rows if r[4] in ("KHÔNG ĐẠT", "LỖI CHẠY")]

    def save(self, path, n_devices):
        header = ["Mã ca", "Kịch bản", "Kết quả mong đợi", "Kết quả thực tế", "Trạng thái",
                  "Gửi lỗi cho", "Ghi chú", "Số thiết bị", "Thời điểm chạy"]
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(header)
            for r in self.rows:
                w.writerow(r + [n_devices, now])


def run(api, n):
    clock = Clock()
    start = latest_seq(api)
    devs = [Device(name, api, start, clock) for name in "ABCDEF"[:n]]
    A, B = devs[0], devs[1]
    tag = "Z" + uuid.uuid4().hex[:5].upper()
    sub = f"{tag}SUB"
    cl = Checklist()
    tracked = []   # uuid các bản ghi điểm danh phải thấy ở mọi máy
    keep = {}

    print(f"Chạy {n} thiết bị ({', '.join(d.name for d in devs)}), mã dữ liệu mẫu: {tag}\n")
    A.add_subject(sub, "Mon mo phong")
    sync_all(devs)

    def case(code, title, expected, owner, fn, known=None):
        try:
            ok, actual = fn()
            cl.add(code, title, expected, actual, ok, owner, known)
        except Exception as e:  # một ca hỏng không làm dừng cả buổi chạy
            for d in devs:
                d.online = True
            cl.error(code, title, expected, e, owner)

    sid1, sid2, sid3, sid4, sid5, sid6, sid7, sid8, sid9, sid10 = (f"{tag}{i:02d}" for i in range(1, 11))

    def c01():
        A.add_student(sid1, "Nguyen Van A")
        sync_all(devs)
        seen = {d.name: d.students(tag).get(sid1) for d in devs}
        return all(v == "Nguyen Van A" for v in seen.values()), f"Tên thấy trên từng máy: {seen}"
    case("C01", f"A thêm sinh viên → {n - 1} máy còn lại thấy", "Mọi máy thấy đúng tên", "TV3", c01)

    def c02():
        A.edit_student(sid1, "Nguyen Van A (da sua)")
        sync_all(devs)
        seen = {d.name: d.students(tag).get(sid1) for d in devs}
        return all(v == "Nguyen Van A (da sua)" for v in seen.values()), f"Tên thấy: {seen}"
    case("C02", "A sửa tên sinh viên → các máy thấy tên mới", "Mọi máy thấy tên mới", "TV3", c02)

    def c03():
        A.delete_student(sid1)
        sync_all(devs)
        hidden = {d.name: (sid1 not in d.students(tag)) for d in devs}
        flagged = all(d.store["students"][sid1].get("deleted_at") for d in devs)
        return all(hidden.values()) and flagged, f"Đã ẩn trên từng máy: {hidden}; có deleted_at ở mọi máy: {flagged}"
    case("C03", "A xóa (xóa mềm) sinh viên → các máy không còn thấy", "Mọi máy ẩn sinh viên", "TV3", c03)

    def c04():
        A.add_student(sid2, "Tran Thi B")
        A.enroll(sid2, sub)
        rec = A.checkin(sid2, sub)
        tracked.append(rec["uuid"])
        sync_all(devs)
        miss = [d.name for d in devs if rec["uuid"] not in d.checkin_uuids()]
        return not miss, "Máy thiếu bản ghi điểm danh: " + (",".join(miss) or "không có")
    case("C04", "A điểm danh → các máy thấy bản ghi điểm danh", "Mọi máy thấy bản ghi", "TV3", c04)

    def c05():
        B.online = False
        B.add_student(sid3, "Le Van C (tao luc mat mang)")
        rec = B.checkin(sid3, sub)
        tracked.append(rec["uuid"])
        refused = False
        try:
            B.push()
        except NetworkDown:
            refused = True
        kept = len(B.outbox)
        B.online = True
        sync_all(devs)
        seen = [d.name for d in devs if sid3 in d.students(tag)]
        ok = (refused and kept >= 2 and not B.outbox and len(seen) == len(devs)
              and all(rec["uuid"] in d.checkin_uuids() for d in devs))
        return ok, (f"Khi mất mạng: gửi bị từ chối={refused}, thao tác giữ lại={kept}; "
                    f"sau khi có mạng: máy thấy sinh viên={seen}, hàng đợi B còn={len(B.outbox)}")
    case("C05", "B mất mạng, thao tác, có mạng lại → tự đồng bộ, không mất thao tác",
         "Hàng đợi giữ nguyên khi mất mạng; có mạng thì mọi máy thấy dữ liệu", "TV6", c05)

    def c06():
        A.add_student(sid4, "Pham Thi D")
        saved = list(A.outbox)
        A.push()
        A.outbox = list(saved)
        A.push()  # gửi lặp y hệt (giống app gửi lại do không nhận được phản hồi)
        sync_all(devs)
        rows = server_rows(api, start, "students", lambda r: r["student_id"] == sid4)
        ok = len(rows) == 1 and all(d.students(tag).get(sid4) == "Pham Thi D" for d in devs)
        return ok, f"Số dòng trên server cho mã {sid4}: {len(rows)}"
    case("C06", "A gửi lặp cùng một thao tác 2 lần → không sinh dữ liệu trùng", "Server chỉ có 1 dòng", "TV3", c06)

    def c07():
        A.add_student(sid5, "E goc")
        A.add_student(sid6, "F goc")
        sync_all(devs)
        t_old, t_new = clock(), clock()
        A.edit_student(sid5, "E - A sua (moi hon)", ts=t_new)
        B.edit_student(sid5, "E - B sua (cu hon)", ts=t_old)
        A.push()
        resp = B.push()  # bản cũ hơn đến sau
        t_old2, t_new2 = clock(), clock()
        B.edit_student(sid6, "F - B sua (cu hon)", ts=t_old2)
        A.edit_student(sid6, "F - A sua (moi hon)", ts=t_new2)
        B.push()
        A.push()  # bản mới hơn đến sau
        sync_all(devs)
        g5 = {d.name: d.students(tag).get(sid5) for d in devs}
        g6 = {d.name: d.students(tag).get(sid6) for d in devs}
        ok = (all(v == "E - A sua (moi hon)" for v in g5.values())
              and all(v == "F - A sua (moi hon)" for v in g6.values()))
        return ok, f"Bản cũ gửi sau bị bỏ qua (skipped={resp.get('skipped', {}).get('students')}); kết quả: {g5} | {g6}"
    case("C07", "A và B cùng sửa một sinh viên → bản có thời gian mới hơn thắng (cả 2 thứ tự gửi)",
         "Mọi máy hội tụ về bản của A (mới hơn)", "TV3", c07)

    def c08():
        A.online = B.online = False
        t1, t2 = clock(), clock()
        keep["a"] = A.add_student(sid7, "May A tao (cu hon)", ts=t1)
        B.add_student(sid7, "May B tao (moi hon)", ts=t2)
        A.online = B.online = True
        sync_all(devs)
        rows = server_rows(api, start, "students", lambda r: r["student_id"] == sid7)
        keep["rows"] = rows
        names = {d.name: d.students(tag).get(sid7) for d in devs}
        ok = len(rows) == 1 and all(v == "May B tao (moi hon)" for v in names.values())
        return ok, f"Số dòng trên server cho mã {sid7}: {len(rows)}; tên thấy: {names}"
    case("C08", "A và B cùng tạo một mã sinh viên lúc mất mạng → gộp thành 1 dòng, bản mới hơn thắng",
         "Server 1 dòng, tên của máy B", "TV3", c08)

    def c09():
        rows = keep.get("rows") or []
        got = rows[0]["uuid"] if rows else None
        return got == keep["a"]["uuid"], f"uuid trên server={got}; uuid máy A đã tạo={keep['a']['uuid']}"
    case("C09", "Sau khi gộp, uuid của bản ghi gốc được giữ nguyên", "uuid không đổi", "TV3", c09,
         known="Server ghi đè uuid khi gộp theo mã sinh viên (chờ Lead chốt uuid chuẩn)")

    def c10():
        A.add_student(sid8, "SV tam 8")
        ra = A.checkin(sid8, sub)
        sync_all(devs)
        got = server_rows(api, start, "checkin_history", lambda r: r["uuid"] == ra["uuid"])
        n_id = got[0]["checkin_id"]
        B.add_student(sid9, "SV tam 9")
        rb = B.checkin(sid9, sub, checkin_id=n_id)  # máy B tình cờ dùng cùng số thứ tự
        sync_all(devs)
        have = {r["uuid"] for r in server_rows(api, start, "checkin_history",
                                               lambda r: r["uuid"] in (ra["uuid"], rb["uuid"]))}
        return {ra["uuid"], rb["uuid"]} <= have, f"Số bản ghi điểm danh còn lại trên server: {len(have)}/2"
    case("C10", "Hai máy dùng cùng số thứ tự điểm danh (checkin_id) → vẫn là 2 bản ghi riêng", "2 bản ghi", "TV3", c10,
         known="Server khớp điểm danh theo checkin_id của client nên bản ghi máy này đè máy kia")

    def c11():
        B.add_student(sid10, "SV 10")
        B.enroll(sid10, sub)
        rec = B.checkin(sid10, sub)
        tracked.append(rec["uuid"])
        ap = B.push()["applied"]
        sync_all(devs)
        ok = (ap.get("students") == 1 and ap.get("enrollments") == 1 and ap.get("checkin_history") == 1
              and all(rec["uuid"] in d.checkin_uuids() for d in devs))
        return ok, f"Server áp dụng: {ap}"
    case("C11", "B gửi một lô gồm sinh viên + ghi danh + điểm danh → server nhận đúng thứ tự cha-con",
         "Cả 3 bảng được áp dụng", "TV3", c11)

    ids = [f"{tag}P{i}" for i in range(7)]

    def c12():
        for i, sid in enumerate(ids):
            A.add_student(sid, f"SV phan trang {i}")
        sync_all(devs)
        z = Device("Z", api, start, clock)
        pages = z.pull(limit=2)
        seen = sum(1 for sid in ids if sid in z.students(tag))
        return pages >= 4 and seen == len(ids), f"Máy mới kéo với limit=2: {pages} trang, thấy {seen}/{len(ids)} sinh viên"
    case("C12", "Máy mới kéo dữ liệu phân trang (limit=2) → không sót", "Thấy đủ 7/7", "TV3", c12)

    def c13():
        sync_all(devs)
        ref = devs[0].students(tag)
        diff = [d.name for d in devs if d.students(tag) != ref]
        missing = [(d.name, u[:8]) for d in devs for u in tracked if u not in d.checkin_uuids()]
        pend = [d.name for d in devs if d.outbox]
        return (not diff and not missing and not pend,
                f"Máy lệch dữ liệu sinh viên={diff or 'không'}; thiếu điểm danh={missing or 'không'}; còn hàng đợi={pend or 'không'}")
    case("C13", "Cuối buổi: tất cả thiết bị có dữ liệu giống hệt nhau", "Không máy nào lệch", "TV3", c13)
    return cl


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="http://localhost:5000", help="Địa chỉ server (mặc định http://localhost:5000)")
    p.add_argument("--devices", type=int, default=4, help="Số thiết bị mô phỏng, từ 3 đến 6")
    p.add_argument("--email", default="admin@hkdn.edu.vn")
    p.add_argument("--password", default="admin123")
    p.add_argument("--out", default="checklist_nghiem_thu.csv")
    a = p.parse_args()
    if not 3 <= a.devices <= 6:
        sys.exit("--devices phải từ 3 đến 6")
    api = Api(a.base, a.email, a.password)
    cl = run(api, a.devices)
    cl.save(a.out, a.devices)
    ok = sum(1 for r in cl.rows if r[4] == "ĐẠT")
    known = sum(1 for r in cl.rows if r[4].startswith("KHÔNG ĐẠT (lỗi"))
    bad = len(cl.failed())
    print(f"\nTổng: {len(cl.rows)} ca | đạt {ok} | lỗi đã biết {known} | lỗi mới/lỗi chạy {bad}")
    print(f"Đã lưu: {a.out}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
