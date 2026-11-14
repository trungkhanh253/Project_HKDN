
import os
import smtplib
from email.message import EmailMessage
from html import escape
from urllib.parse import urlencode


def send_password_reset_email(recipient_email: str, token: str) -> None:
    host = os.getenv("SMTP_HOST", "smtp-relay.brevo.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("MAIL_FROM")

    if not all([username, password, sender]):
        raise RuntimeError("Chưa cấu hình đầy đủ SMTP.")

    # Link này hiện phục vụ luồng Android.
    reset_url = (
        "https://reset-password-vert.vercel.app/?"
        + urlencode({"email": recipient_email, "token": token})
    )

    message = EmailMessage()
    message["Subject"] = "Đặt lại mật khẩu - IriTech"
    message["From"] = sender
    message["To"] = recipient_email

    message.set_content(
        f"Bạn đã yêu cầu đặt lại mật khẩu.\n"
        f"Đường dẫn: {reset_url}\n"
        f"Liên kết có hiệu lực trong 120 giây.\n"
        f"Nếu không yêu cầu, hãy bỏ qua email này."
    )

    message.add_alternative(
        f"""
        <html>
          <body>
            <h3>Đặt lại mật khẩu IriTech</h3>
            <p>Bạn đã yêu cầu đặt lại mật khẩu.</p>
            <p><a href="{escape(reset_url, quote=True)}">
              Đặt lại mật khẩu
            </a></p>
            <p>Liên kết chỉ có hiệu lực trong 120 giây.</p>
            <p>Nếu không yêu cầu, hãy bỏ qua email này.</p>
          </body>
        </html>
        """,
        subtype="html",
    )

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)
