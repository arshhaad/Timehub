from datetime import timedelta
from django.conf import settings
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.db import transaction

from ..models import CustomUser, EmailOTP
from ..utils import send_otp_email
from admin_apps.offers.services import process_referee_reward




@never_cache
def verify_otp(request):
    """Verify OTP for new account registration."""
    email = request.session.get('verify_email')
    pending_data = request.session.get('pending_signup_data')

    if not email:
        return redirect('signup')

    if request.method == "POST":
        otp_input = request.POST.get("otp")

        # 1. Locate the valid OTP object
        otp_obj = EmailOTP.objects.filter(email=email).order_by('-created_at').first()
        if not otp_obj:
            user_obj = CustomUser.objects.filter(email=email).first()
            if user_obj:
                otp_obj = user_obj.otps.order_by('-created_at').first()

        # 2. Validation Checks
        if not otp_obj:
            messages.error(request, "Verification session not found. Please sign up again.")
            return redirect("verify-otp")

        if otp_obj.is_expired:
            messages.error(request, "The verification code has expired. Please request a fresh one.")
            return redirect("verify-otp")

        if otp_obj.otp != otp_input:
            messages.error(request, "Invalid verification code. Please check your email and try again.")
            return redirect("verify-otp")

        # 3. SUCCESS — Commit to Database
        with transaction.atomic():
            if pending_data:
                # Fresh Signup
                user = CustomUser.objects.create_user(
                    email=pending_data['email'],
                    password=pending_data['password'],
                    first_name=pending_data['first_name'],
                    last_name=pending_data['last_name'],
                    phone_number=pending_data['phone_number']
                )
                
                # Link Referral if applicable
                ref_code = pending_data.get('entered_referral_code')
                if ref_code:
                    try:
                        referrer = CustomUser.objects.get(referral_code=ref_code)
                        user.referred_by = referrer
                        user.save()
                    except CustomUser.DoesNotExist:
                        pass 
                
                del request.session['pending_signup_data']
            else:
                # Activation of existing guest-like record
                user = CustomUser.objects.filter(email=email).first()
                if user:
                    user.is_active = True
                    user.save()
                else:
                    messages.error(request, "Registration session expired. Please start over.")
                    return redirect("signup")

            # Cleanup Security Tokens
            otp_obj.delete()
            del request.session['verify_email']
            request.session.pop('referral_code', None)

            # Standard Django Login
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')

            # Process Referral Rewards
            if user.referred_by:
                process_referee_reward(user)

            messages.success(request, f"Welcome to TimeHub, {user.first_name}! Your account has been verified successfully.")
            return redirect("home")

    # Calculate timer for the frontend
    seconds_left = 0
    latest_otp = EmailOTP.objects.filter(email=email).order_by('-created_at').first()
    if not latest_otp:
        user_obj = CustomUser.objects.filter(email=email).first()
        if user_obj: latest_otp = user_obj.otps.order_by('-created_at').first()
            
    if latest_otp:
        expiry = latest_otp.created_at + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
        seconds_left = max(0, int((expiry - timezone.now()).total_seconds()))

    return render(request, "accounts/verify_otp.html", {
        "email": email, "seconds_left": seconds_left
    })




@never_cache
def verify_otp_reset(request):
    """Verify OTP for password reset request."""
    email = request.session.get('reset_email')
    if not email:
        return redirect('forgot-password')

    if request.method == 'POST':
        otp_input = request.POST.get('otp', '').strip()

        try:
            user = CustomUser.objects.get(email=email)
            otp_obj = user.otps.latest('created_at')

            if otp_obj.is_expired:
                messages.error(request, 'The code has expired. Please request a new security code.')
                return redirect('verify-otp-reset')

            if otp_obj.otp != otp_input:
                messages.error(request, 'Incorrect verification code. Access denied.')
                return redirect('verify-otp-reset')

            # Success — Flag session as verified for the next step (reset form)
            otp_obj.delete()
            request.session['otp_verified'] = True
            return redirect('reset-password')

        except (CustomUser.DoesNotExist, EmailOTP.DoesNotExist):
            messages.error(request, 'Verification session not found. Please restart the reset process.')
            return redirect('forgot-password')

    # Timer logic for UI
    seconds_left = 0
    try:
        user = CustomUser.objects.get(email=email)
        latest = user.otps.latest('created_at')
        expiry = latest.created_at + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
        seconds_left = max(0, int((expiry - timezone.now()).total_seconds()))
    except: pass

    return render(request, 'accounts/verify_otp_reset.html', {
        'email': email, 'seconds_left': seconds_left
    })




@never_cache
def resend_otp(request):
    """Resend a fresh OTP to the user email."""
    email = request.session.get('verify_email') or request.session.get('reset_email')
    is_reset = 'reset_email' in request.session

    if not email:
        return redirect('signup') if not is_reset else redirect('forgot-password')

    # Cooldown Security Check
    last_otp = EmailOTP.objects.filter(email=email).order_by('-created_at').first()
    if not last_otp:
        u = CustomUser.objects.filter(email=email).first()
        if u: last_otp = u.otps.order_by('-created_at').first()

    if last_otp and (timezone.now() - last_otp.created_at).total_seconds() < settings.RESET_OTP_COOLDWON_SEC:
        messages.error(request, "Security wait: Please wait a moment before requesting another code.")
        return redirect("verify-otp") if not is_reset else redirect("verify-otp-reset")

    # Create & Send Fresh Token
    u = CustomUser.objects.filter(email=email).first()
    otp_obj = EmailOTP.objects.create(user=u) if u else EmailOTP.objects.create(email=email)
    send_otp_email(email, otp_obj.otp, context="password_reset" if is_reset else "verification")

    messages.success(request, f"A new security code has been dispatched to {email}.")
    return redirect("verify-otp") if not is_reset else redirect("verify-otp-reset")