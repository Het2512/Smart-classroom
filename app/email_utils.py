import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import ssl
from email.utils import formataddr, make_msgid

def send_credentials_email(to_email, password, role, faculty_code=None):
    """
    Sends an email with login credentials to a newly created user.
    If SMTP variables are not set in the environment, it prints the email to the console
    and returns it so it can be displayed to the admin.
    """
    subject = f"Welcome to Smart Classroom - Your {role.title()} Account"
    
    body = f"""Hello,

Your {role} account for Smart Classroom has been created by the administrator.

Here are your login credentials:
Email: {to_email}
Password: {password}
"""
    if role == 'teacher' and faculty_code:
        body += f"Faculty Registration Code: {faculty_code}\n"
        
    body += "\nPlease log in and change your password as soon as possible.\n\nBest regards,\nSmart Classroom Team"

    smtp_server = os.getenv('SMTP_SERVER')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USERNAME')
    smtp_pass = os.getenv('SMTP_PASSWORD')
    smtp_from_email = os.getenv('SMTP_FROM_EMAIL', smtp_user or '')
    smtp_from_name = os.getenv('SMTP_FROM_NAME', 'Smart Classroom')
    smtp_reply_to = os.getenv('SMTP_REPLY_TO', smtp_from_email)
    smtp_use_tls = os.getenv('SMTP_USE_TLS', 'true').strip().lower() == 'true'
    smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'false').strip().lower() == 'true'
    smtp_timeout = int(os.getenv('SMTP_TIMEOUT', '30'))

    # If no SMTP server is configured, log to console
    if not smtp_server or not smtp_user or not smtp_pass:
        print("\n" + "="*50)
        print("EMAIL SIMULATION (SMTP not configured in .env):")
        print(f"To: {to_email}")
        print(f"Subject: {subject}")
        print("-" * 50)
        print(body)
        print("="*50 + "\n")
        return {"sent": False, "simulated": True, "body": body}

    try:
        msg = MIMEMultipart()
        msg['From'] = formataddr((smtp_from_name, smtp_from_email))
        msg['To'] = to_email
        msg['Subject'] = subject
        msg['Reply-To'] = smtp_reply_to
        msg['Message-ID'] = make_msgid(domain=smtp_from_email.split('@')[-1] if '@' in smtp_from_email else None)
        msg.attach(MIMEText(body, 'plain'))

        if smtp_use_ssl:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=smtp_timeout, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=smtp_timeout)
            server.ehlo()
            if smtp_use_tls:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()

        server.login(smtp_user, smtp_pass)
        server.send_message(msg, from_addr=smtp_from_email, to_addrs=[to_email])
        server.quit()
        return {"sent": True, "simulated": False, "body": body}
    except Exception as e:
        print(f"Failed to send email to {to_email}: {str(e)}")
        return {"sent": False, "simulated": False, "body": body}
