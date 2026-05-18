import os
from urllib.parse import quote_plus
from flask import Flask
from app.extensions import db, login_manager
from dotenv import load_dotenv

load_dotenv()

def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')

    _DB_HOST     = os.getenv('DB_HOST', 'localhost')
    _DB_PORT     = os.getenv('DB_PORT', '3306')
    _DB_USER     = os.getenv('DB_USER', 'root')
    _DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    _DB_NAME     = os.getenv('DB_NAME', 'smart_classroom')

    _DB_PASSWORD_ENCODED = quote_plus(_DB_PASSWORD)
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f"mysql+pymysql://{_DB_USER}:{_DB_PASSWORD_ENCODED}@{_DB_HOST}:{_DB_PORT}/{_DB_NAME}"
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Calculate upload folder relative to project root
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app.config['UPLOAD_FOLDER'] = os.path.join(base_dir, 'static', 'uploads')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.teacher_login'

    from app.models import User
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.teacher import teacher_bp
    from app.routes.student import student_bp
    from app.routes.ai import ai_bp
    from app.routes.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(admin_bp)

    return app
