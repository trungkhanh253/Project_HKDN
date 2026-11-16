from app import db
from app.models import Admin
from app.repositories.base_repository import BaseRepository
import sqlalchemy as sa

class AdminRepository(BaseRepository):
    @staticmethod
    def get_by_id(admin_id: str, include_deleted: bool = False):
        query = Admin.query.filter_by(admin_id=admin_id)
        if not include_deleted:
            query = query.filter(Admin.deleted_at.is_(None))
        return query.first()

    @staticmethod
    def get_by_email(email: str, include_deleted: bool = False):
        query = Admin.query.filter_by(email=email)
        if not include_deleted:
            query = query.filter(Admin.deleted_at.is_(None))
        return query.first()

    @staticmethod
    def list_paginated(q: str = None, sort: str = None, limit: int = 10, offset: int = 0):
        query = Admin.query.filter(Admin.deleted_at.is_(None))

        if q and q.strip():
            kw = f"%{q.strip()}%"
            query = query.filter(
                sa.or_(
                    Admin.admin_id.ilike(kw),
                    Admin.email.ilike(kw),
                    Admin.full_name.ilike(kw),
                    Admin.phone.ilike(kw),
                    Admin.admin_code.ilike(kw),
                )
            )

        total = query.count()

        if sort:
            parts = sort.split(":")
            field_name = parts[0].strip().lower()
            order_dir = parts[1].strip().lower() if len(parts) > 1 else "asc"
            col = getattr(Admin, field_name, None)
            if col is not None:
                query = query.order_by(col.desc() if order_dir == "desc" else col.asc())
            else:
                query = query.order_by(Admin.admin_id.asc())
        else:
            query = query.order_by(Admin.admin_id.asc())

        items = query.offset(offset).limit(limit).all()
        return items, total
