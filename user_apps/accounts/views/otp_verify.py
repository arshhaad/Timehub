from django.conf import settings
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.contrib import messages
from django.core.mail import send_mail
from ..models import CustomUser, EmailOTP
from django.utils import timezone
from django.views.decorators.cache import never_cache


@never_cache
def verify_otp(request):
    email = request.session.get('verify_email')

    if not email:
        return redirect('signup')

    if request.method == "POST":
        otp_input = request.POST.get("otp")

        try:
            user = CustomUser.objects.get(email=email)
            otp_obj = user.otps.latest('created_at')

            if otp_obj.is_expired:
                messages.error(request, "OTP expired. Please request a new one.")
                return redirect("verify-otp")

            if otp_obj.otp != otp_input:
                messages.error(request, "Invalid OTP. Please try again.")
                return redirect("verify-otp")

            # success — activate user
            user.is_active = True
            user.save()

            # clean up
            otp_obj.delete()
            del request.session['verify_email']

            # auto login
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')

            messages.success(request, "Email verified successfully!")
            return redirect("home")

        except CustomUser.DoesNotExist:
            messages.error(request, "User not found. Please sign up again.")
            return redirect("signup")
        except EmailOTP.DoesNotExist:
            messages.error(request, "No OTP found. Please request a new one.")
            return redirect("verify-otp")

    return render(request, "accounts/verify_otp.html", {"email": email})


@never_cache
def resend_otp(request):
    email = request.session.get('verify_email')

    if not email:
        return redirect('signup')

    try:
        user = CustomUser.objects.get(email=email)
    except CustomUser.DoesNotExist:
        messages.error(request, "User not found.")
        return redirect('signup')

    last_otp = user.otps.order_by('-created_at').first()

    # cooldown check
    if last_otp and (timezone.now() - last_otp.created_at).total_seconds() < settings.RESET_OTP_COOLDWON_SEC:
        messages.error(request, "Please wait before requesting another OTP.")
        return redirect("verify-otp")

    otp_obj = EmailOTP.objects.create(user=user)

    send_mail(
        "Your OTP Code",
        f"""Hello from TimeHub,

We received a request to verify your OTP.

🔐 Your One-Time Password (OTP) is: {otp_obj.otp}

This OTP is valid for 2 minutes. Please do not share it with anyone for security reasons.
---
🌟 About TimeHub

At TimeHub, we bring you a curated collection of premium timepieces crafted with precision, elegance, and timeless design. Every watch tells a story — of craftsmanship, innovation, and style.

Whether you're looking for luxury, performance, or everyday elegance, TimeHub is your trusted destination.

If you did not request this OTP, you can safely ignore this email. Your account remains secure.

Need help? Our support team is always here for you.

Best regards,
The TimeHub Team""",
        settings.EMAIL_HOST_USER,
        [email],
    )

    messages.success(request, "OTP resent successfully!")
    return redirect("verify-otp")


@never_cache
def verify_otp_reset(request):
    """OTP verification step for the password-reset flow."""
    email = request.session.get('reset_email')

    if not email:
        return redirect('forgot-password')

    if request.method == 'POST':
        otp_input = request.POST.get('otp', '').strip()

        try:
            user = CustomUser.objects.get(email=email)
            otp_obj = user.otps.latest('created_at')

            if otp_obj.is_expired:
                messages.error(request, 'OTP expired. Please request a new one.')
                return redirect('verify-otp-reset')

            if otp_obj.otp != otp_input:
                messages.error(request, 'Invalid OTP. Please try again.')
                return redirect('verify-otp-reset')

            # Mark verified and clean up OTP record
            otp_obj.delete()
            request.session['otp_verified'] = True

            return redirect('reset-password')

        except CustomUser.DoesNotExist:
            messages.error(request, 'User not found.')
            return redirect('forgot-password')
        except EmailOTP.DoesNotExist:
            messages.error(request, 'No OTP found. Please request a new one.')
            return redirect('forgot-password')

    return render(request, 'accounts/verify_otp_reset.html', {'email': email})