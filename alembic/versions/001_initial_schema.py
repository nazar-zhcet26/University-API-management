"""
alembic/versions/001_initial_schema.py
---------------------------------------
Initial migration — creates all tables.

This is the first migration in the project.
Every subsequent schema change gets its own migration file.

Each migration has:
- upgrade(): applies the change (moving forward)
- downgrade(): reverses the change (rolling back)

Always implement downgrade() — it lets you roll back a bad deployment
without restoring from backup.

Revision ID: 001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001_initial_schema'
down_revision = None  # this is the first migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Create all tables in dependency order.
    Foreign keys mean you must create referenced tables first.
    Order: Programs → Students, Faculty → Courses → Enrollments, Books → Borrowings
    """

    # ── ENUMS ─────────────────────────────────────────────────────────────────
    # PostgreSQL enum types must be created before tables that use them
    user_role = postgresql.ENUM(
        'student', 'faculty', 'librarian', 'admin', 'service',
        name='user_role'
    )
    student_status = postgresql.ENUM(
        'active', 'inactive', 'graduated', 'suspended',
        name='student_status'
    )
    faculty_title = postgresql.ENUM(
        'Lecturer', 'Assistant Professor', 'Associate Professor', 'Professor',
        name='faculty_title'
    )
    enrollment_status = postgresql.ENUM(
        'active', 'dropped', 'completed',
        name='enrollment_status'
    )
    borrowing_status = postgresql.ENUM(
        'active', 'returned', 'overdue', 'lost',
        name='borrowing_status'
    )

    user_role.create(op.get_bind(), checkfirst=True)
    student_status.create(op.get_bind(), checkfirst=True)
    faculty_title.create(op.get_bind(), checkfirst=True)
    enrollment_status.create(op.get_bind(), checkfirst=True)
    borrowing_status.create(op.get_bind(), checkfirst=True)

    # ── PROGRAMS ──────────────────────────────────────────────────────────────
    op.create_table(
        'programs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('department', sa.String(100), nullable=False),
        sa.Column('duration_years', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_programs_code', 'programs', ['code'], unique=True)
    op.create_index('ix_programs_department', 'programs', ['department'])

    # ── FACULTY ───────────────────────────────────────────────────────────────
    op.create_table(
        'faculty',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('first_name', sa.String(100), nullable=False),
        sa.Column('last_name', sa.String(100), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('department', sa.String(100), nullable=False),
        sa.Column('title', postgresql.ENUM(name='faculty_title', create_type=False), nullable=False),
        sa.Column('specializations', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('office_number', sa.String(20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_faculty_email', 'faculty', ['email'], unique=True)
    op.create_index('ix_faculty_last_name', 'faculty', ['last_name'])
    op.create_index('ix_faculty_department', 'faculty', ['department'])

    # ── STUDENTS ──────────────────────────────────────────────────────────────
    op.create_table(
        'students',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('first_name', sa.String(100), nullable=False),
        sa.Column('last_name', sa.String(100), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('date_of_birth', sa.Date(), nullable=False),
        sa.Column('program_id', sa.String(36), sa.ForeignKey('programs.id'), nullable=False),
        sa.Column('enrollment_year', sa.Integer(), nullable=False),
        sa.Column('status', postgresql.ENUM(name='student_status', create_type=False),
                  nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_students_email', 'students', ['email'], unique=True)
    op.create_index('ix_students_last_name', 'students', ['last_name'])
    op.create_index('ix_students_program_id', 'students', ['program_id'])
    op.create_index('ix_students_status', 'students', ['status'])
    # Composite index — queries filtering by BOTH program AND status are common
    # (e.g. "all active students in CS program")
    # A composite index on (program_id, status) is much faster than two separate indexes
    op.create_index('ix_students_program_status', 'students', ['program_id', 'status'])

    # ── USERS ─────────────────────────────────────────────────────────────────
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('role', postgresql.ENUM(name='user_role', create_type=False), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('student_id', sa.String(36), sa.ForeignKey('students.id'), nullable=True),
        sa.Column('faculty_id', sa.String(36), sa.ForeignKey('faculty.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_role', 'users', ['role'])

    # ── COURSES ───────────────────────────────────────────────────────────────
    op.create_table(
        'courses',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('program_id', sa.String(36), sa.ForeignKey('programs.id'), nullable=False),
        sa.Column('credits', sa.Integer(), nullable=False),
        sa.Column('semester', sa.String(20), nullable=False),
        sa.Column('faculty_id', sa.String(36), sa.ForeignKey('faculty.id'), nullable=False),
        sa.Column('max_capacity', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_courses_program_id', 'courses', ['program_id'])
    op.create_index('ix_courses_faculty_id', 'courses', ['faculty_id'])
    op.create_index('ix_courses_semester', 'courses', ['semester'])
    # Composite: queries for "all courses in program X for semester Y" are common
    op.create_index('ix_courses_program_semester', 'courses', ['program_id', 'semester'])

    # ── ENROLLMENTS ───────────────────────────────────────────────────────────
    op.create_table(
        'enrollments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('course_id', sa.String(36), sa.ForeignKey('courses.id'), nullable=False),
        sa.Column('student_id', sa.String(36), sa.ForeignKey('students.id'), nullable=False),
        sa.Column('enrolled_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('status', postgresql.ENUM(name='enrollment_status', create_type=False),
                  nullable=False, server_default='active'),
    )
    op.create_index('ix_enrollments_course_id', 'enrollments', ['course_id'])
    op.create_index('ix_enrollments_student_id', 'enrollments', ['student_id'])
    # Unique constraint: a student can only be enrolled in a course once
    op.create_index(
        'uq_enrollments_student_course', 'enrollments',
        ['student_id', 'course_id'], unique=True
    )

    # ── BOOKS ─────────────────────────────────────────────────────────────────
    op.create_table(
        'books',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('author', sa.String(255), nullable=False),
        sa.Column('isbn', sa.String(20), nullable=False),
        sa.Column('genre', sa.String(100), nullable=False),
        sa.Column('total_copies', sa.Integer(), nullable=False),
        sa.Column('publisher', sa.String(255), nullable=True),
        sa.Column('published_year', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_books_isbn', 'books', ['isbn'], unique=True)
    op.create_index('ix_books_genre', 'books', ['genre'])
    op.create_index('ix_books_author', 'books', ['author'])
    # Full text search index on title — uses PostgreSQL's built-in GIN index
    # This is much faster than ILIKE '%search%' for text search
    op.execute("""
        CREATE INDEX ix_books_title_fts ON books
        USING gin(to_tsvector('english', title))
    """)

    # ── BORROWINGS ────────────────────────────────────────────────────────────
    op.create_table(
        'borrowings',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('book_id', sa.String(36), sa.ForeignKey('books.id'), nullable=False),
        sa.Column('student_id', sa.String(36), sa.ForeignKey('students.id'), nullable=False),
        sa.Column('borrowed_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('returned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', postgresql.ENUM(name='borrowing_status', create_type=False),
                  nullable=False, server_default='active'),
    )
    op.create_index('ix_borrowings_book_id', 'borrowings', ['book_id'])
    op.create_index('ix_borrowings_student_id', 'borrowings', ['student_id'])
    op.create_index('ix_borrowings_status', 'borrowings', ['status'])
    # Composite: "all active borrowings for this book" is the availability check
    op.create_index(
        'ix_borrowings_book_status', 'borrowings',
        ['book_id', 'status']
    )
    # Partial index — only indexes ACTIVE borrowings for the uniqueness check
    # Most borrowings are returned — this keeps the index small and fast
    op.execute("""
        CREATE UNIQUE INDEX uq_borrowings_active_student_book
        ON borrowings(student_id, book_id)
        WHERE status = 'active'
    """)


def downgrade() -> None:
    """
    Drop everything in reverse order.
    Tables with foreign keys must be dropped before the tables they reference.
    """
    op.drop_table('borrowings')
    op.drop_table('books')
    op.drop_table('enrollments')
    op.drop_table('courses')
    op.drop_table('users')
    op.drop_table('students')
    op.drop_table('faculty')
    op.drop_table('programs')

    # Drop enum types after tables
    postgresql.ENUM(name='borrowing_status').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='enrollment_status').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='faculty_title').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='student_status').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='user_role').drop(op.get_bind(), checkfirst=True)
