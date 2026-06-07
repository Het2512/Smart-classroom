from flask import Blueprint, request, render_template, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime as dt, date as date_type, time as time_type
from app.models import User, Classroom, ClassroomTeacher, AllowedStudent, Note, Notice, Attendance, Subject, Exam, ExamResult, Timetable, SEMESTERS, BATCHES
from app.extensions import db
import os

teacher_bp = Blueprint('teacher', __name__)


def _teacher_has_access(classroom):
    if classroom.teacher_id == current_user.id:
        return True
    if ClassroomTeacher.query.filter_by(
        classroom_id=classroom.id, teacher_id=current_user.id
    ).first() is not None:
        return True
    # Auto-grant access if the teacher has a subject in this classroom's semester
    if classroom.semester:
        if Subject.query.filter_by(teacher_id=current_user.id, semester=classroom.semester).first():
            return True
    return False


@teacher_bp.route('/teacher/dashboard')
@login_required
def teacher_dashboard():
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))

    owned       = Classroom.query.filter_by(teacher_id=current_user.id).all()
    co_links    = ClassroomTeacher.query.filter_by(teacher_id=current_user.id).all()
    co_room_ids = [l.classroom_id for l in co_links]
    co_rooms    = Classroom.query.filter(Classroom.id.in_(co_room_ids)).all() if co_room_ids else []
    
    # Get classrooms where the teacher teaches a subject (based on semester)
    subjects = Subject.query.filter_by(teacher_id=current_user.id).all()
    subject_sems = [s.semester for s in subjects if s.semester]
    subject_rooms = Classroom.query.filter(Classroom.semester.in_(subject_sems)).all() if subject_sems else []
    
    # Merge and deduplicate all accessible classrooms
    all_classrooms_set = {c.id: c for c in (owned + co_rooms + subject_rooms)}
    all_classrooms = list(all_classrooms_set.values())

    sem_map = {}
    for sem in SEMESTERS:
        rooms = [c for c in all_classrooms if c.semester == sem]
        if rooms:
            sem_map[sem] = rooms
    unassigned = [c for c in all_classrooms if not c.semester]

    notes          = Note.query.filter(Note.classroom_id.in_([c.id for c in all_classrooms])).all() if all_classrooms else []
    notices        = Notice.query.filter(Notice.classroom_id.in_([c.id for c in all_classrooms])).all() if all_classrooms else []
    global_notices = Notice.query.filter_by(posted_by=current_user.id, is_public=True)\
                                 .order_by(Notice.posted_date.desc()).all()

    return render_template(
        'teacher_dashboard.html',
        notes=notes, notices=notices,
        classrooms=all_classrooms,
        sem_map=sem_map,
        unassigned_classrooms=unassigned,
        global_notices=global_notices,
        semesters=SEMESTERS,
    )


@teacher_bp.route('/teacher/classroom/create', methods=['POST'])
@login_required
def create_classroom():
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))

    name        = request.form['name'].strip()
    description = request.form.get('description', '').strip()
    semester    = request.form.get('semester', '').strip()

    if not name:
        flash('Classroom name is required.', 'danger')
        return redirect(url_for('teacher.teacher_dashboard'))

    if Classroom.query.filter_by(name=name).first():
        flash(f'Classroom "{name}" already exists.', 'warning')
        return redirect(url_for('teacher.teacher_dashboard'))

    classroom = Classroom(
        name=name,
        description=description,
        semester=semester or None,
        teacher_id=current_user.id
    )
    db.session.add(classroom)
    db.session.commit()
    flash(f'Classroom "{name}" created!', 'success')
    return redirect(url_for('teacher.view_classroom', classroom_id=classroom.id))


@teacher_bp.route('/teacher/classroom/<int:classroom_id>')
@login_required
def view_classroom(classroom_id):
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))

    classroom = db.get_or_404(Classroom, classroom_id)
    if not _teacher_has_access(classroom):
        flash('You do not have access to this classroom.', 'danger')
        return redirect(url_for('teacher.teacher_dashboard'))

    is_owner = (classroom.teacher_id == current_user.id)

    # ── Students: auto-enrolled by semester ──────────────────────────────
    semester_students = classroom.get_students()   # uses Classroom.get_students()

    # Build per-batch student lists
    batch_students = {b: classroom.get_batch_students(b) for b in BATCHES}

    # student_id -> User map (for history display)
    student_user_map = {u.id: u for u in semester_students}

    notes    = Note.query.filter_by(classroom_id=classroom_id).order_by(Note.upload_date.desc()).all()
    notices  = Notice.query.filter_by(classroom_id=classroom_id).order_by(Notice.posted_date.desc()).all()
    attendance_records = Attendance.query.filter_by(classroom_id=classroom_id)\
                                         .order_by(Attendance.date.desc()).all()

    # Find teachers teaching a subject in this classroom's semester
    sem_subjects = Subject.query.filter_by(semester=classroom.semester).all() if classroom.semester else []
    subject_teacher_ids = {s.teacher_id for s in sem_subjects if s.teacher_id}

    # Find explicitly added co-teachers
    co_links          = ClassroomTeacher.query.filter_by(classroom_id=classroom_id).all()
    co_teacher_ids    = {l.teacher_id for l in co_links}

    # Merge teacher sets (excluding the owner)
    all_co_teacher_ids = (subject_teacher_ids | co_teacher_ids) - {classroom.teacher_id}
    co_teachers_users = User.query.filter(User.id.in_(all_co_teacher_ids)).all() if all_co_teacher_ids else []

    owner               = db.session.get(User, classroom.teacher_id)
    all_teachers_in_room = [owner] + co_teachers_users
    all_teachers        = User.query.filter_by(role='teacher').all()

    # Subjects assigned to the current teacher for this semester
    classroom_subjects = Subject.query.filter_by(
        semester=classroom.semester,
        teacher_id=current_user.id
    ).all()

    # ── Attendance summary: {student_id: {subject_id: {subject, present, total}}} ──
    attendance_summary = {}   # used by the Summary tab
    for rec in attendance_records:
        sid  = rec.student_id
        sjid = rec.subject_id
        if sid not in attendance_summary:
            attendance_summary[sid] = {}
        if sjid not in attendance_summary[sid]:
            attendance_summary[sid][sjid] = {
                'subject': rec.subject,
                'present': 0,
                'total':   0,
            }
        attendance_summary[sid][sjid]['total'] += 1
        if rec.status == 'Present':
            attendance_summary[sid][sjid]['present'] += 1

    # ── Active timetable slot (for time-locked attendance) ───────────────────
    now      = dt.now()
    today_name = now.strftime('%A')          # e.g. 'Monday'
    now_time   = now.time().replace(second=0, microsecond=0)

    all_slots_today = Timetable.query.filter_by(
        classroom_id=classroom_id,
        day_of_week=today_name,
    ).order_by(Timetable.start_time).all()

    active_slots = [
        s for s in all_slots_today
        if s.start_time <= now_time <= s.end_time
    ]
    upcoming_slots = [
        s for s in all_slots_today
        if s.start_time > now_time
    ]
    next_slot = upcoming_slots[0] if upcoming_slots else None

    return render_template(
        'classroom_detail.html',
        classroom=classroom,
        students=semester_students,
        batch_students=batch_students,
        notes=notes,
        notices=notices,
        attendance_records=attendance_records,
        attendance_summary=attendance_summary,
        co_teachers=all_teachers_in_room,
        is_owner=is_owner,
        all_teachers=all_teachers,
        semesters=SEMESTERS,
        batches=BATCHES,
        classroom_subjects=classroom_subjects,
        student_user_map=student_user_map,
        today=date_type.today().isoformat(),
        active_slots=active_slots,
        next_slot=next_slot,
        now_time=now_time,
    )


# ── Active slot JSON (AJAX polling) ──────────────────────────────────────────

@teacher_bp.route('/teacher/classroom/<int:classroom_id>/active-slot')
@login_required
def active_slot_json(classroom_id):
    """Returns current active timetable slots as JSON for live updates."""
    now        = dt.now()
    today_name = now.strftime('%A')
    now_time   = now.time().replace(second=0, microsecond=0)

    slots = Timetable.query.filter_by(
        classroom_id=classroom_id,
        day_of_week=today_name,
    ).order_by(Timetable.start_time).all()

    active = []
    for s in slots:
        if s.start_time <= now_time <= s.end_time:
            active.append({
                'id'           : s.id,
                'subject_name' : s.subject.name,
                'subject_code' : s.subject.code,
                'subject_id'   : s.subject_id,
                'session_type' : s.session_type,
                'batch'        : s.batch,
                'start_time'   : s.start_time.strftime('%H:%M'),
                'end_time'     : s.end_time.strftime('%H:%M'),
            })
    return jsonify({'active': active, 'server_time': now.strftime('%H:%M:%S')})


@teacher_bp.route('/teacher/classroom/<int:classroom_id>/delete', methods=['POST'])
@login_required
def delete_classroom(classroom_id):
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))

    classroom = db.get_or_404(Classroom, classroom_id)
    if classroom.teacher_id != current_user.id:
        flash('Only the classroom owner can delete it.', 'danger')
        return redirect(url_for('teacher.view_classroom', classroom_id=classroom_id))

    # Unlink or delete related records to prevent MySQL IntegrityError
    Note.query.filter_by(classroom_id=classroom_id).update({'classroom_id': None})
    Notice.query.filter_by(classroom_id=classroom_id).update({'classroom_id': None})
    AllowedStudent.query.filter_by(classroom_id=classroom_id).update({'classroom_id': None})
    
    # We must also handle timetables and attendance explicitly if DB lacks ON DELETE CASCADE
    Attendance.query.filter_by(classroom_id=classroom_id).delete()
    Timetable.query.filter_by(classroom_id=classroom_id).delete()

    # Exam has no classroom_id — find exams via subjects of this classroom's semester
    if classroom.semester:
        sem_subject_ids = [s.id for s in Subject.query.filter_by(semester=classroom.semester).all()]
        if sem_subject_ids:
            exams = Exam.query.filter(Exam.subject_id.in_(sem_subject_ids)).all()
            for exam in exams:
                ExamResult.query.filter_by(exam_id=exam.id).delete()
                db.session.delete(exam)
        
    ClassroomTeacher.query.filter_by(classroom_id=classroom_id).delete()

    db.session.delete(classroom)
    db.session.commit()
    flash(f'Classroom "{classroom.name}" deleted.', 'info')
    return redirect(url_for('teacher.teacher_dashboard'))


@teacher_bp.route('/teacher/classroom/<int:classroom_id>/upload', methods=['POST'])
@login_required
def upload_note_to_classroom(classroom_id):
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))

    title = request.form['title']
    file  = request.files['file']
    if file and file.filename:
        filename = secure_filename(file.filename)
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
        note = Note(title=title, filename=filename,
                    uploaded_by=current_user.id, classroom_id=classroom_id)
        db.session.add(note)
        db.session.commit()
        flash('Note uploaded!', 'success')
    return redirect(url_for('teacher.view_classroom', classroom_id=classroom_id))


@teacher_bp.route('/teacher/classroom/<int:classroom_id>/delete_note/<int:note_id>', methods=['POST'])
@login_required
def delete_note(classroom_id, note_id):
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))
    note = db.get_or_404(Note, note_id)
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], note.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    db.session.delete(note)
    db.session.commit()
    flash('Note deleted.', 'success')
    return redirect(url_for('teacher.view_classroom', classroom_id=classroom_id))


@teacher_bp.route('/teacher/classroom/<int:classroom_id>/notice', methods=['POST'])
@login_required
def post_notice_to_classroom(classroom_id):
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))
    title   = request.form['title']
    content = request.form['content']
    notice  = Notice(title=title, content=content,
                     posted_by=current_user.id, classroom_id=classroom_id, is_public=False)
    db.session.add(notice)
    db.session.commit()
    flash('Notice posted!', 'success')
    return redirect(url_for('teacher.view_classroom', classroom_id=classroom_id))


@teacher_bp.route('/teacher/classroom/<int:classroom_id>/delete_notice/<int:notice_id>', methods=['POST'])
@login_required
def delete_notice(classroom_id, notice_id):
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))
    notice = db.get_or_404(Notice, notice_id)
    db.session.delete(notice)
    db.session.commit()
    flash('Notice deleted.', 'success')
    return redirect(url_for('teacher.view_classroom', classroom_id=classroom_id))


@teacher_bp.route('/teacher/notice/global', methods=['POST'])
@login_required
def post_global_notice():
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))
    title   = request.form['title']
    content = request.form['content']
    notice  = Notice(title=title, content=content,
                     posted_by=current_user.id, classroom_id=None, is_public=True)
    db.session.add(notice)
    db.session.commit()
    flash('Global notice posted!', 'success')
    return redirect(url_for('teacher.teacher_dashboard'))


# ─────────────────────────────────────────────────────────────────────────────
# ATTENDANCE — Lecture & Lab
# ─────────────────────────────────────────────────────────────────────────────

@teacher_bp.route('/teacher/classroom/<int:classroom_id>/attendance', methods=['POST'])
@login_required
def mark_attendance_for_classroom(classroom_id):
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))

    classroom = db.get_or_404(Classroom, classroom_id)

    # ── Derive params — from timetable slot OR manual override ───────────────
    timetable_id = request.form.get('timetable_id', '').strip()
    if timetable_id:
        slot = db.session.get(Timetable, int(timetable_id))
        if not slot:
            flash('Invalid session slot.', 'danger')
            return redirect(url_for('teacher.view_classroom', classroom_id=classroom_id))
        att_type   = slot.session_type
        subject_id = str(slot.subject_id)
        batch      = slot.batch
        att_date   = date_type.today()
    else:
        att_type   = request.form.get('att_type', 'lecture')
        date_str   = request.form.get('att_date', '').strip()
        subject_id = request.form.get('subject_id', '').strip() or None
        batch      = request.form.get('batch', '').strip() or None
        today      = date_type.today()
        try:
            att_date = dt.strptime(date_str, '%Y-%m-%d').date() if date_str else today
        except ValueError:
            att_date = today
        if att_date > today:
            flash('Cannot mark attendance for a future date.', 'danger')
            return redirect(url_for('teacher.view_classroom', classroom_id=classroom_id))
        days_back = (today - att_date).days
        if days_back > 7:
            flash(f'Warning: Back-dating by {days_back} days. Please verify.', 'warning')

    if not subject_id:
        flash('Please select a subject.', 'danger')
        return redirect(url_for('teacher.view_classroom', classroom_id=classroom_id))
    if att_type == 'lab' and not batch:
        flash('Please select a batch for lab attendance.', 'danger')
        return redirect(url_for('teacher.view_classroom', classroom_id=classroom_id))

    subject_id_int = int(subject_id)

    # ── Target students ──────────────────────────────────────────────────────
    if att_type == 'lab' and batch:
        target_students = classroom.get_batch_students(batch)
    else:
        target_students = classroom.get_students()

    present_ids = set()
    for val in request.form.getlist('present'):
        try:
            present_ids.add(int(val))
        except ValueError:
            pass

    new_count = updated_count = 0
    for user in target_students:
        status = 'Present' if user.id in present_ids else 'Absent'
        q = Attendance.query.filter_by(
            student_id=user.id,
            classroom_id=classroom_id,
            subject_id=subject_id_int,
            date=att_date,
            attendance_type=att_type,
        )
        if att_type == 'lab':
            q = q.filter_by(batch=batch)
        existing = q.first()
        if existing:
            existing.status    = status
            existing.marked_by = current_user.id
            updated_count += 1
        else:
            db.session.add(Attendance(
                student_id=user.id,
                status=status,
                classroom_id=classroom_id,
                subject_id=subject_id_int,
                date=att_date,
                attendance_type=att_type,
                batch=batch,
                marked_by=current_user.id,
            ))
            new_count += 1

    db.session.commit()
    type_label = f"Lab — Batch {batch}" if att_type == 'lab' else 'Lecture'
    if updated_count > 0 and new_count > 0:
        flash(f'{type_label} attendance saved ({new_count} new, {updated_count} updated).', 'success')
    elif updated_count > 0:
        flash(f'{type_label} attendance updated ({updated_count} records).', 'warning')
    else:
        flash(f'{type_label} attendance saved for {att_date}!', 'success')

    return redirect(url_for('teacher.view_classroom', classroom_id=classroom_id))


# ── Co-teacher management removed (Admin handles this via subjects) ──


# ── Exams ────────────────────────────────────────────────────────────────────

@teacher_bp.route('/teacher/exams')
@login_required
def teacher_exams():
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))
    subjects    = Subject.query.filter_by(teacher_id=current_user.id).all()
    subject_ids = [s.id for s in subjects]
    exams = Exam.query.filter(Exam.subject_id.in_(subject_ids))\
                      .order_by(Exam.date.desc()).all() if subject_ids else []
    return render_template('teacher/teacher_exams.html', exams=exams)


@teacher_bp.route('/teacher/exam/<int:exam_id>/grade', methods=['GET', 'POST'])
@login_required
def grade_exam(exam_id):
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))

    exam = Exam.query.get_or_404(exam_id)
    if exam.subject.teacher_id != current_user.id:
        flash('You are not authorised to grade this exam.', 'danger')
        return redirect(url_for('teacher.teacher_exams'))

    students = User.query.filter_by(role='student', semester=exam.semester).order_by(User.batch, User.name).all()

    if request.method == 'POST':
        for student in students:
            marks   = request.form.get(f'marks_{student.id}')
            remarks = request.form.get(f'remarks_{student.id}')
            if marks is not None and marks != '':
                result = ExamResult.query.filter_by(exam_id=exam.id, student_id=student.id).first()
                if result:
                    result.marks_obtained = int(marks)
                    result.remarks        = remarks
                else:
                    db.session.add(ExamResult(
                        exam_id=exam.id,
                        student_id=student.id,
                        marks_obtained=int(marks),
                        remarks=remarks,
                    ))
        db.session.commit()
        flash('Grades saved!', 'success')
        return redirect(url_for('teacher.teacher_exams'))

    results     = ExamResult.query.filter_by(exam_id=exam.id).all()
    results_map = {r.student_id: r for r in results}
    return render_template('teacher/grade_exam.html', exam=exam, students=students, results_map=results_map)
