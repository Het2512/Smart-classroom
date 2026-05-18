from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from app.models import AllowedStudent, Classroom, Note, Notice, Timetable, Exam, ExamResult, Attendance, Subject, User
from app.extensions import db

student_bp = Blueprint('student', __name__)

@student_bp.route('/student/dashboard')
@login_required
def student_dashboard():
    if current_user.role != 'student':
        return redirect(url_for('main.index'))

    classroom = None
    notes     = []
    class_notices  = []
    public_notices = Notice.query.filter_by(is_public=True)\
                                 .order_by(Notice.posted_date.desc()).all()

    # Primary: look up classroom by student's semester (new system)
    if current_user.semester:
        classroom = Classroom.query.filter_by(semester=current_user.semester).first()

    # Fallback: legacy AllowedStudent table
    if not classroom:
        allowed = AllowedStudent.query.filter_by(email=current_user.email).first()
        if allowed and allowed.classroom_id:
            classroom = db.session.get(Classroom, allowed.classroom_id)

    if classroom:
        notes         = Note.query.filter_by(classroom_id=classroom.id)\
                                  .order_by(Note.upload_date.desc()).all()
        class_notices = Notice.query.filter_by(classroom_id=classroom.id)\
                                    .order_by(Notice.posted_date.desc()).all()

    seen_ids = set()
    all_notices = []
    for n in class_notices + public_notices:
        if n.id not in seen_ids:
            seen_ids.add(n.id)
            all_notices.append(n)

    return render_template(
        'student_dashboard.html',
        notes=notes,
        notices=all_notices,
        class_notices=class_notices,
        public_notices=public_notices,
        classroom=classroom,
    )

@student_bp.route('/student/timetable')
@login_required
def timetable():
    if current_user.role != 'student':
        return redirect(url_for('main.index'))
        
    allowed = AllowedStudent.query.filter_by(email=current_user.email).first()
    slots = []
    if allowed and allowed.classroom_id:
        slots = Timetable.query.filter_by(classroom_id=allowed.classroom_id).order_by(Timetable.start_time).all()
        
    # Group by day
    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    timetable_map = {day: [] for day in days_order}
    for slot in slots:
        if slot.day_of_week in timetable_map:
            timetable_map[slot.day_of_week].append(slot)
            
    return render_template('student/timetable.html', timetable_map=timetable_map, days_order=days_order)

@student_bp.route('/student/exams')
@login_required
def exams():
    if current_user.role != 'student':
        return redirect(url_for('main.index'))
        
    results = []
    semester = current_user.semester
    
    # Fallback to AllowedStudent if semester is not set
    if not semester:
        allowed = AllowedStudent.query.filter_by(email=current_user.email).first()
        if allowed and allowed.classroom_id:
            classroom = db.session.get(Classroom, allowed.classroom_id)
            if classroom:
                semester = classroom.semester
                
    if semester:
        # Get published exams for this semester
        published_exams = Exam.query.filter_by(semester=semester, is_published=True).all()
        exam_ids = [e.id for e in published_exams]
        
        # Get results for the student
        if exam_ids:
            results = ExamResult.query.filter(
                ExamResult.exam_id.in_(exam_ids), 
                ExamResult.student_id == current_user.id
            ).all()
            
    return render_template('student/exams.html', results=results)


@student_bp.route('/student/attendance')
@login_required
def my_attendance():
    if current_user.role != 'student':
        return redirect(url_for('main.index'))

    # Find the student's classroom via their semester (primary source of truth)
    classroom = None
    if current_user.semester:
        classroom = Classroom.query.filter_by(semester=current_user.semester).first()

    # Fallback: legacy AllowedStudent table
    if not classroom:
        allowed = AllowedStudent.query.filter_by(email=current_user.email).first()
        if allowed and allowed.classroom_id:
            classroom = db.session.get(Classroom, allowed.classroom_id)

    subject_stats = []   # list of dicts: {subject, present, total, pct, is_defaulter}

    if classroom:
        records = Attendance.query.filter_by(
            student_id=current_user.id,
            classroom_id=classroom.id,
        ).all()

        # Group by subject_id
        stats_map = {}   # subject_id -> {subject, present, total}
        for rec in records:
            sid = rec.subject_id
            if sid not in stats_map:
                stats_map[sid] = {'subject': rec.subject, 'present': 0, 'total': 0}
            stats_map[sid]['total'] += 1
            if rec.status == 'Present':
                stats_map[sid]['present'] += 1

        for sid, data in stats_map.items():
            total   = data['total']
            present = data['present']
            pct     = round((present / total) * 100, 1) if total > 0 else 0.0
            subject_stats.append({
                'subject':      data['subject'],
                'present':      present,
                'absent':       total - present,
                'total':        total,
                'pct':          pct,
                'is_defaulter': pct < 75.0,
            })

        # Sort: defaulters first, then by subject name
        subject_stats.sort(key=lambda x: (not x['is_defaulter'], x['subject'].name if x['subject'] else ''))

    return render_template(
        'student/attendance.html',
        classroom=classroom,
        subject_stats=subject_stats,
    )
