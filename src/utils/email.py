# python
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# SMTP Configuration
import os

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))


def send_recovery_email(target_email: str, token: str):
    """
    Forensic Dispatch Protocol: Sends the signed JWT token to the personnel email.
    """
    try:
        msg = MIMEMultipart()
        msg["From"] = f"SmartPrep Security <{EMAIL_SENDER}>"
        msg["To"] = target_email
        msg["Subject"] = "SECURITY PROTOCOL: Credential Recovery Token"

        body = f"""
        PERSONNEL ACCESS RECOVERY SYSTEM
        --------------------------------
        A password reset has been initiated for this account.
        
        Your Forensic Recovery Token:
        {token}
        
        This token is valid for 15 minutes. If you did not request this, 
        please notify your system administrator immediately.
        
        SmartPrep Modern Security Division
        """
        msg.attach(MIMEText(body, "plain"))

        # Connect and Send
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()  # Secure the connection
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"SMTP Dispatch Error: {e}")
        return False
