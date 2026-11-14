import os
from pathlib import Path
import yaml
from flask import Flask, Response, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.exceptions import HTTPException

db = SQLAlchemy()
migrate = Migrate()


def _load_openapi_text() -> str:
    candidates = [
        Path("/docs/openapi.yml"),
        Path(__file__).resolve().parent.parent.parent / "docs" / "openapi.yml",
        Path(__file__).resolve().parent / "openapi.yml",
    ]
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError("Không tìm thấy tệp đặc tả openapi.yml.")


SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Project_HKDN API Documentation (Swagger UI)</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui.css" />
  <style>
    body { margin: 0; background: #fafafa; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui-bundle.js"></script>
  <script>
    window.onload = function() {
      window.ui = SwaggerUIBundle({
        url: "/openapi.json",
        dom_id: "#swagger-ui",
        deepLinking: true,
        persistAuthorization: true
      });
    };
  </script>
</body>
</html>
"""


def create_app():
    app = Flask(__name__)

    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:kiet2201@127.0.0.1:5432/attendance_server",
    )

    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    secret_key = os.getenv("SECRET_KEY", "").strip()

    if not secret_key or secret_key == "hkdn-default-secret-key-2026":
        raise RuntimeError("SECRET_KEY chưa được cấu hình an toàn.")

    app.config["SECRET_KEY"] = secret_key

    # CORS - Cho phép nhóm Web truy cập Flask API
    cors_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]

    CORS(
        app,
        resources={
            r"/*": {
                "origins": cors_origins,
            }
        },
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        supports_credentials=False,
    )

    db.init_app(app)

    migrate.init_app(app, db)  

    # Import models để Flask-Migrate / Alembic nhận diện đầy đủ 6 bảng
    from app import models  # noqa: F401
    from app.routes import api_bp

    # Đăng ký blueprint ở cả /api/v1 (chuẩn có version) và gốc / (tương thích ngược)
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(api_bp, name="api_root", url_prefix="")

    @app.route("/openapi.yml", methods=["GET"])
    @app.route("/api/v1/openapi.yml", methods=["GET"])
    def serve_openapi_yaml():
        return Response(_load_openapi_text(), mimetype="application/yaml")

    @app.route("/openapi.json", methods=["GET"])
    @app.route("/api/v1/openapi.json", methods=["GET"])
    def serve_openapi_json():
        spec = yaml.safe_load(_load_openapi_text())
        return jsonify(spec), 200

    @app.route("/apidocs", methods=["GET"])
    @app.route("/apidocs/", methods=["GET"])
    @app.route("/swagger", methods=["GET"])
    @app.route("/docs", methods=["GET"])
    def serve_swagger_ui():
        return Response(SWAGGER_UI_HTML, mimetype="text/html")

    # Xử lý lỗi chuẩn JSON {"error": {"code": ..., "message": ...}}
    @app.errorhandler(400)
    def handle_400(err):
        return (
            jsonify(
                {
                    "error": {
                        "code": "BAD_REQUEST",
                        "message": getattr(err, "description", "Yêu cầu không hợp lệ."),
                    }
                }
            ),
            400,
        )

    @app.errorhandler(401)
    def handle_401(err):
        return (
            jsonify(
                {
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": getattr(err, "description", "Chưa xác thực hoặc token không hợp lệ."),
                    }
                }
            ),
            401,
        )

    @app.errorhandler(404)
    def handle_404(err):
        return (
            jsonify(
                {
                    "error": {
                        "code": "NOT_FOUND",
                        "message": getattr(err, "description", "Đường dẫn hoặc tài nguyên không tồn tại."),
                    }
                }
            ),
            404,
        )

    @app.errorhandler(405)
    def handle_405(err):
        return (
            jsonify(
                {
                    "error": {
                        "code": "METHOD_NOT_ALLOWED",
                        "message": getattr(err, "description", "Phương thức HTTP không được phép."),
                    }
                }
            ),
            405,
        )

    @app.errorhandler(500)
    def handle_500(err):
        return (
            jsonify(
                {
                    "error": {
                        "code": "INTERNAL_SERVER_ERROR",
                        "message": "Lỗi hệ thống nội bộ trên Server.",
                    }
                }
            ),
            500,
        )

    @app.cli.command("seed-admin")
    def seed_admin_command():
        """Tạo sẵn tài khoản Super Admin và Admin mẫu phục vụ kiểm thử."""
        from seed_admin import seed_default_admins

        seed_default_admins()
        print("Đã khởi tạo tài khoản Admin mẫu thành công.")

    @app.cli.command("verify-phase2")
    def verify_phase2_command():
        """Kiểm tra toàn bộ hạ tầng Giai đoạn 2: PostgreSQL, pgvector(192), 6 bảng & Trigger seq."""
        import sqlalchemy as sa

        ext = db.session.execute(
            sa.text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
        print(f"[1] Extension pgvector: {'OK (v' + str(ext) + ')' if ext else 'MISSING'}")

        seq_exists = db.session.execute(
            sa.text("SELECT to_regclass('public.global_sync_seq')")
        ).scalar()
        print(f"[2] Sequence global_sync_seq: {'OK' if seq_exists else 'MISSING'}")

        tables = [
            "admin",
            "subjects",
            "students",
            "enrollments",
            "checkin_history",
            "email_recipients",
        ]
        for t in tables:
            reg = db.session.execute(
                sa.text("SELECT to_regclass(:tbl)"), {"tbl": f"public.{t}"}
            ).scalar()
            print(f"    - Bảng {t:<18}: {'OK' if reg else 'MISSING'}")

        vec_type = db.session.execute(
            sa.text(
                "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                "WHERE a.attrelid = 'students'::regclass AND a.attname = 'face_embedding'"
            )
        ).scalar()
        print(f"[3] Kiểu dữ liệu face_embedding: {vec_type}")


    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "attendance-server"
        }, 200        
        
         

    return app

