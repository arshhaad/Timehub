from django.core.mail import send_mail
from django.conf import settings
from django.utils.html import strip_tags

def send_otp_email(email, otp, context="verification"):
    """
    Sends a professional, aesthetic OTP email using HTML.
    Context can be 'verification' or 'password_reset'.
    """
    subject_map = {
        "verification": "Verify Your TimeHub Account ⏱",
        "password_reset": "TimeHub — Password Reset OTP 🔐",
        "email_change": "TimeHub — Email Change Verification ✉️",
    }
    
    title_map = {
        "verification": "Verify Your Account",
        "password_reset": "Reset Your Password",
        "email_change": "Verify Your New Email",
    }
    
    message_map = {
        "verification": "Welcome to TimeHub! To complete your registration and start exploring our premium timepieces, please use the verification code below.",
        "password_reset": "We received a request to reset your TimeHub password. Use the verification code below to proceed with the reset process.",
        "email_change": "You've requested to update your email address on TimeHub. Please use the verification code below to confirm this change.",
    }

    subject = subject_map.get(context, "Verification Code - TimeHub")
    title = title_map.get(context, "Verification Code")
    msg_text = message_map.get(context, "Please use the code below to verify your action.")

    html_message = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            .email-container {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 12px;
                overflow: hidden;
            }}
            .header {{
                background-color: #000000;
                padding: 30px;
                text-align: center;
            }}
            .logo {{
                font-size: 28px;
                font-weight: 800;
                color: #ffffff;
                letter-spacing: 2px;
            }}
            .logo span {{
                color: #f98822; /* Primary brand color */
            }}
            .content {{
                padding: 40px;
                text-align: center;
                color: #333333;
            }}
            .title {{
                font-size: 24px;
                font-weight: 700;
                margin-bottom: 20px;
                color: #000000;
            }}
            .message {{
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 30px;
                color: #666666;
            }}
            .otp-box {{
                background-color: #f8f9fa;
                border: 2px dashed #f98822;
                border-radius: 8px;
                padding: 20px;
                font-size: 36px;
                font-weight: 800;
                letter-spacing: 10px;
                color: #000000;
                display: inline-block;
                margin-bottom: 30px;
            }}
            .expiry {{
                font-size: 14px;
                color: #ef4444;
                font-weight: 600;
                margin-bottom: 20px;
            }}
            .footer {{
                background-color: #f8f9fa;
                padding: 20px;
                text-align: center;
                font-size: 12px;
                color: #999999;
            }}
            .warning {{
                font-size: 13px;
                color: #999999;
                margin-top: 20px;
                padding-top: 20px;
                border-top: 1px solid #eeeeee;
            }}
        </style>
    </head>
    <body>
        <div class="email-container">
            <div class="header">
                <div class="logo">TimeHub<span>.</span></div>
            </div>
            <div class="content">
                <div class="title">{title}</div>
                <div class="message">{msg_text}</div>
                <div class="otp-box">{otp}</div>
                <div class="expiry">⏳ This code is valid for 1 minute only.</div>
                <div class="warning">
                    If you did not request this code, you can safely ignore this email. 
                    For your security, never share this code with anyone.
                </div>
            </div>
            <div class="footer">
                &copy; 2024 TimeHub Luxury Watches. All rights reserved.<br>
                Premium Quality • Timeless Style
            </div>
        </div>
    </body>
    </html>
    """
    
    # Plain text fallback
    plain_message = f"{title}\n\n{msg_text}\n\nYOUR CODE: {otp}\n\nValid for 1 minute only.\n\nBest regards,\nThe TimeHub Team"

    send_mail(
        subject=subject,
        message=plain_message,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[email],
        html_message=html_message,
        fail_silently=False,
    )
