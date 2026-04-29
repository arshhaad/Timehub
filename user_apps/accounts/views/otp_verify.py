from django.conf import settings
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.contrib import messages
from django.core.mail import send_mail
from ..models import CustomUser, EmailOTP
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.cache import never_cache
from admin_apps.offers.services import process_referee_reward


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

            # Process referral reward for referee
            process_referee_reward(user)

            messages.success(request, f"Email verified! Welcome to TimeHub, {user.first_name or user.email}. 🎉")
            return redirect("home")

        except CustomUser.DoesNotExist:
            messages.error(request, "User not found. Please sign up again.")
            return redirect("signup")
        except EmailOTP.DoesNotExist:
            messages.error(request, "No OTP found. Please request a new one.")
            return redirect("verify-otp")

    # Get latest OTP for timer
    seconds_left = 0
    try:
        user = CustomUser.objects.get(email=email)
        otp_obj = user.otps.latest('created_at')
        expiry_time = otp_obj.created_at + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
        seconds_left = max(0, int((expiry_time - timezone.now()).total_seconds()))
    except (CustomUser.DoesNotExist, EmailOTP.DoesNotExist):
        pass

    return render(request, "accounts/verify_otp.html", {
        "email": email,
        "seconds_left": seconds_left
    })


@never_cache
def resend_otp(request):
    email = request.session.get('verify_email') or request.session.get('reset_email')
    is_reset = 'reset_email' in request.session

    if not email:
        return redirect('signup') if not is_reset else redirect('forgot-password')

    try:
        user = CustomUser.objects.get(email=email)
    except CustomUser.DoesNotExist:
        messages.error(request, "User not found.")
        return redirect('signup')

    last_otp = user.otps.order_by('-created_at').first()

    # cooldown check
    if last_otp and (timezone.now() - last_otp.created_at).total_seconds() < settings.RESET_OTP_COOLDWON_SEC:
        messages.error(request, "Please wait before requesting another OTP.")
        return redirect("verify-otp") if not is_reset else redirect("verify-otp-reset")

    otp_obj = EmailOTP.objects.create(user=user)

    send_mail(
        "Your OTP Code",
        f"""Hello from TimeHub,

We received a request to verify your OTP.

🔐 Your One-Time Password (OTP) is: {otp_obj.otp}

This OTP is valid for 1 minute. Please do not share it with anyone for security reasons.
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
    return redirect("verify-otp") if not is_reset else redirect("verify-otp-reset")


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

    # Get latest OTP for timer
    seconds_left = 0
    try:
        user = CustomUser.objects.get(email=email)
        otp_obj = user.otps.latest('created_at')
        expiry_time = otp_obj.created_at + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
        seconds_left = max(0, int((expiry_time - timezone.now()).total_seconds()))
    except (CustomUser.DoesNotExist, EmailOTP.DoesNotExist):
        pass

    return render(request, 'accounts/verify_otp_reset.html', {
        'email': email,
        'seconds_left': seconds_left
    })