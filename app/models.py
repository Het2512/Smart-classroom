# pyrefly: ignore [missing-import]
from flask_login import UserMixin
from datetime import datetime
from app.extensions import db

SEMESTERS = ['Sem 1', 'Sem 2', 'Sem 3', 'Sem 4', 'Sem 5', 'Sem 6', 'Sem 7', 'Sem 8']
BATCHES   = ['A', 'B', 'C']


class SystemConfig(db.Model):
    id    = db.Column(db.Integer, primary_key=True)
    key   = db.Column(db.String(50),  unique=True, nullable=False)
    value = db.Column(db.String(200), nullable=False)


class User(UserMixin, db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(100), nullable=False)
    email    = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200))
    plain_password = db.Column(db.String(200), nullable=True)
    role     = db.Column(db.String(20),  nullable=False)   # 'teacher' | 'student'
    # ── Student-only fields ────────────────────────────────────────────────
    semester = db.Column(db.String(20), nullable=True)   # e.g. 'Sem 3'
    batch    = db.Column(db.String(5),  nullable=True)   # 'A' | 'B' | 'C'


# ── Many-to-many: classroom <-> co-teachers ──────────────────────────────────
class ClassroomTeacher(db.Model):
    """Association table — tracks every teacher who can access a classroom."""
    __tablename__ = 'classroom_teacher'
    classroom_id = db.Column(db.Integer, db.ForeignKey('classroom.id'), primary_key=True)
    teacher_id   = db.Column(db.Integer, db.ForeignKey('user.id'),      primary_key=True)
    added_at     = db.Column(db.DateTime, default=datetime.utcnow)

    teacher = db.relationship('User', backref='taught_classrooms')


class Classroom(db.Model):
    """Represents a classroom like IT-Sem3 or CS-Sem5."""
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(200))
    semester    = db.Column(db.String(20), nullable=True)   # e.g. "Sem 1" … "Sem 8"
    teacher_id  = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    teacher     = db.relationship('User', backref='classrooms', foreign_keys=[teacher_id])
    co_teachers = db.relationship(
        'ClassroomTeacher',
        backref='classroom',
        cascade='all, delete-orphan',
        lazy=True
    )

    def get_students(self):
        """Return all students enrolled in this classroom's semester."""
        if not self.semester:
            return []
        return User.query.filter_by(role='student', semester=self.semester)\
                         .order_by(User.batch, User.name).all()

    def get_batch_students(self, batch):
        """Return students for a specific lab batch."""
        if not self.semester:
            return []
        return User.query.filter_by(role='student', semester=self.semester, batch=batch)\
                         .order_by(User.name).all()


class AllowedStudent(db.Model):
    """Legacy table — kept for backward-compat but no longer drives classroom membership."""
    id           = db.Column(db.Integer, primary_key=True)
    email        = db.Column(db.String(120), nullable=False)
    name         = db.Column(db.String(100))
    added_by     = db.Column(db.Integer, db.ForeignKey('user.id'))
    classroom_id = db.Column(db.Integer, db.ForeignKey('classroom.id'), nullable=True)


class Note(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    title        = db.Column(db.String(200), nullable=False)
    filename     = db.Column(db.String(200), nullable=False)
    uploaded_by  = db.Column(db.Integer, db.ForeignKey('user.id'))
    classroom_id = db.Column(db.Integer, db.ForeignKey('classroom.id'), nullable=True)
    upload_date  = db.Column(db.DateTime, default=datetime.utcnow)


class Notice(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    title        = db.Column(db.String(200), nullable=False)
    content      = db.Column(db.Text, nullable=False)
    posted_by    = db.Column(db.Integer, db.ForeignKey('user.id'))
    classroom_id = db.Column(db.Integer, db.ForeignKey('classroom.id'), nullable=True)
    posted_date  = db.Column(db.DateTime, default=datetime.utcnow)
    is_public    = db.Column(db.Boolean, default=False)


class Subject(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(100), nullable=False)
    code         = db.Column(db.String(20),  nullable=False)
    semester     = db.Column(db.String(20),  nullable=False)
    teacher_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    teacher   = db.relationship('User', backref='subjects_taught')


class Attendance(db.Model):
    """
    Records one student's attendance for one session.

    attendance_type:
        'lecture' — regular lecture for the whole semester
        'lab'     — lab session for a specific batch (A / B / C)

    Duplicate prevention is handled at the application layer
    (MySQL NULLs are NOT equal in UNIQUE constraints).
    """
    __tablename__ = 'attendance'

    id              = db.Column(db.Integer, primary_key=True)
    student_id      = db.Column(db.Integer, db.ForeignKey('user.id'),      nullable=False)
    classroom_id    = db.Column(db.Integer, db.ForeignKey('classroom.id'), nullable=True)
    subject_id      = db.Column(db.Integer, db.ForeignKey('subject.id'),   nullable=True)
    date            = db.Column(db.Date,    nullable=False, default=datetime.utcnow)
    status          = db.Column(db.String(20), nullable=False)           # 'Present' | 'Absent'
    attendance_type = db.Column(db.String(20), nullable=False, default='lecture')  # 'lecture' | 'lab'
    batch           = db.Column(db.String(5),  nullable=True)            # For lab: 'A' | 'B' | 'C'

    marked_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # audit: which teacher marked

    student    = db.relationship('User',      backref='attendance_records', foreign_keys=[student_id])
    subject    = db.relationship('Subject',   backref='att_records')
    classroom  = db.relationship('Classroom', backref='att_records')
    marker     = db.relationship('User',      foreign_keys=[marked_by])


class Timetable(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey('classroom.id'), nullable=False)
    subject_id   = db.Column(db.Integer, db.ForeignKey('subject.id'),   nullable=False)
    day_of_week  = db.Column(db.String(20), nullable=False)
    start_time   = db.Column(db.Time, nullable=False)
    end_time     = db.Column(db.Time, nullable=False)
    session_type = db.Column(db.String(20), nullable=False, default='lecture')  # 'lecture' | 'lab'
    batch        = db.Column(db.String(5),  nullable=True)   # only for lab: 'A'|'B'|'C'

    classroom = db.relationship('Classroom', backref=db.backref('timetable_slots', cascade='all, delete-orphan'))
    subject   = db.relationship('Subject',   backref=db.backref('timetable_slots', cascade='all, delete-orphan'))


class Exam(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    title        = db.Column(db.String(200), nullable=False)
    semester     = db.Column(db.String(20), nullable=False)
    subject_id   = db.Column(db.Integer, db.ForeignKey('subject.id'),   nullable=False)
    date         = db.Column(db.Date,    nullable=False)
    total_marks  = db.Column(db.Integer, nullable=False)
    is_published = db.Column(db.Boolean, default=False)

    subject   = db.relationship('Subject',   backref=db.backref('exams', cascade='all, delete-orphan'))


class ExamResult(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    exam_id        = db.Column(db.Integer, db.ForeignKey('exam.id'),  nullable=False)
    student_id     = db.Column(db.Integer, db.ForeignKey('user.id'),  nullable=False)
    marks_obtained = db.Column(db.Integer, nullable=False)
    remarks        = db.Column(db.String(200))

    exam    = db.relationship('Exam', backref=db.backref('results', cascade='all, delete-orphan'))
    student = db.relationship('User', backref='exam_results')
