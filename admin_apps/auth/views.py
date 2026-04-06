from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, get_user_model, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.views.decorators.cache import never_cache
from django.db.models import Q, Sum, Count
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from .forms import AdminProfileForm, AdminLoginForm
from user_apps.accounts.models import CustomUser, EmailOTP
from user_apps.core.models import Product, Order, OrderItem, Collection
from django.db.models import Sum
from .models import Profile

User = get_user_model()

@never_cache
def admin_login(request):
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect("dashboard")
    if request.method == "POST":
        form = AdminLoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data.get("email")
            password = form.cleaned_data.get("password")
            
            user = authenticate(request, username=email, password=password)
            
            if user is not None and user.is_superuser:
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                return redirect("dashboard")
            elif user is not None:
                messages.error(request, "You are not authorized to access the admin dashboard.")
            else:
                messages.error(request, "Invalid email or password.")
        else:
            messages.error(request, "Invalid form submission.")
    else:
        form = AdminLoginForm()
    return render(request, "signin.html", {"form": form})


@never_cache
@login_required(login_url="admin_login")
def dashboard(request):
    if not request.user.is_superuser:
        return redirect("home")

    now = timezone.now()
    last_30_start = now - timedelta(days=30)
    prev_30_start = now - timedelta(days=60)

    def pct_change(current, previous):
        if previous == 0:
            return 100.0 if current > 0 else 0.0
        return round((current - previous) / previous * 100, 1)

    # --- Revenue ---
    total_revenue = Order.objects.filter(status='Delivered').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    last_30_revenue = Order.objects.filter(status='Delivered', created_at__gte=last_30_start).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    prev_30_revenue = Order.objects.filter(status='Delivered', created_at__gte=prev_30_start, created_at__lt=last_30_start).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    revenue_change = pct_change(last_30_revenue, prev_30_revenue)

    # --- Orders ---
    total_orders = Order.objects.count()
    last_30_orders = Order.objects.filter(created_at__gte=last_30_start).count()
    prev_30_orders = Order.objects.filter(created_at__gte=prev_30_start, created_at__lt=last_30_start).count()
    orders_change = pct_change(last_30_orders, prev_30_orders)

    # --- Customers ---
    total_customers = User.objects.filter(is_superuser=False, is_staff=False).count()
    last_30_customers = User.objects.filter(is_superuser=False, is_staff=False, created_at__gte=last_30_start).count()
    prev_30_customers = User.objects.filter(is_superuser=False, is_staff=False, created_at__gte=prev_30_start, created_at__lt=last_30_start).count()
    customers_change = pct_change(last_30_customers, prev_30_customers)

    # --- Products ---
    total_products = Product.objects.count()
    last_30_products = Product.objects.filter(created_at__gte=last_30_start).count()
    prev_30_products = Product.objects.filter(created_at__gte=prev_30_start, created_at__lt=last_30_start).count()
    products_change = pct_change(last_30_products, prev_30_products)

    recent_orders = Order.objects.select_related('user').prefetch_related('items__product').order_by("-created_at")[:10]

    # Top selling = products with most order items
    top_selling = Product.objects.annotate(
        order_count=Count('orderitem')
    ).order_by('-order_count')[:4]

    low_stock = Product.objects.filter(stock__lt=5).order_by("stock")[:5]

    context = {
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "total_customers": total_customers,
        "total_products": total_products,
        "revenue_change": revenue_change,
        "orders_change": orders_change,
        "customers_change": customers_change,
        "products_change": products_change,
        "recent_orders": recent_orders,
        "top_selling": top_selling,
        "low_stock": low_stock,
        "now": now,
        "user": request.user,
    }
    return render(request, "dashboard.html", context)


@login_required(login_url="admin_login")
@never_cache
def admin_logout(request):
    logout(request)
    messages.info(request, "Logged out successfully.")
    return redirect("admin_login")

@never_cache
def admin_forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email")
        
        try:
            user = User.objects.get(email=email)
            if not (user.is_superuser or user.is_staff):
                messages.error(request, "You are not authorized to reset passwords here.")
                return redirect("admin_forgot_password")
            
            # Generate OTP using the user-side model
            otp_obj = EmailOTP.objects.create(user=user)
            
         # Save the email into the browser session
            request.session['admin_reset_email'] = email
            
            # Dispatch the email
            send_mail(
                subject='TimeHub Admin — Password Reset OTP',
                message=f"""Hello {user.first_name if user.first_name else 'Admin'} ⏱

                        You requested a password reset for the TimeHub Admin Panel.

                        🔐 YOUR ONE-TIME PASSWORD:

                                        {otp_obj.otp}   
                                        
                        ⏳ Valid for 5 minutes only.
                        🚫 Do not share it with anyone.

                        If you did not request this, please ignore this email.

                        — The TimeHub Admin System 🚀""",
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[email],
            )
            
            messages.success(request, "An OTP has been sent to your admin email address.")
            return redirect("admin_verify_otp")
            
        except User.DoesNotExist:
            messages.error(request, "No admin account found with that email address.")
            return redirect("admin_forgot_password")
            
    return render(request, "forgot.html")




@never_cache
def admin_verify_otp(request):
    """OTP verification step for the Admin password-reset flow."""
    email = request.session.get('admin_reset_email')

    if not email:
        return redirect('admin_forgot_password')

    if request.method == 'POST':
        otp_input = request.POST.get('otp', '').strip()

        try:
            user = User.objects.get(email=email)
            otp_obj = user.otps.latest('created_at')

            if otp_obj.is_expired:
                messages.error(request, 'OTP expired. Please request a new one.')
                return redirect('admin_verify_otp')

            if otp_obj.otp != otp_input:
                messages.error(request, 'Invalid OTP. Please try again.')
                return redirect('admin_verify_otp')

            # Mark verified and clean up OTP record
            otp_obj.delete()
            request.session['admin_otp_verified'] = True

            return redirect('admin_reset_password')

        except User.DoesNotExist:
            messages.error(request, 'Admin account not found.')
            return redirect('admin_forgot_password')
        except EmailOTP.DoesNotExist:
            messages.error(request, 'No OTP found. Please request a new one.')
            return redirect('admin_forgot_password')

    return render(request, 'verify.html', {'email': email})


@never_cache
def admin_resend_otp(request):
    """Resend OTP to admin if requested."""
    email = request.session.get('admin_reset_email')

    if not email:
        return redirect('admin_forgot_password')

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        messages.error(request, "Admin account not found.")
        return redirect('admin_forgot_password')

    last_otp = user.otps.order_by('-created_at').first()

    # cooldown check (2 minutes = 120 seconds) 
    cooldown = getattr(settings, 'RESET_OTP_COOLDOWN_SEC', 120)
    if last_otp and (timezone.now() - last_otp.created_at).total_seconds() < cooldown:
        messages.error(request, "Please wait before requesting another OTP.")
        return redirect("admin_verify_otp")

    otp_obj = EmailOTP.objects.create(user=user)

    send_mail(
        subject='TimeHub Admin — Password Reset OTP',
        message=f"""Hello {user.first_name if user.first_name else 'Admin'} ⏱

You requested a new password reset OTP for the TimeHub Admin Panel.

🔐 YOUR ONE-TIME PASSWORD:

                  {otp_obj.otp}   
                
⏳ Valid for 5 minutes only.

— The TimeHub Admin System 🚀""",
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[email],
    )

    messages.success(request, "OTP resent successfully!")
    return redirect("admin_verify_otp")


@never_cache
def admin_reset_password(request):
    """Final password reset form after OTP is verified."""
    if not request.session.get('admin_otp_verified'):
        return redirect('admin_forgot_password')

    if request.method == 'POST':
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')

        if len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
            return render(request, 'reset.html')

        if password != confirm:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'reset.html')

        email = request.session.get('admin_reset_email')
        
        try:
            user = User.objects.get(email=email)
            user.set_password(password)
            user.save()

            # Clear session
            request.session.pop('admin_otp_verified', None)
            request.session.pop('admin_reset_email', None)

            messages.success(request, 'Password reset successfully! You can now log into the Admin Dashboard.')
            return redirect('admin_login')
            
        except User.DoesNotExist:
            messages.error(request, 'Session expired or user invalid. Please start again.')
            return redirect('admin_forgot_password')

    return render(request, 'reset.html')


@login_required(login_url="admin_login")
@never_cache
def admin_profile(request):
    if not request.user.is_superuser:
        return redirect("dashboard")
    
    user = request.user
    profile_form = AdminProfileForm(instance=user)
    password_form = PasswordChangeForm(user=user)
    active_tab = "edit-profile"

    if request.method == "POST":
        if 'update_profile' in request.POST:
            active_tab = "edit-profile"
            profile_form = AdminProfileForm(request.POST, request.FILES, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile updated successfully.")
                return redirect("admin_profile")
        elif 'change_password' in request.POST:
            active_tab = "change-password"
            password_form = PasswordChangeForm(user=user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                messages.success(request, "Password changed successfully!")
                return redirect("admin_profile")
            else:
                messages.error(request, "Please correct the errors below.")

    context = {
        "profile_form": profile_form,
        "password_form": password_form,
        "user": user,
        "active_tab": active_tab,
    }
    return render(request, "admin_profile.html", context)