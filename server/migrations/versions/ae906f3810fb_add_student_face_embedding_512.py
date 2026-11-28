"""add student face embedding 512"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = 'ae906f3810fb'
down_revision = '041651200e8e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'students',
        sa.Column(
            'face_embedding_512',
            Vector(512),
            nullable=True
        )
    )


def downgrade():
    op.drop_column(
        'students',
        'face_embedding_512'
    )