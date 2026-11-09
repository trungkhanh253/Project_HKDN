import os
from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.exceptions import HTTPException

db = SQLAlchemy()
migrate = Migrate()


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
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "hkdn-default-secret-key-2026")

    db.init_app(app)
    migrate.init_app(app, db)

    # Import models để Flask-Migrate / Alembic nhận diện đầy đủ 6 bảng
    from app import models  # noqa: F401
    from app.routes import api_bp

    # Đăng ký blueprint ở cả /api/v1 (chuẩn có version) và gốc / (tương thích ngược)
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(api_bp, name="api_root", url_prefix="")

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

    return app
