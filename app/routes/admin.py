from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from app.models import User, Classroom, AllowedStudent, SystemConfig, Subject, Timetable, Exam, SEMESTERS, BATCHES, Note, Notice, Attendance, ClassroomTeacher, ExamResult
from app.extensions import db
from app.utils import admin_required
from app.email_utils import send_credentials_email
import pandas as pd
import io

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/dashboard')
@admin_required
def admin_dashboard():
    teachers_count   = User.query.filter_by(role='teacher').count()
    students_count   = User.query.filter_by(role='student').count()
    classrooms_count = Classroom.query.count()
    subjects_count   = Subject.query.count()
    return render_template('admin/dashboard.html',
                           teachers_count=teachers_count,
                           students_count=students_count,
                           classrooms_count=classrooms_count,
                           subjects_count=subjects_count)

@admin_bp.route('/teachers', methods=['GET', 'POST'])
@admin_required
def teachers():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'danger')
        else:
            new_teacher = User(
                name=name,
                email=email,
                password=generate_password_hash(password),
                plain_password=password,
                role='teacher'
            )
            db.session.add(new_teacher)
            db.session.commit()
            
            # Send Email
            faculty_config = SystemConfig.query.filter_by(key='faculty_code').first()
            valid_code = faculty_config.value if faculty_config else 'FACULTY2024'
            result = send_credentials_email(email, password, 'teacher', valid_code)
            
            if result.get("simulated"):
                flash(f"Teacher created! Simulation mode: Email content shown in terminal. Credentials: Email: {email}, Password: {password}, Code: {valid_code}", 'success')
            elif result.get("sent"):
                flash('Teacher added and email sent successfully', 'success')
            else:
                flash(f"Teacher created but failed to send email. Credentials: Email: {email}, Password: {password}, Code: {valid_code}", 'warning')
                
        return redirect(url_for('admin.teachers'))
        
    teachers_list = User.query.filter_by(role='teacher').all()
    return render_template('admin/teachers.html', teachers=teachers_list)

@admin_bp.route('/teachers/delete/<int:id>', methods=['POST'])
@admin_required
def delete_teacher(id):
    teacher = User.query.get_or_404(id)
    if teacher.role == 'teacher':
        ClassroomTeacher.query.filter_by(teacher_id=id).delete()
        Classroom.query.filter_by(teacher_id=id).update({'teacher_id': None})
        
        subjects = Subject.query.filter_by(teacher_id=id).all()
        for subject in subjects:
            Timetable.query.filter_by(subject_id=subject.id).delete()
            Attendance.query.filter_by(subject_id=subject.id).delete()
            exams = Exam.query.filter_by(subject_id=subject.id).all()
            for exam in exams:
                ExamResult.query.filter_by(exam_id=exam.id).delete()
                db.session.delete(exam)
            db.session.delete(subject)
            
        Attendance.query.filter_by(marked_by=id).update({'marked_by': None})
        Note.query.filter_by(uploaded_by=id).update({'uploaded_by': None})
        Notice.query.filter_by(posted_by=id).update({'posted_by': None})
        AllowedStudent.query.filter_by(added_by=id).update({'added_by': None})
        
        db.session.delete(teacher)
        db.session.commit()
        flash('Teacher deleted successfully', 'success')
    return redirect(url_for('admin.teachers'))

@admin_bp.route('/students', methods=['GET', 'POST'])
@admin_required
def students():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        name     = request.form.get('name', '').strip()
        password = request.form.get('password', '')
        semester = request.form.get('semester', '').strip() or None
        batch    = request.form.get('batch', '').strip() or None

        if not email or not password:
            flash('Email and password are required.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('A user with this email already exists.', 'danger')
        else:
            new_student = User(
                name=name or email.split('@')[0],
                email=email,
                password=generate_password_hash(password),
                plain_password=password,
                role='student',
                semester=semester,
                batch=batch,
            )
            db.session.add(new_student)
            db.session.commit()

            result = send_credentials_email(email, password, 'student')
            if result.get('simulated'):
                flash(f'Student created (sim mode). Email: {email} | Pass: {password}', 'success')
            elif result.get('sent'):
                flash('Student created and credentials emailed.', 'success')
            else:
                flash(f'Student created but email failed. Email: {email} | Pass: {password}', 'warning')

        return redirect(url_for('admin.students'))

    # Group students by semester for display
    all_students = User.query.filter_by(role='student').order_by(
        User.semester, User.batch, User.name
    ).all()

    # Batch counts per semester (to help admin assign evenly)
    batch_counts = {}
    for sem in SEMESTERS:
        batch_counts[sem] = {}
        for b in BATCHES:
            batch_counts[sem][b] = User.query.filter_by(role='student', semester=sem, batch=b).count()

    return render_template(
        'admin/students.html',
        students=all_students,
        semesters=SEMESTERS,
        batches=BATCHES,
        batch_counts=batch_counts,
    )


@admin_bp.route('/students/delete/<int:id>', methods=['POST'])
@admin_required
def delete_student(id):
    student = User.query.get_or_404(id)
    if student.role != 'student':
        flash('Not a student account.', 'danger')
        return redirect(url_for('admin.students'))
        
    Attendance.query.filter_by(student_id=id).delete()
    ExamResult.query.filter_by(student_id=id).delete()
    
    db.session.delete(student)
    db.session.commit()
    flash(f'Student "{student.name}" deleted.', 'success')
    return redirect(url_for('admin.students'))


@admin_bp.route('/students/edit/<int:id>', methods=['POST'])
@admin_required
def edit_student(id):
    student = User.query.get_or_404(id)
    if student.role != 'student':
        flash('Not a student account.', 'danger')
        return redirect(url_for('admin.students'))
    student.semester = request.form.get('semester') or None
    student.batch    = request.form.get('batch')    or None
    db.session.commit()
    flash(f'Updated {student.name} — Sem: {student.semester}, Batch: {student.batch}', 'success')
    return redirect(url_for('admin.students'))

@admin_bp.route('/classrooms', methods=['GET', 'POST'])
@admin_required
def classrooms():
    if request.method == 'POST':
        name = request.form.get('name')
        semester = request.form.get('semester')
        description = request.form.get('description')
        teacher_id = request.form.get('teacher_id')
        
        if not name:
            flash('Classroom name is required', 'danger')
        elif Classroom.query.filter_by(name=name).first():
            flash('Classroom with this name already exists', 'danger')
        else:
            new_class = Classroom(
                name=name,
                semester=semester,
                description=description,
                teacher_id=teacher_id if teacher_id else None
            )
            db.session.add(new_class)
            db.session.commit()
            flash('Classroom created successfully', 'success')
        return redirect(url_for('admin.classrooms'))

    classrooms_list = Classroom.query.all()
    teachers_list = User.query.filter_by(role='teacher').all()
    return render_template('admin/classrooms.html', classrooms=classrooms_list, teachers=teachers_list)

@admin_bp.route('/classrooms/delete/<int:id>', methods=['POST'])
@admin_required
def delete_classroom(id):
    classroom = Classroom.query.get_or_404(id)
    
    # Unlink or delete related records to prevent MySQL IntegrityError
    Note.query.filter_by(classroom_id=id).update({'classroom_id': None})
    Notice.query.filter_by(classroom_id=id).update({'classroom_id': None})
    AllowedStudent.query.filter_by(classroom_id=id).update({'classroom_id': None})
    
    Attendance.query.filter_by(classroom_id=id).delete()
    Timetable.query.filter_by(classroom_id=id).delete()

    # Exam has no classroom_id — find exams via subjects of this classroom's semester
    if classroom.semester:
        sem_subject_ids = [s.id for s in Subject.query.filter_by(semester=classroom.semester).all()]
        if sem_subject_ids:
            exams = Exam.query.filter(Exam.subject_id.in_(sem_subject_ids)).all()
            for exam in exams:
                ExamResult.query.filter_by(exam_id=exam.id).delete()
                db.session.delete(exam)
        
    ClassroomTeacher.query.filter_by(classroom_id=id).delete()

    db.session.delete(classroom)
    db.session.commit()
    flash('Classroom deleted successfully', 'success')
    return redirect(url_for('admin.classrooms'))

@admin_bp.route('/subjects', methods=['GET', 'POST'])
@admin_required
def subjects():
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        semester = request.form.get('semester')
        teacher_id = request.form.get('teacher_id')
        
        if not name or not code or not semester or not teacher_id:
            flash('All fields are required', 'danger')
        else:
            new_subject = Subject(
                name=name,
                code=code,
                semester=semester,
                teacher_id=teacher_id
            )
            db.session.add(new_subject)
            db.session.commit()
            flash('Subject created successfully', 'success')
        return redirect(url_for('admin.subjects'))

    subjects_list = Subject.query.all()
    teachers_list = User.query.filter_by(role='teacher').all()
    return render_template('admin/subjects.html', subjects=subjects_list, semesters=SEMESTERS, teachers=teachers_list)

@admin_bp.route('/subjects/delete/<int:id>', methods=['POST'])
@admin_required
def delete_subject(id):
    subject = Subject.query.get_or_404(id)
    
    Timetable.query.filter_by(subject_id=id).delete()
    Attendance.query.filter_by(subject_id=id).delete()
    exams = Exam.query.filter_by(subject_id=id).all()
    for exam in exams:
        ExamResult.query.filter_by(exam_id=exam.id).delete()
        db.session.delete(exam)
        
    db.session.delete(subject)
    db.session.commit()
    flash('Subject deleted successfully', 'success')
    return redirect(url_for('admin.subjects'))

@admin_bp.route('/timetable', methods=['GET', 'POST'])
@admin_required
def timetable():
    if request.method == 'POST':
        classroom_id = request.form.get('classroom_id')
        subject_name = request.form.get('subject_name')
        day = request.form.get('day')
        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')
        
        session_type = request.form.get('session_type', 'lecture').strip()
        batch        = request.form.get('batch', '').strip() or None

        if not classroom_id or not subject_name or not day or not start_time_str or not end_time_str:
            flash('All fields are required', 'danger')
        else:
            from datetime import datetime
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
            end_time   = datetime.strptime(end_time_str,   '%H:%M').time()

            subject = Subject.query.filter_by(name=subject_name).first()
            if not subject:
                classroom = Classroom.query.get(classroom_id)
                teacher = User.query.filter_by(role='teacher').first()
                if not teacher:
                    teacher = User.query.first()
                
                subject = Subject(
                    name=subject_name,
                    code=subject_name[:3].upper() + "101",
                    semester=classroom.semester if classroom else "Sem 1",
                    teacher_id=teacher.id if teacher else 1
                )
                db.session.add(subject)
                db.session.flush()

            new_slot = Timetable(
                classroom_id=classroom_id,
                subject_id=subject.id,
                day_of_week=day,
                start_time=start_time,
                end_time=end_time,
                session_type=session_type,
                batch=batch,
            )
            db.session.add(new_slot)
            db.session.commit()
            flash('Timetable slot created successfully', 'success')
        return redirect(url_for('admin.timetable'))


    slots_list = Timetable.query.all()
    classrooms_list = Classroom.query.all()
    subjects_list = Subject.query.all()
    return render_template('admin/timetable.html', slots=slots_list, classrooms=classrooms_list, subjects=subjects_list)

@admin_bp.route('/timetable/delete/<int:id>', methods=['POST'])
@admin_required
def delete_timetable(id):
    slot = Timetable.query.get_or_404(id)
    db.session.delete(slot)
    db.session.commit()
    flash('Timetable slot deleted successfully', 'success')
    return redirect(url_for('admin.timetable'))

@admin_bp.route('/exams', methods=['GET', 'POST'])
@admin_required
def exams():
    if request.method == 'POST':
        title = request.form.get('title')
        semester = request.form.get('semester')
        subject_id = request.form.get('subject_id')
        date_str = request.form.get('date')
        total_marks = request.form.get('total_marks')
        
        if not title or not semester or not subject_id or not date_str or not total_marks:
            flash('All fields are required', 'danger')
        else:
            from datetime import datetime
            exam_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            new_exam = Exam(
                title=title,
                semester=semester,
                subject_id=subject_id,
                date=exam_date,
                total_marks=total_marks
            )
            db.session.add(new_exam)
            db.session.commit()
            flash('Exam created successfully', 'success')
        return redirect(url_for('admin.exams'))

    exams_list = Exam.query.all()
    subjects_list = Subject.query.all()
    return render_template('admin/exams.html', exams=exams_list, semesters=SEMESTERS, subjects=subjects_list)

@admin_bp.route('/exams/delete/<int:id>', methods=['POST'])
@admin_required
def delete_exam(id):
    exam = Exam.query.get_or_404(id)
    ExamResult.query.filter_by(exam_id=id).delete()
    db.session.delete(exam)
    db.session.commit()
    flash('Exam deleted successfully', 'success')
    return redirect(url_for('admin.exams'))

@admin_bp.route('/exams/publish/<int:id>', methods=['POST'])
@admin_required
def publish_exam(id):
    exam = Exam.query.get_or_404(id)
    exam.is_published = not exam.is_published
    db.session.commit()
    status = "published" if exam.is_published else "unpublished"
    flash(f'Exam {status} successfully', 'success')
    return redirect(url_for('admin.exams'))

@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    faculty_config = SystemConfig.query.filter_by(key='faculty_code').first()
    
    if request.method == 'POST':
        new_code = request.form.get('faculty_code')
        if not faculty_config:
            faculty_config = SystemConfig(key='faculty_code', value=new_code)
            db.session.add(faculty_config)
        else:
            faculty_config.value = new_code
            
        db.session.commit()
        flash('Faculty Code updated successfully.', 'success')
        return redirect(url_for('admin.settings'))
        
    return render_template('admin/settings.html', faculty_code=faculty_config.value if faculty_config else 'FACULTY2024')


@admin_bp.route('/users/bulk-import/students', methods=['GET', 'POST'])
@admin_required
def bulk_import_students():
    """
    Accepts an Excel file (.xlsx / .xls) or CSV with columns:
        username/email | password | name (opt) | semester (opt) | batch (opt)
    Creates student accounts that don't already exist.
    """
    results = None

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            flash('Please select an Excel or CSV file.', 'danger')
            return redirect(url_for('admin.bulk_import_students'))

        ext = file.filename.rsplit('.', 1)[-1].lower()
        if ext not in ('xlsx', 'xls', 'csv'):
            flash('Only .xlsx, .xls or .csv files are accepted.', 'danger')
            return redirect(url_for('admin.bulk_import_students'))

        try:
            raw = file.read()
            if ext == 'csv':
                df = pd.read_csv(io.BytesIO(raw))
            else:
                df = pd.read_excel(io.BytesIO(raw))
        except Exception as e:
            flash(f'Could not read file: {e}', 'danger')
            return redirect(url_for('admin.bulk_import_students'))

        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]

        if 'username' in df.columns and 'email' not in df.columns:
            df.rename(columns={'username': 'email'}, inplace=True)

        required_cols = {'email', 'password'}
        if not required_cols.issubset(set(df.columns)):
            flash(
                f'File must have at least "email" (or "username") and "password" columns. '
                f'Found: {", ".join(df.columns)}',
                'danger'
            )
            return redirect(url_for('admin.bulk_import_students'))

        created  = []
        skipped  = []
        errors   = []

        _EMPTY_VALS = {'', 'nan', 'none', 'n/a', 'na', '-', '(empty)', 'null'}

        def _clean(val):
            s = str(val).strip()
            return None if s.lower() in _EMPTY_VALS else s

        for idx, row in df.iterrows():
            row_num = idx + 2
            try:
                email    = _clean(row.get('email', '')) or ''
                password = _clean(row.get('password', '')) or ''
                name     = _clean(row.get('name', ''))     if 'name'     in df.columns else None
                semester = _clean(row.get('semester', '')) if 'semester' in df.columns else None
                batch    = _clean(row.get('batch', ''))    if 'batch'    in df.columns else None

                email    = email.lower()
                name     = name or email.split('@')[0]
                role     = 'student'

                if semester and len(semester) > 20:
                    semester = semester[:20]
                if batch and len(batch) > 5:
                    batch = batch[:5]

                if not email or not password:
                    errors.append({'row': row_num, 'email': email, 'reason': 'Missing email/username or password'})
                    continue

                existing_user = User.query.filter_by(email=email).first()

                if existing_user:
                    skipped.append({'row': row_num, 'email': email, 'reason': 'Student already exists'})
                    continue

                new_user = User(
                    name=name,
                    email=email,
                    password=generate_password_hash(password),
                    plain_password=password,
                    role=role,
                    semester=semester,
                    batch=batch,
                )
                db.session.add(new_user)
                db.session.flush()
                send_credentials_email(email, password, role)

                if semester:
                    classroom = Classroom.query.filter_by(semester=semester).first()
                    if classroom:
                        db.session.add(AllowedStudent(
                            email=email,
                            name=name,
                            added_by=None,
                            classroom_id=classroom.id,
                        ))

                created.append({'row': row_num, 'email': email, 'name': name, 'role': role, 'semester': semester, 'batch': batch})

            except Exception as e:
                db.session.rollback()
                errors.append({'row': row_num, 'email': str(row.get('email', '?')), 'reason': str(e)})

        db.session.commit()

        if created:
            flash(f'✅ {len(created)} student(s) imported successfully.', 'success')
        if skipped:
            flash(f'⚠️ {len(skipped)} student(s) skipped (already exists).', 'warning')
        if errors:
            flash(f'❌ {len(errors)} row(s) had errors.', 'danger')

        results = {'created': created, 'skipped': skipped, 'errors': errors}

    return render_template('admin/bulk_import_students.html', results=results)


@admin_bp.route('/users/bulk-import/teachers', methods=['GET', 'POST'])
@admin_required
def bulk_import_teachers():
    """
    Accepts an Excel file (.xlsx / .xls) or CSV with columns:
        username/email | password | name (opt) | subject_name (opt) | subject_code (opt) | subject_semester (opt)
    Creates teacher accounts and auto-links subjects.
    """
    results = None

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            flash('Please select an Excel or CSV file.', 'danger')
            return redirect(url_for('admin.bulk_import_teachers'))

        ext = file.filename.rsplit('.', 1)[-1].lower()
        if ext not in ('xlsx', 'xls', 'csv'):
            flash('Only .xlsx, .xls or .csv files are accepted.', 'danger')
            return redirect(url_for('admin.bulk_import_teachers'))

        try:
            raw = file.read()
            if ext == 'csv':
                df = pd.read_csv(io.BytesIO(raw))
            else:
                df = pd.read_excel(io.BytesIO(raw))
        except Exception as e:
            flash(f'Could not read file: {e}', 'danger')
            return redirect(url_for('admin.bulk_import_teachers'))

        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]

        if 'username' in df.columns and 'email' not in df.columns:
            df.rename(columns={'username': 'email'}, inplace=True)

        required_cols = {'email', 'password'}
        if not required_cols.issubset(set(df.columns)):
            flash(
                f'File must have at least "email" (or "username") and "password" columns. '
                f'Found: {", ".join(df.columns)}',
                'danger'
            )
            return redirect(url_for('admin.bulk_import_teachers'))

        created  = []
        skipped  = []
        errors   = []

        _EMPTY_VALS = {'', 'nan', 'none', 'n/a', 'na', '-', '(empty)', 'null'}

        def _clean(val):
            s = str(val).strip()
            return None if s.lower() in _EMPTY_VALS else s

        for idx, row in df.iterrows():
            row_num = idx + 2
            try:
                email    = _clean(row.get('email', '')) or ''
                password = _clean(row.get('password', '')) or ''
                name     = _clean(row.get('name', ''))     if 'name'     in df.columns else None

                subj_name = _clean(row.get('subject_name', '')) if 'subject_name' in df.columns else None
                subj_code = _clean(row.get('subject_code', '')) if 'subject_code' in df.columns else None
                subj_sem  = _clean(row.get('subject_semester', '')) if 'subject_semester' in df.columns else None

                email    = email.lower()
                name     = name or email.split('@')[0]
                role     = 'teacher'

                if not email or not password:
                    errors.append({'row': row_num, 'email': email, 'reason': 'Missing email/username or password'})
                    continue

                existing_user = User.query.filter_by(email=email).first()

                user_obj = None
                is_new = False

                if existing_user:
                    user_obj = existing_user
                    skipped.append({'row': row_num, 'email': email, 'reason': 'Teacher already exists'})
                else:
                    new_user = User(
                        name=name,
                        email=email,
                        password=generate_password_hash(password),
                        plain_password=password,
                        role=role,
                    )
                    db.session.add(new_user)
                    db.session.flush()
                    send_credentials_email(email, password, role)
                    user_obj = new_user
                    is_new = True
                    created.append({
                        'row': row_num, 
                        'email': email, 
                        'name': name, 
                        'subject_name': subj_name, 
                        'subject_code': subj_code, 
                        'subject_semester': subj_sem
                    })

                # Create or link subject
                if user_obj and subj_name and subj_code and subj_sem:
                    if len(subj_sem) > 20:
                        subj_sem = subj_sem[:20]

                    existing_subj = Subject.query.filter_by(code=subj_code).first()
                    if existing_subj:
                        existing_subj.teacher_id = user_obj.id
                        existing_subj.name = subj_name
                        existing_subj.semester = subj_sem
                    else:
                        new_subj = Subject(
                            name=subj_name,
                            code=subj_code,
                            semester=subj_sem,
                            teacher_id=user_obj.id
                        )
                        db.session.add(new_subj)

                    db.session.flush()
                    
                    if not is_new:
                        # If teacher was skipped but subject was successfully created/linked, add to skipped with custom reason
                        skipped[-1]['reason'] = f'Teacher already exists. Subject "{subj_name}" has been successfully assigned/updated.'

            except Exception as e:
                db.session.rollback()
                errors.append({'row': row_num, 'email': str(row.get('email', '?')), 'reason': str(e)})

        db.session.commit()

        if created:
            flash(f'✅ {len(created)} teacher(s) imported successfully.', 'success')
        if skipped:
            flash(f'⚠️ {len(skipped)} teacher(s) handled (already existed / updated subjects).', 'warning')
        if errors:
            flash(f'❌ {len(errors)} row(s) had errors.', 'danger')

        results = {'created': created, 'skipped': skipped, 'errors': errors}

    return render_template('admin/bulk_import_teachers.html', results=results)

@admin_bp.route('/timetable/bulk-import', methods=['GET', 'POST'])
@admin_required
def bulk_import_timetable():
    """
    Accepts an Excel file (.xlsx / .xls) or CSV with columns:
        classroom_name | subject_code | subject_name (opt) | day | start_time | end_time | session_type (opt) | batch (opt)
    """
    results = None

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            flash('Please select an Excel or CSV file.', 'danger')
            return redirect(url_for('admin.bulk_import_timetable'))

        ext = file.filename.rsplit('.', 1)[-1].lower()
        if ext not in ('xlsx', 'xls', 'csv'):
            flash('Only .xlsx, .xls or .csv files are accepted.', 'danger')
            return redirect(url_for('admin.bulk_import_timetable'))

        try:
            raw = file.read()
            if ext == 'csv':
                df = pd.read_csv(io.BytesIO(raw))
            else:
                df = pd.read_excel(io.BytesIO(raw))
        except Exception as e:
            flash(f'Could not read file: {e}', 'danger')
            return redirect(url_for('admin.bulk_import_timetable'))

        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]

        required_cols = {'classroom_name', 'subject_code', 'day', 'start_time', 'end_time'}
        if not required_cols.issubset(set(df.columns)):
            flash(
                f'File must have at least {", ".join(required_cols)} columns. '
                f'Found: {", ".join(df.columns)}',
                'danger'
            )
            return redirect(url_for('admin.bulk_import_timetable'))

        created  = []
        skipped  = []
        errors   = []

        _EMPTY_VALS = {'', 'nan', 'none', 'n/a', 'na', '-', '(empty)', 'null'}

        def _clean(val):
            s = str(val).strip()
            return None if s.lower() in _EMPTY_VALS else s

        for idx, row in df.iterrows():
            row_num = idx + 2
            try:
                classroom_name = _clean(row.get('classroom_name', ''))
                subject_code   = _clean(row.get('subject_code', ''))
                subject_name   = _clean(row.get('subject_name', ''))
                day            = _clean(row.get('day', ''))
                start_time_str = _clean(row.get('start_time', ''))
                end_time_str   = _clean(row.get('end_time', ''))
                session_type   = _clean(row.get('session_type', 'lecture'))
                batch          = _clean(row.get('batch', ''))

                if not all([classroom_name, subject_code, day, start_time_str, end_time_str]):
                    errors.append({'row': row_num, 'detail': 'Missing required fields'})
                    continue

                classroom = Classroom.query.filter_by(name=classroom_name).first()
                if not classroom:
                    errors.append({'row': row_num, 'detail': f'Classroom "{classroom_name}" not found'})
                    continue

                subject = Subject.query.filter_by(code=subject_code).first()
                if not subject:
                    if not subject_name:
                        errors.append({'row': row_num, 'detail': f'Subject "{subject_code}" not found, and no subject_name provided to create it.'})
                        continue
                    
                    teacher = User.query.filter_by(role='teacher').first()
                    subject = Subject(
                        name=subject_name,
                        code=subject_code,
                        semester=classroom.semester if classroom.semester else "Sem 1",
                        teacher_id=teacher.id if teacher else 1
                    )
                    db.session.add(subject)
                    db.session.flush()

                from datetime import datetime
                try:
                    start_time = datetime.strptime(str(start_time_str), '%H:%M').time()
                except ValueError:
                    try:
                        start_time = datetime.strptime(str(start_time_str), '%H:%M:%S').time()
                    except ValueError:
                        errors.append({'row': row_num, 'detail': f'Invalid start_time format: {start_time_str}'})
                        continue
                        
                try:
                    end_time = datetime.strptime(str(end_time_str), '%H:%M').time()
                except ValueError:
                    try:
                        end_time = datetime.strptime(str(end_time_str), '%H:%M:%S').time()
                    except ValueError:
                        errors.append({'row': row_num, 'detail': f'Invalid end_time format: {end_time_str}'})
                        continue

                # Check if slot already exists to prevent exact duplicates
                existing_slot = Timetable.query.filter_by(
                    classroom_id=classroom.id,
                    subject_id=subject.id,
                    day_of_week=day.capitalize(),
                    start_time=start_time,
                    end_time=end_time,
                    batch=batch
                ).first()

                if existing_slot:
                    skipped.append({'row': row_num, 'detail': 'Slot already exists'})
                    continue

                new_slot = Timetable(
                    classroom_id=classroom.id,
                    subject_id=subject.id,
                    day_of_week=day.capitalize(),
                    start_time=start_time,
                    end_time=end_time,
                    session_type=session_type.lower() if session_type else 'lecture',
                    batch=batch
                )
                db.session.add(new_slot)
                db.session.flush()

                created.append({
                    'row': row_num, 
                    'classroom': classroom.name, 
                    'subject': subject.name,
                    'day': day.capitalize(),
                    'time': f"{start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"
                })

            except Exception as e:
                db.session.rollback()
                errors.append({'row': row_num, 'detail': str(e)})

        db.session.commit()

        if created:
            flash(f'✅ {len(created)} timetable slot(s) imported successfully.', 'success')
        if skipped:
            flash(f'⚠️ {len(skipped)} slot(s) skipped (already exist).', 'warning')
        if errors:
            flash(f'❌ {len(errors)} row(s) had errors.', 'danger')

        results = {'created': created, 'skipped': skipped, 'errors': errors}

    return render_template('admin/bulk_import_timetable.html', results=results)
