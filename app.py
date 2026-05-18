from app import create_app
from app.extensions import db
from werkzeug.security import generate_password_hash

app = create_app()

with app.app_context():
    db.create_all()
    # Ensure an admin user exists
    from app.models import User, SystemConfig
    admin = User.query.filter_by(role='admin').first()
    if not admin:
        admin = User(
            name='Admin',
            email='admin@admin.com',
            password=generate_password_hash('admin123'),
            role='admin'
        )
        db.session.add(admin)
        
    # Ensure default faculty code exists
    faculty_code = SystemConfig.query.filter_by(key='faculty_code').first()
    if not faculty_code:
        faculty_code = SystemConfig(key='faculty_code', value='FACULTY2024')
        db.session.add(faculty_code)
        
    db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)