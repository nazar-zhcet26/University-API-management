"""
scripts/seed.py
---------------
Populate the database with realistic test data.

Run this after applying migrations:
    python scripts/seed.py

This creates:
- 3 programs (CS, Business, Engineering)
- 6 faculty members
- 50 students spread across programs
- 12 courses across programs and semesters
- ~80 enrollments
- 10 books with borrowings
- User accounts for testing all roles

Test credentials after seeding:
    Admin:     admin@university.ac.ae     / Admin@1234
    Student:   student1@university.ac.ae  / Student@1234
    Faculty:   faculty1@university.ac.ae  / Faculty@1234
    Librarian: librarian@university.ac.ae / Librarian@1234
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.security import hash_password
from app.models.models import (
    Program, Student, Faculty, Course, Enrollment, Book, Borrowing, User
)
from datetime import date, timedelta
import uuid

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/university_db"
)

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def uid():
    return str(uuid.uuid4())


async def seed():
    async with SessionLocal() as db:
        print("🌱 Seeding database...")

        # ── Programs ──────────────────────────────────────────────────────────
        cs = Program(id=uid(), code="CS-BSC", name="Bachelor of Science in Computer Science",
                     department="computer_science", duration_years=4)
        business = Program(id=uid(), code="BUS-BSC", name="Bachelor of Business Administration",
                           department="business", duration_years=3)
        engineering = Program(id=uid(), code="ENG-BSC", name="Bachelor of Engineering",
                              department="engineering", duration_years=4)
        db.add_all([cs, business, engineering])
        await db.flush()
        print(f"  ✅ Created 3 programs")

        # ── Faculty ───────────────────────────────────────────────────────────
        f1 = Faculty(id=uid(), first_name="Sarah", last_name="Ahmed",
                     email="s.ahmed@university.ac.ae", department="computer_science",
                     title="Associate Professor", specializations=["machine_learning", "nlp"],
                     office_number="B-204")
        f2 = Faculty(id=uid(), first_name="James", last_name="Wilson",
                     email="j.wilson@university.ac.ae", department="computer_science",
                     title="Professor", specializations=["algorithms", "systems"],
                     office_number="B-201")
        f3 = Faculty(id=uid(), first_name="Fatima", last_name="Al-Hassan",
                     email="f.alhassan@university.ac.ae", department="business",
                     title="Assistant Professor", specializations=["finance", "economics"],
                     office_number="C-110")
        f4 = Faculty(id=uid(), first_name="David", last_name="Chen",
                     email="d.chen@university.ac.ae", department="engineering",
                     title="Professor", specializations=["civil_engineering", "structures"],
                     office_number="A-305")
        f5 = Faculty(id=uid(), first_name="Aisha", last_name="Mohammed",
                     email="a.mohammed@university.ac.ae", department="computer_science",
                     title="Lecturer", specializations=["web_development", "databases"],
                     office_number="B-208")
        f6 = Faculty(id=uid(), first_name="Robert", last_name="Taylor",
                     email="r.taylor@university.ac.ae", department="business",
                     title="Associate Professor", specializations=["marketing", "strategy"],
                     office_number="C-115")
        faculty_list = [f1, f2, f3, f4, f5, f6]
        db.add_all(faculty_list)
        await db.flush()
        print(f"  ✅ Created {len(faculty_list)} faculty members")

        # ── Students ──────────────────────────────────────────────────────────
        students = []
        first_names = ["Nazar", "Ali", "Omar", "Layla", "Sara", "Hassan", "Zara",
                       "Khalid", "Mia", "Ahmed", "Nour", "Tariq", "Hana", "Yusuf",
                       "Lina", "Faisal", "Dina", "Samir", "Rania", "Kareem"]
        last_names = ["Kamaal", "Al-Rashid", "Hassan", "Ibrahim", "Malik", "Ahmed",
                      "Khan", "Al-Farsi", "Mohammed", "Abdullah", "Nasser", "Saleh",
                      "Qasim", "Al-Ali", "Hussain", "Aziz", "Barakat", "Yousef",
                      "Mansour", "Al-Zaabi"]
        programs_pool = [cs, cs, cs, business, business, engineering]

        for i in range(50):
            prog = programs_pool[i % len(programs_pool)]
            fname = first_names[i % len(first_names)]
            lname = last_names[i % len(last_names)]
            student = Student(
                id=uid(),
                first_name=fname,
                last_name=lname,
                email=f"{fname.lower()}.{lname.lower().replace('-', '')}{i}@university.ac.ae",
                date_of_birth=date(2000 + (i % 5), (i % 12) + 1, (i % 28) + 1),
                program_id=prog.id,
                enrollment_year=2024 + (i % 2),
                status="active",
            )
            students.append(student)

        db.add_all(students)
        await db.flush()
        print(f"  ✅ Created {len(students)} students")

        # ── Courses ───────────────────────────────────────────────────────────
        courses = [
            Course(id=uid(), code="CS101", title="Introduction to Programming",
                   program_id=cs.id, credits=3, semester="fall_2026",
                   faculty_id=f5.id, max_capacity=40,
                   description="Fundamentals of programming using Python"),
            Course(id=uid(), code="CS201", title="Data Structures and Algorithms",
                   program_id=cs.id, credits=3, semester="fall_2026",
                   faculty_id=f2.id, max_capacity=35,
                   description="Core data structures and algorithm analysis"),
            Course(id=uid(), code="CS301", title="Machine Learning Fundamentals",
                   program_id=cs.id, credits=3, semester="fall_2026",
                   faculty_id=f1.id, max_capacity=30,
                   description="Introduction to supervised and unsupervised learning"),
            Course(id=uid(), code="CS302", title="Database Systems",
                   program_id=cs.id, credits=3, semester="spring_2026",
                   faculty_id=f5.id, max_capacity=35,
                   description="Relational databases, SQL, and database design"),
            Course(id=uid(), code="CS401", title="API Design and Management",
                   program_id=cs.id, credits=3, semester="fall_2026",
                   faculty_id=f2.id, max_capacity=25,
                   description="REST API design, security, and lifecycle management"),
            Course(id=uid(), code="BUS101", title="Principles of Management",
                   program_id=business.id, credits=3, semester="fall_2026",
                   faculty_id=f6.id, max_capacity=50,
                   description="Foundations of organizational management"),
            Course(id=uid(), code="BUS201", title="Financial Accounting",
                   program_id=business.id, credits=3, semester="fall_2026",
                   faculty_id=f3.id, max_capacity=45,
                   description="Fundamentals of financial accounting and reporting"),
            Course(id=uid(), code="BUS301", title="Strategic Marketing",
                   program_id=business.id, credits=3, semester="spring_2026",
                   faculty_id=f6.id, max_capacity=40,
                   description="Marketing strategy and consumer behavior"),
            Course(id=uid(), code="ENG101", title="Engineering Mathematics",
                   program_id=engineering.id, credits=4, semester="fall_2026",
                   faculty_id=f4.id, max_capacity=45,
                   description="Calculus, linear algebra, and differential equations"),
            Course(id=uid(), code="ENG201", title="Structural Analysis",
                   program_id=engineering.id, credits=3, semester="fall_2026",
                   faculty_id=f4.id, max_capacity=30,
                   description="Analysis of structural systems and materials"),
        ]
        db.add_all(courses)
        await db.flush()
        print(f"  ✅ Created {len(courses)} courses")

        # ── Enrollments ───────────────────────────────────────────────────────
        enrollments = []
        enrolled_pairs = set()
        for i, student in enumerate(students[:40]):  # enroll first 40 students
            # Each student gets 2-3 courses from their program
            student_program = student.program_id
            program_courses = [c for c in courses if c.program_id == student_program]
            for j, course in enumerate(program_courses[:3]):
                pair = (student.id, course.id)
                if pair not in enrolled_pairs and len([e for e in enrollments if e.course_id == course.id]) < course.max_capacity:
                    enrollments.append(Enrollment(
                        id=uid(),
                        course_id=course.id,
                        student_id=student.id,
                        status="active",
                    ))
                    enrolled_pairs.add(pair)

        db.add_all(enrollments)
        await db.flush()
        print(f"  ✅ Created {len(enrollments)} enrollments")

        # ── Books ─────────────────────────────────────────────────────────────
        books = [
            Book(id=uid(), title="Introduction to Algorithms", author="Thomas Cormen",
                 isbn="9780262033848", genre="computer_science", total_copies=5,
                 publisher="MIT Press", published_year=2009),
            Book(id=uid(), title="Clean Code", author="Robert Martin",
                 isbn="9780132350884", genre="computer_science", total_copies=4,
                 publisher="Prentice Hall", published_year=2008),
            Book(id=uid(), title="Designing Data-Intensive Applications", author="Martin Kleppmann",
                 isbn="9781449373320", genre="computer_science", total_copies=3,
                 publisher="O'Reilly", published_year=2017),
            Book(id=uid(), title="The Lean Startup", author="Eric Ries",
                 isbn="9780307887894", genre="business", total_copies=6,
                 publisher="Crown Business", published_year=2011),
            Book(id=uid(), title="Principles of Corporate Finance", author="Brealey Myers",
                 isbn="9781260565553", genre="business", total_copies=4,
                 publisher="McGraw Hill", published_year=2020),
            Book(id=uid(), title="Engineering Mechanics", author="Russell Hibbeler",
                 isbn="9780134870380", genre="engineering", total_copies=5,
                 publisher="Pearson", published_year=2018),
            Book(id=uid(), title="Python Crash Course", author="Eric Matthes",
                 isbn="9781593279288", genre="computer_science", total_copies=6,
                 publisher="No Starch Press", published_year=2019),
            Book(id=uid(), title="API Design Patterns", author="JJ Geewax",
                 isbn="9781617295850", genre="computer_science", total_copies=3,
                 publisher="Manning", published_year=2021),
        ]
        db.add_all(books)
        await db.flush()
        print(f"  ✅ Created {len(books)} books")

        # ── Borrowings ────────────────────────────────────────────────────────
        borrowings = []
        for i, student in enumerate(students[:10]):
            book = books[i % len(books)]
            borrowings.append(Borrowing(
                id=uid(),
                book_id=book.id,
                student_id=student.id,
                due_date=date.today() + timedelta(days=14),
                status="active",
            ))
        # Add some returned borrowings for history
        for i, student in enumerate(students[10:15]):
            book = books[(i + 3) % len(books)]
            borrowings.append(Borrowing(
                id=uid(),
                book_id=book.id,
                student_id=student.id,
                due_date=date.today() - timedelta(days=5),
                returned_at=date.today() - timedelta(days=2),
                status="returned",
            ))
        db.add_all(borrowings)
        await db.flush()
        print(f"  ✅ Created {len(borrowings)} borrowings")

        # ── Users (auth accounts) ─────────────────────────────────────────────
        users = [
            # Admin
            User(id=uid(), email="admin@university.ac.ae",
                 hashed_password=hash_password("Admin@1234"),
                 role="admin", is_active=True),
            # Librarian
            User(id=uid(), email="librarian@university.ac.ae",
                 hashed_password=hash_password("Librarian@1234"),
                 role="librarian", is_active=True),
            # Student user linked to first student
            User(id=uid(), email="student1@university.ac.ae",
                 hashed_password=hash_password("Student@1234"),
                 role="student", is_active=True, student_id=students[0].id),
            # Faculty user linked to first faculty
            User(id=uid(), email="faculty1@university.ac.ae",
                 hashed_password=hash_password("Faculty@1234"),
                 role="faculty", is_active=True, faculty_id=f1.id),
        ]
        db.add_all(users)
        await db.commit()
        print(f"  ✅ Created {len(users)} user accounts")

        print("\n✅ Seeding complete!")
        print("\n📋 Test credentials:")
        print("  Admin:     admin@university.ac.ae     / Admin@1234")
        print("  Student:   student1@university.ac.ae  / Student@1234")
        print("  Faculty:   faculty1@university.ac.ae  / Faculty@1234")
        print("  Librarian: librarian@university.ac.ae / Librarian@1234")


if __name__ == "__main__":
    asyncio.run(seed())
