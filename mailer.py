import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import config

from email.header import Header

def send_email(subject, html_content):
    sender = config.get("GMAIL_ADDRESS")
    password = config.get("GMAIL_APP_PASSWORD")
    recipient = config.get("REPORT_RECIPIENT", sender) # Default to self
    
    if not sender or not password:
        print("Skipping email: GMAIL_ADDRESS or GMAIL_APP_PASSWORD not configured.")
        return False
        
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, 'utf-8')
    msg["From"] = sender
    msg["To"] = recipient

    # Attach the HTML body
    part = MIMEText(html_content, "html", "utf-8")
    msg.attach(part)

    try:
        # Use Gmail SMTP server
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.ehlo()
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
        server.quit()
        print(f"Email '{subject}' sent successfully to {recipient}.")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
