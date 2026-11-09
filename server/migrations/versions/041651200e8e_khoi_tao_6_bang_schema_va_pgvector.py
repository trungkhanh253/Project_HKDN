"""Khoi tao 6 bang schema va pgvector theo chuan schema.md

Revision ID: 041651200e8e
Revises: 
Create Date: 2026-11-07 17:21:36.651663

"""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy

# revision identifiers, used by Alembic.
revision = '041651200e8e'
down_revision = None
branch_labels = None
depends_on = None

TABLES = [
    'admin',
    'subjects',
    'students',
    'enrollments',
    'checkin_history',
    'email_recipients',
]


def upgrade():
    # 1. Bật extension pgvector
    op.execute('CREATE EXTENSION IF NOT EXISTS vector;')

    # 2. Tạo 1 sequence chung cho toàn bộ 6 bảng
    op.execute('CREATE SEQUENCE IF NOT EXISTS global_sync_seq START 1;')

    # 3. Tạo trigger function tự động tăng seq và cập nhật updated_at khi INSERT hoặc UPDATE
    op.execute("""
    CREATE OR REPLACE FUNCTION bump_sync_metadata()
    RETURNS TRIGGER AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            IF NEW.seq IS NULL THEN
                NEW.seq := nextval('global_sync_seq');
            ELSE
                PERFORM setval('global_sync_seq', GREATEST(NEW.seq, COALESCE((SELECT last_value FROM global_sync_seq WHERE is_called), 0)), true);
            END IF;
            IF NEW.updated_at IS NULL THEN
                NEW.updated_at := CURRENT_TIMESTAMP;
            END IF;
        ELSIF TG_OP = 'UPDATE' THEN
            NEW.seq := nextval('global_sync_seq');
            IF NEW.seq <= OLD.seq THEN
                NEW.seq := OLD.seq + 1;
                PERFORM setval('global_sync_seq', NEW.seq, true);
            END IF;
            IF NEW.updated_at IS NULL OR NEW.updated_at = OLD.updated_at THEN
                NEW.updated_at := CURRENT_TIMESTAMP;
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)

    # 4. Bảng admin
    op.create_table(
        'admin',
        sa.Column('admin_id', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('date_of_birth', sa.String(length=50), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('gender', sa.String(length=50), nullable=True),
        sa.Column('photo_path', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('role', sa.String(length=50), server_default='ADMIN', nullable=False),
        sa.Column('admin_code', sa.String(length=100), nullable=True),
        sa.Column('reset_token', sa.String(length=255), nullable=True),
        sa.Column('expire_at', sa.BigInteger(), nullable=True),
        sa.Column('is_first_login', sa.Integer(), server_default='1', nullable=True),
        sa.Column('has_iris', sa.Integer(), server_default='0', nullable=True),
        sa.Column('face_embedding', pgvector.sqlalchemy.Vector(dim=192), nullable=True),
        sa.Column('uuid', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('seq', sa.BigInteger(), server_default=sa.text("nextval('global_sync_seq')"), nullable=False),
        sa.PrimaryKeyConstraint('admin_id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('uuid'),
        sa.UniqueConstraint('seq'),
    )
    with op.batch_alter_table('admin', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_admin_seq'), ['seq'], unique=False)

    # 5. Bảng subjects
    op.create_table(
        'subjects',
        sa.Column('subject_id', sa.String(length=255), nullable=False),
        sa.Column('subject_name', sa.String(length=255), nullable=False),
        sa.Column('time_slot', sa.String(length=255), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('instructor_id', sa.String(length=255), nullable=True),
        sa.Column('subject_status', sa.String(length=50), server_default='UNASSIGNED', nullable=False),
        sa.Column('created_at', sa.String(length=50), nullable=True),
        sa.Column('semester_start_date', sa.String(length=50), nullable=True),
        sa.Column('semester_end_date', sa.String(length=50), nullable=True),
        sa.Column('uuid', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('seq', sa.BigInteger(), server_default=sa.text("nextval('global_sync_seq')"), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['admin.admin_id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['instructor_id'], ['admin.admin_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('subject_id'),
        sa.UniqueConstraint('uuid'),
        sa.UniqueConstraint('seq'),
    )
    with op.batch_alter_table('subjects', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_subjects_seq'), ['seq'], unique=False)

    # 6. Bảng students
    op.create_table(
        'students',
        sa.Column('student_id', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('photo_path', sa.Text(), nullable=True),
        sa.Column('checkin_password', sa.String(length=255), nullable=True),
        sa.Column('face_embedding', pgvector.sqlalchemy.Vector(dim=192), nullable=True),
        sa.Column('uuid', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('seq', sa.BigInteger(), server_default=sa.text("nextval('global_sync_seq')"), nullable=False),
        sa.PrimaryKeyConstraint('student_id'),
        sa.UniqueConstraint('uuid'),
        sa.UniqueConstraint('seq'),
    )
    with op.batch_alter_table('students', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_students_seq'), ['seq'], unique=False)

    # 7. Bảng enrollments
    op.create_table(
        'enrollments',
        sa.Column('student_id', sa.String(length=255), nullable=False),
        sa.Column('subject_id', sa.String(length=255), nullable=False),
        sa.Column('enrollment_status', sa.String(length=50), nullable=True),
        sa.Column('uuid', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('seq', sa.BigInteger(), server_default=sa.text("nextval('global_sync_seq')"), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['students.student_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.subject_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('student_id', 'subject_id'),
        sa.UniqueConstraint('uuid'),
        sa.UniqueConstraint('seq'),
    )
    with op.batch_alter_table('enrollments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_enrollments_seq'), ['seq'], unique=False)

    # 8. Bảng checkin_history
    op.create_table(
        'checkin_history',
        sa.Column('checkin_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('student_id', sa.String(length=255), nullable=True),
        sa.Column('subject_id', sa.String(length=255), nullable=True),
        sa.Column('checkin_time', sa.String(length=50), nullable=True),
        sa.Column('checkin_date', sa.String(length=50), nullable=True),
        sa.Column('uuid', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('seq', sa.BigInteger(), server_default=sa.text("nextval('global_sync_seq')"), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['students.student_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.subject_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('checkin_id'),
        sa.UniqueConstraint('uuid'),
        sa.UniqueConstraint('seq'),
    )
    with op.batch_alter_table('checkin_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_checkin_history_seq'), ['seq'], unique=False)

    # 9. Bảng email_recipients
    op.create_table(
        'email_recipients',
        sa.Column('email_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('subject_id', sa.String(length=255), nullable=False),
        sa.Column('email_address', sa.String(length=255), nullable=False),
        sa.Column('recipient_name', sa.String(length=255), nullable=True),
        sa.Column('added_date', sa.String(length=50), nullable=True),
        sa.Column('is_selected', sa.Boolean(), server_default=sa.text('TRUE'), nullable=True),
        sa.Column('uuid', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('seq', sa.BigInteger(), server_default=sa.text("nextval('global_sync_seq')"), nullable=False),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.subject_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('email_id'),
        sa.UniqueConstraint('subject_id', 'email_address', name='unique_subject_email'),
        sa.UniqueConstraint('uuid'),
        sa.UniqueConstraint('seq'),
    )
    with op.batch_alter_table('email_recipients', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_email_recipients_seq'), ['seq'], unique=False)

    # 10. Gắn trigger BEFORE INSERT OR UPDATE cho cả 6 bảng
    for tbl in TABLES:
        op.execute(f"""
        CREATE TRIGGER trg_{tbl}_sync_metadata
        BEFORE INSERT OR UPDATE ON {tbl}
        FOR EACH ROW EXECUTE FUNCTION bump_sync_metadata();
        """)


def downgrade():
    for tbl in reversed(TABLES):
        op.execute(f'DROP TRIGGER IF EXISTS trg_{tbl}_sync_metadata ON {tbl};')

    with op.batch_alter_table('email_recipients', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_email_recipients_seq'))
    op.drop_table('email_recipients')

    with op.batch_alter_table('checkin_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_checkin_history_seq'))
    op.drop_table('checkin_history')

    with op.batch_alter_table('enrollments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_enrollments_seq'))
    op.drop_table('enrollments')

    with op.batch_alter_table('students', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_students_seq'))
    op.drop_table('students')

    with op.batch_alter_table('subjects', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_subjects_seq'))
    op.drop_table('subjects')

    with op.batch_alter_table('admin', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_admin_seq'))
    op.drop_table('admin')

    op.execute('DROP FUNCTION IF EXISTS bump_sync_metadata();')
    op.execute('DROP SEQUENCE IF EXISTS global_sync_seq;')
