from django.conf import settings
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.contrib import messages
from django.core.mail import send_mail
from ..models import CustomUser, EmailOTP
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.cache import never_cache
from django.db import transaction
from admin_apps.offers.services import process_referee_reward


@never_cache
def verify_otp(request):
    email = request.session.get('verify_email')
    pending_data = request.session.get('pending_signup_data')

    if not email:
        return redirect('signup')

    if request.method == "POST":
        otp_input = request.POST.get("otp")

        # Try to find OTP by email first (for new signups) or by user (for re-verification)
        otp_obj = EmailOTP.objects.filter(email=email).order_by('-created_at').first()
        
        # If not found by email, it might be an existing user re-verifying (if applicable)
        if not otp_obj:
            user_obj = CustomUser.objects.filter(email=email).first()
            if user_obj:
                otp_obj = user_obj.otps.order_by('-created_at').first()

        if not otp_obj:
            messages.error(request, "No verification code found. Please request a new one.")
            return redirect("verify-otp")

        if otp_obj.is_expired:
            messages.error(request, "Code expired. Please request a new one.")
            return redirect("verify-otp")

        if otp_obj.otp != otp_input:
            messages.error(request, "Invalid code. Please try again.")
            return redirect("verify-otp")

        # SUCCESS — Handle User Creation or Activation
        with transaction.atomic():
            if pending_data:
                # CREATE NEW USER from session data
                user = CustomUser.objects.create_user(
                    email=pending_data['email'],
                    password=pending_data['password'],
                    first_name=pending_data['first_name'],
                    last_name=pending_data['last_name'],
                    phone_number=pending_data['phone_number']
                )
                
                # Handle Referral
                ref_code = pending_data.get('entered_referral_code')
                if ref_code:
                    try:
                        referrer = CustomUser.objects.get(referral_code=ref_code)
                        user.referred_by = referrer
                        user.save()
                    except CustomUser.DoesNotExist:
                        pass # Should have been validated in signup, but safe check
                
                del request.session['pending_signup_data']
            else:
                # ACTIVATE EXISTING USER (if they were already in DB)
                user = CustomUser.objects.filter(email=email).first()
                if user:
                    user.is_active = True
                    user.save()
                else:
                    messages.error(request, "Registration data lost. Please sign up again.")
                    return redirect("signup")

            # Clean up
            otp_obj.delete()
            del request.session['verify_email']
            request.session.pop('referral_code', None)

            # Auto login
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')

            # Process referral reward
            process_referee_reward(user)

            messages.success(request, f"Verification successful! Welcome to TimeHub, {user.first_name or user.email}. 🎉")
            return redirect("home")

    # Get latest OTP for timer
    seconds_left = 0
    otp_obj = EmailOTP.objects.filter(email=email).order_by('-created_at').first()
    if not otp_obj:
        user_obj = CustomUser.objects.filter(email=email).first()
        if user_obj:
            otp_obj = user_obj.otps.order_by('-created_at').first()
            
    if otp_obj:
        expiry_time = otp_obj.created_at + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
        seconds_left = max(0, int((expiry_time - timezone.now()).total_seconds()))

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

    # Cooldown check
    last_otp = EmailOTP.objects.filter(email=email).order_by('-created_at').first()
    if not last_otp:
        user_obj = CustomUser.objects.filter(email=email).first()
        if user_obj:
            last_otp = user_obj.otps.order_by('-created_at').first()

    if last_otp and (timezone.now() - last_otp.created_at).total_seconds() < settings.RESET_OTP_COOLDWON_SEC:
        messages.error(request, "Please wait before requesting another code.")
        return redirect("verify-otp") if not is_reset else redirect("verify-otp-reset")

    # Create new OTP (either by email or user)
    user_obj = CustomUser.objects.filter(email=email).first()
    if user_obj:
        otp_obj = EmailOTP.objects.create(user=user_obj)
    else:
        otp_obj = EmailOTP.objects.create(email=email)

    send_mail(
        "Your Verification Code - TimeHub ⏱",
        f"""Hello,
        
Your verification code is: {otp_obj.otp}

This code is valid for 1 minute. 

If you did not request this, please ignore this email.

Best regards,
The TimeHub Team""",
        settings.EMAIL_HOST_USER,
        [email],
    )

    messages.success(request, "New code sent successfully!")
    return redirect("verify-otp") if not is_reset else redirect("verify-otp-reset")


@never_cache
def verify_otp_reset(request):
    """OTP verification step for the password-reset flow (Existing Users Only)."""
    email = request.session.get('reset_email')

    if not email:
        return redirect('forgot-password')

    if request.method == 'POST':
        otp_input = request.POST.get('otp', '').strip()

        try:
            user = CustomUser.objects.get(email=email)
            otp_obj = user.otps.latest('created_at')

            if otp_obj.is_expired:
                messages.error(request, 'Code expired. Please request a new one.')
                return redirect('verify-otp-reset')

            if otp_obj.otp != otp_input:
                messages.error(request, 'Invalid code. Please try again.')
                return redirect('verify-otp-reset')

            otp_obj.delete()
            request.session['otp_verified'] = True
            return redirect('reset-password')

        except (CustomUser.DoesNotExist, EmailOTP.DoesNotExist):
            messages.error(request, 'Invalid request or code expired.')
            return redirect('forgot-password')

    # Timer logic for reset
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