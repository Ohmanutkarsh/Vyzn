"""
Outbound Email Service for VYZN Netra.
Dispatches real OTP verification codes via:
1. Direct SMTP (Gmail SMTP, custom SMTP)
2. Resend API (if RESEND_API_KEY configured)
3. Supabase Auth OTP (if Supabase configured)
"""

from __future__ import annotations
import os
import smtplib
import logging
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional

try:
    from dotenv import load_dotenv
    from pathlib import Path
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except Exception:
    pass

logger = logging.getLogger("vyzn.email")


def get_email_provider_status() -> Dict[str, Any]:
    """Returns current outbound email provider status."""
    has_smtp = bool(
        (os.environ.get("SMTP_USER") or os.environ.get("GMAIL_USER"))
        and (os.environ.get("SMTP_PASSWORD") or os.environ.get("GMAIL_APP_PASSWORD"))
    )
    has_resend = bool(os.environ.get("RESEND_API_KEY"))
    has_supabase = bool(os.environ.get("VYZN_SUPABASE_URL") and os.environ.get("VYZN_SUPABASE_ANON_KEY"))

    configured = has_smtp or has_resend or has_supabase
    provider = "smtp" if has_smtp else ("resend" if has_resend else ("supabase" if has_supabase else "none"))
    return {
        "configured": configured,
        "provider": provider,
        "has_smtp": has_smtp,
        "has_resend": has_resend,
        "has_supabase": has_supabase
    }


def send_email_otp(recipient_email: str, code: str) -> Dict[str, Any]:
    """
    Sends a real 6-digit OTP code to the recipient's email address.
    Tries configured providers in order: SMTP -> Resend -> Supabase.
    """
    recipient = recipient_email.strip().lower()

    # 1. Direct SMTP (e.g. Gmail SMTP)
    smtp_user = (os.environ.get("SMTP_USER") or os.environ.get("GMAIL_USER") or "").strip()
    smtp_pass = (os.environ.get("SMTP_PASSWORD") or os.environ.get("GMAIL_APP_PASSWORD") or "").strip()
    if smtp_user and smtp_pass:
        # App passwords may be provided with spaces (e.g. "eiiq eogi vhcc ukvc")
        smtp_pass = smtp_pass.replace(" ", "")
        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", 587))
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"{code} is your VYZN verification code"
            msg["From"] = f"VYZN Security <{smtp_user}>"
            msg["To"] = recipient

            text_body = f"Your VYZN verification code is: {code}\nThis code is valid for 10 minutes.\n\nIf you did not request this code, please ignore this email."
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head><meta charset="utf-8"></head>
            <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f6f8fa; margin: 0; padding: 32px 16px;">
              <table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 460px; background: #ffffff; border: 1px solid #d0d7de; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06);">
                <tr>
                  <td style="padding: 24px 28px 16px 28px; border-bottom: 1px solid #eaeef2;">
                    <span style="font-size: 18px; font-weight: 700; color: #1f2328; letter-spacing: -0.02em;">VYZN</span>
                  </td>
                </tr>
                <tr>
                  <td style="padding: 28px;">
                    <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 600; color: #1f2328;">Check your email</h2>
                    <p style="margin: 0 0 24px 0; font-size: 14px; line-height: 1.5; color: #57606a;">
                      Use this 6-digit verification code to sign in to your VYZN Retail Surveillance system. It expires in 10 minutes.
                    </p>
                    <div style="background: #f6f8fa; border: 1.5px solid #d0d7de; border-radius: 6px; padding: 18px 24px; text-align: center; margin-bottom: 24px;">
                      <span style="font-family: 'SF Mono', Consolas, Monaco, monospace; font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #0969da;">{code}</span>
                    </div>
                    <p style="margin: 0; font-size: 12px; line-height: 1.5; color: #8c959f;">
                      If you did not request this code, you can safely ignore this message. Never share this code with anyone.
                    </p>
                  </td>
                </tr>
              </table>
            </body>
            </html>
            """
            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(smtp_host, smtp_port, timeout=12.0) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [recipient], msg.as_string())

            logger.info(f"[EMAIL] Successfully sent real OTP email to {recipient} via {smtp_host}")
            return {
                "sent": True,
                "provider": "smtp",
                "recipient": recipient
            }
        except Exception as e:
            logger.error(f"[EMAIL] SMTP dispatch failed to {recipient}: {e}")
            return {
                "sent": False,
                "provider": "smtp",
                "error": str(e)
            }

    # 2. Resend API
    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key:
        try:
            resend_from = os.environ.get("RESEND_FROM", "VYZN <onboarding@resend.dev>")
            resp = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
                json={
                    "from": resend_from,
                    "to": [recipient],
                    "subject": f"{code} is your VYZN verification code",
                    "html": f"<p>Your VYZN verification code is: <strong>{code}</strong>. Valid for 10 minutes.</p>"
                },
                timeout=10.0
            )
            if resp.status_code in [200, 201]:
                logger.info(f"[EMAIL] Sent real OTP to {recipient} via Resend")
                return {"sent": True, "provider": "resend", "recipient": recipient}
            else:
                logger.warning(f"[EMAIL] Resend returned {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"[EMAIL] Resend dispatch error: {e}")

    # 3. Supabase Auth OTP
    supabase_url = os.environ.get("VYZN_SUPABASE_URL", "").rstrip("/")
    supabase_anon_key = os.environ.get("VYZN_SUPABASE_ANON_KEY", "")
    if supabase_url and supabase_anon_key:
        try:
            resp = requests.post(
                f"{supabase_url}/auth/v1/otp",
                headers={"apikey": supabase_anon_key, "Content-Type": "application/json"},
                json={"email": recipient, "create_user": True},
                timeout=10.0
            )
            if resp.status_code in [200, 201]:
                logger.info(f"[EMAIL] Sent OTP to {recipient} via Supabase Auth mailer")
                return {"sent": True, "provider": "supabase", "recipient": recipient}
            else:
                logger.warning(f"[EMAIL] Supabase Auth OTP returned {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"[EMAIL] Supabase Auth OTP dispatch error: {e}")

    logger.warning(f"[EMAIL] No live outbound email provider configured. Code for {recipient}: {code}")
    return {
        "sent": False,
        "provider": "none",
        "message": "Configure Gmail SMTP (SMTP_USER & SMTP_PASSWORD) or Supabase keys in .env to send real emails."
    }
