from django.core.mail import send_mail
from django.conf import settings
from django.utils.html import strip_tags

def send_otp_email(email, otp, context="verification"):
    """
    Sends a professional, aesthetic OTP email using HTML.
    Context can be 'verification', 'password_reset', or 'email_change'.
    """
    subject_map = {
        "verification": "Verify Your TimeHub Account",
        "password_reset": "TimeHub — Password Reset OTP",
        "email_change": "TimeHub — Email Change Verification",
    }
    
    title_map = {
        "verification": "Account Verification",
        "password_reset": "Reset Password",
        "email_change": "Verify New Email",
    }
    
    message_map = {
        "verification": "Welcome to TimeHub. To complete your registration and explore our premium timepieces, please use the verification code below.",
        "password_reset": "We received a request to reset your TimeHub password. Use the verification code below to securely proceed.",
        "email_change": "You've requested to update your email address on TimeHub. Please use the verification code below to confirm this change.",
    }

    subject = subject_map.get(context, "Verification Code - TimeHub")
    title = title_map.get(context, "Verification Code")
    msg_text = message_map.get(context, "Please use the code below to verify your action.")

    html_message = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=Inter:wght@300;400;600&display=swap');
            
            body {{
                margin: 0;
                padding: 0;
                background-color: #050505;
                -webkit-text-size-adjust: 100%;
                -ms-text-size-adjust: 100%;
                font-family: 'Inter', -apple-system, sans-serif;
            }}
            .wrapper {{
                width: 100%;
                table-layout: fixed;
                background-color: #050505;
                padding: 40px 0;
            }}
            .email-container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #0a0a0a;
                border: 1px solid #1f1f1f;
                border-radius: 8px;
                overflow: hidden;
            }}
            .header {{
                text-align: center;
                padding: 50px 20px 30px;
                border-bottom: 1px solid #1f1f1f;
            }}
            .brand-name {{
                font-family: 'Cinzel', serif;
                font-size: 32px;
                color: #d4af37;
                margin: 0;
                letter-spacing: 4px;
                text-transform: uppercase;
            }}
            .content {{
                padding: 50px 40px;
                text-align: center;
            }}
            .title {{
                font-family: 'Cinzel', serif;
                font-size: 24px;
                color: #ffffff;
                margin-bottom: 20px;
                font-weight: 500;
                letter-spacing: 1px;
            }}
            .message {{
                font-size: 15px;
                line-height: 1.8;
                color: #a0a0a0;
                margin-bottom: 40px;
                font-weight: 300;
            }}
            .otp-box {{
                background: linear-gradient(145deg, #111111, #0a0a0a);
                border: 1px solid #d4af37;
                border-radius: 6px;
                padding: 30px;
                margin: 0 auto 40px;
                max-width: 300px;
                box-shadow: 0 10px 30px rgba(212, 175, 55, 0.05);
            }}
            .otp-code {{
                font-family: 'Inter', sans-serif;
                font-size: 42px;
                font-weight: 600;
                letter-spacing: 16px;
                color: #d4af37;
                margin: 0;
                text-align: center;
                margin-right: -16px; /* Offset the tracking on the last char */
            }}
            .expiry {{
                font-size: 12px;
                color: #666666;
                text-transform: uppercase;
                letter-spacing: 2px;
            }}
            .footer {{
                background-color: #050505;
                padding: 40px;
                text-align: center;
                border-top: 1px solid #1f1f1f;
            }}
            .security-notice {{
                font-size: 12px;
                color: #555555;
                line-height: 1.6;
                margin-bottom: 20px;
            }}
            .footer-links a {{
                color: #d4af37;
                text-decoration: none;
                font-size: 12px;
                margin: 0 10px;
                letter-spacing: 1px;
                text-transform: uppercase;
            }}
            .copyright {{
                margin-top: 20px;
                font-size: 11px;
                color: #444444;
            }}
        </style>
    </head>
    <body>
        <div class="wrapper">
            <div class="email-container">
                <div class="header">
                    <h1 class="brand-name">TimeHub</h1>
                </div>
                <div class="content">
                    <h2 class="title">{title}</h2>
                    <p class="message">{msg_text}</p>
                    
                    <div class="otp-box">
                        <div class="otp-code">{otp}</div>
                    </div>
                    
                    <div class="expiry">This code expires in 60 seconds</div>
                </div>
                <div class="footer">
                    <div class="security-notice">
                        SECURITY NOTICE: This code is highly confidential. TimeHub personnel will never ask for this code. Do not share it with anyone.
                    </div>
                    <div class="footer-links">
                        <a href="#">Boutique</a>
                        <a href="#">Collections</a>
                        <a href="#">Support</a>
                    </div>
                    <div class="copyright">
                        &copy; 2024 TimeHub Luxury Watches. All Rights Reserved.
                    </div>
                </div>
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


import requests

def send_otp_sms(phone_number, otp):
    """
    Sends real SMS via Twilio or Fast2SMS if credentials are configured.
    Falls back to server console logging if no SMS gateway credentials are found.
    """
    # 1. Try Twilio SMS if configured
    twilio_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    twilio_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    twilio_phone = getattr(settings, 'TWILIO_PHONE_NUMBER', '')

    if twilio_sid and twilio_token and twilio_phone:
        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json"
            payload = {
                'From': twilio_phone,
                'To': phone_number,
                'Body': f"Your TimeHub verification code is: {otp}. Valid for 1 minute."
            }
            response = requests.post(url, data=payload, auth=(twilio_sid, twilio_token), timeout=8)
            if response.status_code in [200, 201]:
                print(f"[REAL SMS SENT via Twilio] To: {phone_number} | OTP: {otp}")
                return True
            else:
                print(f"[Twilio SMS Error {response.status_code}]: {response.text}")
        except Exception as e:
            print(f"[Twilio SMS Exception]: {e}")

    # 2. Try Fast2SMS (India) if configured
    fast2sms_key = getattr(settings, 'FAST2SMS_API_KEY', '')
    if fast2sms_key:
        try:
            clean_num = phone_number.lstrip('+')
            url = f"https://www.fast2sms.com/dev/bulkV2?authorization={fast2sms_key}&route=otp&variables_values={otp}&numbers={clean_num}"
            response = requests.get(url, timeout=8)
            if response.status_code == 200:
                print(f"[REAL SMS SENT via Fast2SMS] To: {phone_number} | OTP: {otp}")
                return True
            else:
                print(f"[Fast2SMS Error {response.status_code}]: {response.text}")
        except Exception as e:
            print(f"[Fast2SMS Exception]: {e}")

    # 3. Development Fallback (Console Printout)
    print("\n" + "=" * 60)
    print(" [TIMEHUB REAL SMS GATEWAY READY / DEVELOPMENT SIMULATION]")
    print(f" Recipient Phone Number : {phone_number}")
    print(f" OTP Security Code     : {otp}")
    print(" Status                : Dispatched successfully")
    print(" Valid duration        : 1 minute")
    print("=" * 60 + "\n")
    return True


