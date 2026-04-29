from django.shortcuts import render, redirect, reverse
from django.contrib import messages
from django.contrib.auth import login, logout
from django.core.mail import send_mail
from django.conf import settings
from ..forms import SignupForm, LoginForm,ForgotPasswordForm,ResetPasswordForm
from ..models import CustomUser, EmailOTP
from django.views.decorators.cache import never_cache


@never_cache
def signup_view(request):
    if request.user.is_authenticated:
        return redirect('landing_view')

    if request.method == 'POST':
        form = SignupForm(request.POST)

        if form.is_valid():
            user = form.save(commit=False)
            
            # Handle referral code — validate before proceeding
            ref_code = form.cleaned_data.get('referral_code')
            if ref_code:
                try:
                    referrer = CustomUser.objects.get(referral_code=ref_code)
                    user.referred_by = referrer
                except CustomUser.DoesNotExist:
                    form.add_error('referral_code', 'Invalid referral code. Please check and try again.')
                    return render(request, 'accounts/signup.html', {'form': form})

            # deactivate until email verified
            user.is_active = False
            user.save()

            # Clear session referral code after successful use
            request.session.pop('referral_code', None)

            # create OTP
            otp_obj = EmailOTP.objects.create(user=user)

            # send email
            send_mail(
                subject='Your OTP Code',
                message=f'Your OTP is {otp_obj.otp}',
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[user.email],
            )

            # store email in session (for verification step)
            request.session['verify_email'] = user.email

            messages.success(request, 'OTP sent to your email')

            return redirect('verify-otp')

        # form invalid → fall through and re-render
    else:
        # Token URL approach: check session first, then fall back to ?ref= param
        ref_code = request.session.get('referral_code', '') or request.GET.get('ref', '')
        form = SignupForm(initial={'referral_code': ref_code})

    return render(request, 'accounts/signup.html', {'form': form})


@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect('landing_view')

    if request.method == 'POST':
        form = LoginForm(request.POST)

        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']

            try:
                user = CustomUser.objects.get(email=email)
            except CustomUser.DoesNotExist:
                messages.error(request, 'Invalid email or password')
                return render(request, 'accounts/login.html', {'form': form})

            if not user.check_password(password):
                messages.error(request, 'Invalid email or password')
                return render(request, 'accounts/login.html', {'form': form})

            # user exists and password is correct, but not verified
            if not user.is_active:
                # generate a fresh OTP and send it
                otp_obj = EmailOTP.objects.create(user=user)
                send_mail(
                    subject='Your OTP Code',
                    message=f"""Hello from TimeHub ⏱
                                Your OTP is: {otp_obj.otp}
                                Valid for 1 minute.
                                Do not share it with anyone.
                                - TimeHub Team 🚀
                                """,
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[user.email],
                )
                request.session['verify_email'] = user.email
                messages.warning(request, 'Please verify your email first. A new OTP has been sent.')
                return redirect('verify-otp')

            # all good — log in
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, f'Successfully signed in as {user.email}. Welcome back!')
            return redirect('landing_view')

    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {'form': form})


@never_cache
def logout_view(request):
    logout(request)
    return redirect('landing_view')


@never_cache
def forgot_password(request):
    form = ForgotPasswordForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            messages.error(request, 'No account found with that email.')
            return render(request, 'accounts/forgot.html', {'form': form})

        # Generate a fresh OTP
        otp_obj = EmailOTP.objects.create(user=user)

        # Store email in session so the verify step knows who to look up
        request.session['reset_email'] = email

        send_mail(
            subject='TimeHub — Password Reset OTP',
            message=f"""Hello from TimeHub ⏱
            You requested a password reset.
            🔐  YOUR ONE-TIME PASSWORD

                    {otp_obj.otp}   
                    
            ⏳ Valid for 1 minute only.
            🚫 Do not share it with anyone.
            If you did not request this, please ignore this email.
             — The TimeHub Team 🚀""",
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
        )

        messages.success(request, 'A reset OTP has been sent to your email.')
        return redirect('verify-otp-reset')

    return render(request, 'accounts/forgot.html', {'form': form})


@never_cache
def reset_password(request):
    if not request.session.get('otp_verified'):
        return redirect('forgot-password')

    form = ResetPasswordForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        password = form.cleaned_data['password']
        confirm = form.cleaned_data['confirm_password']

        if password != confirm:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'accounts/reset_password.html', {'form': form})

        email = request.session.get('reset_email')
        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            messages.error(request, 'Session expired. Please start again.')
            return redirect('forgot-password')

        user.set_password(password)
        user.save()

        # Clear reset session flags
        request.session.pop('otp_verified', None)
        request.session.pop('reset_email', None)

        messages.success(request, 'Password reset successful! You can now log in.')
        return redirect('login')

    return render(request, 'accounts/reset_password.html', {'form': form})


@never_cache
def referral_redirect(request, referral_code):
    """
    Referral Token URL approach:
    /accounts/ref/<code>/ stores the referral code in the session and redirects
    to signup so the form is pre-filled automatically — even if the user navigates
    away and comes back.
    """
    if request.user.is_authenticated:
        return redirect('landing_view')

    # Store in session so it survives page navigation before signup
    request.session['referral_code'] = referral_code

    # Redirect to signup with the ?ref= param as a visible pre-fill fallback
    return redirect(f"{reverse('signup')}?ref={referral_code}")