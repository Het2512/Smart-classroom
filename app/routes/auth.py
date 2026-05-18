from flask import Blueprint, request, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import User, AllowedStudent, SystemConfig
from app.extensions import db
import os

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/teacher/login', methods=['GET', 'POST'])
def teacher_login():
    if request.method == 'POST':
        code     = request.form['code']
        email    = request.form['email']
        password = request.form['password']

        faculty_config = SystemConfig.query.filter_by(key='faculty_code').first()
        valid_code = faculty_config.value if faculty_config else 'FACULTY2024'

        if code != valid_code:
            flash('Invalid faculty code!', 'danger')
            return redirect(url_for('auth.teacher_login'))

        user = User.query.filter_by(email=email, role='teacher').first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('teacher.teacher_dashboard'))
        else:
            flash('Invalid email or password.', 'danger')
            
    return render_template('teacher_login.html')

@auth_bp.route('/student/login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        email    = request.form['email']
        password = request.form.get('password')

        user = User.query.filter_by(email=email, role='student').first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('student.student_dashboard'))
        else:
            flash('Invalid email or password. Only admins can create accounts.', 'danger')
            
    return render_template('login.html')

@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = User.query.filter_by(email=email, role='admin').first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('admin.admin_dashboard'))
        else:
            flash('Invalid admin credentials', 'danger')
            
    return render_template('admin/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.index'))
