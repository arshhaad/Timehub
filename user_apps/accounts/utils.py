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
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;800&display=swap');
            
            body {{
                margin: 0;
                padding: 0;
                background-color: #f1f5f9;
                -webkit-text-size-adjust: 100%;
                -ms-text-size-adjust: 100%;
            }}
            .email-container {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 24px;
                overflow: hidden;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.15);
            }}
            .header {{
                background-color: #0f172a;
                padding: 45px 20px;
                text-align: center;
                border-bottom: 4px solid #ff8a00;
            }}
            .logo-wrapper {{
                display: inline-block;
                text-decoration: none;
            }}
            /* High-precision CSS Clock Logo */
            .logo-clock-container {{
                display: inline-block;
                vertical-align: middle;
                margin-right: 12px;
            }}
            .clock-outer {{
                width: 56px;
                height: 56px;
                background-color: #ff8a00;
                border-radius: 50%;
                position: relative;
                display: flex;
                align-items: center;
                justify-content: center;
            }}
            .clock-inner {{
                width: 38px;
                height: 38px;
                background-color: #000000;
                border-radius: 50%;
                position: relative;
            }}
            .hand-hour {{
                position: absolute;
                top: 50%;
                left: 50%;
                width: 2px;
                height: 10px;
                background-color: #ffffff;
                transform-origin: bottom;
                transform: translate(-50%, -100%) rotate(0deg);
                border-radius: 2px;
            }}
            .hand-min {{
                position: absolute;
                top: 50%;
                left: 50%;
                width: 12px;
                height: 2px;
                background-color: #ffffff;
                transform-origin: left;
                transform: translate(0, -50%) rotate(0deg);
                border-radius: 2px;
            }}
            .logo-text {{
                font-family: 'Inter', sans-serif;
                font-size: 40px;
                font-weight: 800;
                color: #ffffff;
                letter-spacing: -1.5px;
                display: inline-block;
                vertical-align: middle;
                margin: 0;
                line-height: 1;
            }}
            .content {{
                padding: 60px 45px;
                text-align: center;
                color: #334155;
            }}
            .title {{
                font-size: 30px;
                font-weight: 800;
                margin-bottom: 16px;
                color: #0f172a;
                letter-spacing: -0.025em;
            }}
            .message {{
                font-size: 17px;
                line-height: 1.6;
                margin-bottom: 35px;
                color: #64748b;
            }}
            .otp-section {{
                background-color: #f8fafc;
                border-radius: 20px;
                padding: 40px 20px;
                margin: 30px 0;
                border: 1px solid #f1f5f9;
            }}
            .otp-code {{
                font-size: 52px;
                font-weight: 800;
                letter-spacing: 12px;
                color: #0f172a;
                display: block;
                margin-bottom: 25px;
                font-family: 'Courier New', Courier, monospace;
                user-select: all;
                -webkit-user-select: all;
                cursor: pointer;
            }}
            .copy-button {{
                display: inline-block;
                background-color: #ff8a00;
                color: #ffffff;
                padding: 14px 36px;
                border-radius: 12px;
                font-size: 16px;
                font-weight: 700;
                text-decoration: none;
                text-transform: uppercase;
                letter-spacing: 1px;
                box-shadow: 0 4px 12px rgba(255, 138, 0, 0.3);
                /* Fallback for environments that support inline JS (rare in email) */
                cursor: copy;
            }}
            .copy-instruction {{
                display: block;
                font-size: 12px;
                color: #94a3b8;
                margin-top: 15px;
                font-weight: 500;
            }}
            .expiry-pill {{
                font-size: 13px;
                color: #ef4444;
                font-weight: 700;
                background-color: #fef2f2;
                display: inline-block;
                padding: 8px 16px;
                border-radius: 9999px;
                margin-top: 20px;
            }}
            .footer {{
                background-color: #f8fafc;
                padding: 45px;
                text-align: center;
                border-top: 1px solid #f1f5f9;
            }}
            .security-box {{
                font-size: 12px;
                color: #94a3b8;
                max-width: 450px;
                margin: 0 auto 30px auto;
                line-height: 1.6;
                padding: 15px;
                background-color: #ffffff;
                border-radius: 12px;
                border: 1px solid #f1f5f9;
            }}
            .social-links {{
                margin-bottom: 20px;
            }}
            .social-links a {{
                color: #475569;
                text-decoration: none;
                margin: 0 12px;
                font-weight: 700;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <div class="email-container">
            <div class="header">
                <div class="logo-wrapper">
                    <div class="logo-clock-container">
                        <div class="clock-outer">
                            <div class="clock-inner">
                                <div class="hand-hour"></div>
                                <div class="hand-min"></div>
                            </div>
                        </div>
                    </div>
                    <h1 class="logo-text">TimeHub</h1>
                </div>
            </div>
            <div class="content">
                <h2 class="title">{title}</h2>
                <p class="message">{msg_text}</p>
                
                <div class="otp-section">
                    <span class="otp-code" id="text">{otp}</span>
                    <button id="copyBtn" onclick="copyText()" class="copy-button" style="border: none; cursor: pointer;">Copy Code</button>
                    <span class="copy-instruction">Tap the code above to select instantly</span>
                </div>

                <div class="expiry-pill">⏳ Expires in 60 seconds</div>
            </div>
            <div class="footer">
                <div class="security-box">
                    <strong>SECURITY ALERT:</strong> This code is for your eyes only. TimeHub will never 
                    call or email you asking for this code.
                </div>
                <div class="social-links">
                    <a href="#">Instagram</a> • <a href="#">Twitter</a> • <a href="#">Facebook</a>
                </div>
                <div class="copyright" style="font-size: 13px; color: #94a3b8;">
                    &copy; 2024 TimeHub Luxury Watches. All rights reserved.<br>
                    <span style="color: #ff8a00; font-weight: 600;">Timeless Quality • Global Luxury</span>
                </div>
            </div>
        </div>

        <script>
            function copyText() {{
                const text = document.getElementById("text").innerText;
                const button = document.getElementById("copyBtn");

                navigator.clipboard.writeText(text)
                    .then(() => {{
                        button.innerText = "Copied ✅";

                        setTimeout(() => {{
                            button.innerText = "Copy Code";
                        }}, 2000);
                    }})
                    .catch(err => {{
                        console.log("Copy failed:", err);
                    }});
            }}
        </script>
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
