from flask import Blueprint, render_template, send_from_directory, current_app
from flask_login import login_required

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/download/<filename>')
@login_required
def download(filename):
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
