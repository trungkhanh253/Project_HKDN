"""
bench_vector_pull.py  –  TV5 Nguyễn Minh Tuyên
Đo kích thước và thời gian pull khi có vector khuôn mặt (Task 2).

Chạy:
    docker compose exec api python bench_vector_pull.py

Kết quả in ra: thời gian (ms), kích thước response (KB), số bản ghi.
Nếu > 2000ms → đề xuất giảm limit khi kéo kèm vector.
"""
import os
import sys
import time
import uuid
import json
import requests

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:5000").rstrip("/")
API_V1   = f"{BASE_URL}/api/v1"

SUPER_EMAIL    = "admin@hkdn.edu.vn"
SUPER_PASSWORD = "admin123"
NUM_STUDENTS   = 500   # số sinh viên cần đo
VECTOR_192     = [round(0.001 * i, 4) for i in range(192)]
BATCH_SIZE     = 50    # đẩy từng batch để tránh timeout


def login():
    r = requests.post(f"{API_V1}/auth/login",
                      json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD}, timeout=5)
    if r.status_code != 200:
        print(f"[LỖI] Đăng nhập thất bại: {r.text}")
        sys.exit(1)
    token = r.json()["access_token"]
    print(f"[OK] Đăng nhập thành công")
    return {"Authorization": f"Bearer {token}"}


def push_students(headers, n=NUM_STUDENTS):
    """Tạo n sinh viên có vector, trả về danh sách student_id."""
    print(f"[...] Đang tạo {n} sinh viên kèm vector (batch {BATCH_SIZE})...")
    ids = []
    for start in range(0, n, BATCH_SIZE):
        batch = []
        for _ in range(min(BATCH_SIZE, n - start)):
            sid = f"SV_BN_{uuid.uuid4().hex[:8].upper()}"
            ids.append(sid)
            batch.append({
                "student_id": sid,
                "full_name": f"Bench Student {sid}",
                "email": f"{sid.lower()}@bench.com",
                "face_embedding": VECTOR_192,
                "checkin_password": "pbkdf2_sha256$260000$salt$hash==",
                "uuid": str(uuid.uuid4()),
                "updated_at": "2026-11-22T00:00:00Z",
            })
        r = requests.post(f"{API_V1}/sync/push", headers=headers,
                          json={"students": batch}, timeout=30)
        if r.status_code != 200:
            print(f"  [CẢNH BÁO] Push batch {start}-{start+len(batch)} lỗi: {r.status_code}")
        else:
            print(f"  [OK] Đã push {start + len(batch)}/{n} sinh viên")
    return ids


def measure_pull(headers, label="pull", limit=100):
    """Đo thời gian + kích thước của 1 lần sync/pull."""
    t0 = time.monotonic()
    r = requests.get(f"{API_V1}/sync/pull", headers=headers,
                     params={"after_seq": 0, "limit": limit}, timeout=60)
    elapsed_ms = (time.monotonic() - t0) * 1000
    size_kb    = len(r.content) / 1024

    if r.status_code != 200:
        print(f"  [LỖI] {label}: HTTP {r.status_code}")
        return None

    data        = r.json()
    changes     = data.get("changes", {})
    num_students = 0
    if isinstance(changes, dict):
        num_students = len(changes.get("students", []))
    elif isinstance(changes, list):
        num_students = sum(1 for c in changes if c.get("table") == "students")

    has_more = data.get("has_more", False)
    return {
        "label":        label,
        "limit":        limit,
        "elapsed_ms":   round(elapsed_ms, 1),
        "size_kb":      round(size_kb, 1),
        "num_students": num_students,
        "has_more":     has_more,
    }


def print_result(res):
    if res is None:
        return
    status = "⚠️  CHẬM" if res["elapsed_ms"] > 2000 else "✅ OK"
    print(f"\n  {'='*55}")
    print(f"  Kịch bản   : {res['label']}")
    print(f"  limit      : {res['limit']}")
    print(f"  Thời gian  : {res['elapsed_ms']} ms  {status}")
    print(f"  Kích thước : {res['size_kb']} KB")
    print(f"  Sinh viên  : {res['num_students']} bản ghi")
    print(f"  has_more   : {res['has_more']}")
    print(f"  {'='*55}")


def recommend(results):
    print("\n📊 KHUYẾN NGHỊ:")
    for r in results:
        if r is None:
            continue
        if r["elapsed_ms"] > 2000:
            print(f"  ⚠️  limit={r['limit']} → {r['elapsed_ms']}ms > 2s, nên giảm limit xuống 50 khi kèm vector")
        else:
            print(f"  ✅ limit={r['limit']} → {r['elapsed_ms']}ms, chấp nhận được")


def main():
    print("=" * 60)
    print("  BENCHMARK: Pull 500 bản ghi kèm face_embedding (192 chiều)")
    print("=" * 60)

    headers = login()

    # Tạo 500 sinh viên kèm vector
    push_students(headers, NUM_STUDENTS)

    print("\n[...] Đang đo thời gian pull...")

    results = []

    # Kịch bản 1: limit=100 (mặc định)
    res1 = measure_pull(headers, label="limit=100 (mặc định)", limit=100)
    print_result(res1)
    results.append(res1)

    # Kịch bản 2: limit=50
    res2 = measure_pull(headers, label="limit=50", limit=50)
    print_result(res2)
    results.append(res2)

    # Kịch bản 3: limit=200
    res3 = measure_pull(headers, label="limit=200", limit=200)
    print_result(res3)
    results.append(res3)

    recommend(results)

    print("\n✅ Benchmark hoàn thành!")


if __name__ == "__main__":
    main()
