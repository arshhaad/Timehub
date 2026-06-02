"""Seller Dashboard & Product Management."""

import json
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.db import transaction
from django.http import JsonResponse
from django.conf import settings

from .models import Seller
from user_apps.core.models import (
    Product, Collection, Wallet, WalletTransaction, 
    ProductImage, ProductVariant, VariantImage, Color
)
from user_apps.accounts.forms import SignupForm, LoginForm
from user_apps.accounts.models import CustomUser, EmailOTP
from user_apps.accounts.utils import send_otp_email
from functools import wraps

def seller_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('seller_login')
        if not hasattr(request.user, 'seller_profile'):
            return redirect('seller_signup')
        if request.user.seller_profile.is_blocked:
            logout(request)
            messages.error(request, "Your seller account has been blocked by the administrator.")
            return redirect('seller_login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view




@never_cache
def seller_signup(request):
    """Render seller registration page."""
    if request.user.is_authenticated:
        if hasattr(request.user, 'seller_profile'):
            return redirect('seller_dashboard')
        return render(request, 'acc_create.html', {'is_authenticated_non_seller': True})
    
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            p1 = form.cleaned_data.get('password1')
            p2 = form.cleaned_data.get('password2')
            
            if p1 != p2:
                messages.error(request, "Passwords do not match.")
                return render(request, 'acc_create.html', {'form': form})

            email = form.cleaned_data.get('email').lower()
            
            # Store details in session for the second step (OTP verification)
            request.session['pending_seller_data'] = {
                'email': email,
                'first_name': form.cleaned_data.get('first_name'),
                'last_name': form.cleaned_data.get('last_name'),
                'phone_number': form.cleaned_data.get('phone_number'),
                'password': p1,
            }
            
            # Issue OTP
            otp_obj = EmailOTP.objects.create(email=email)
            send_otp_email(email, otp_obj.otp, context="verification")
            
            request.session['verify_email'] = email
            messages.success(request, 'Verification code sent to your email.')
            return redirect('seller_verify_otp')
    else:
        form = SignupForm()
    
    return render(request, 'acc_create.html', {'form': form})


@never_cache
def seller_verify_otp(request):
    """Verify OTP and create seller profile."""
    email = request.session.get('verify_email')
    data = request.session.get('pending_seller_data')
    
    if not email or not data:
        return redirect('seller_signup')
    
    if request.method == 'POST':
        otp_input = request.POST.get('otp')
        
        # 1. Locate the valid OTP object
        otp_obj = EmailOTP.objects.filter(email=email).order_by('-created_at').first()
        if not otp_obj:
            user_obj = CustomUser.objects.filter(email=email).first()
            if user_obj:
                otp_obj = user_obj.otps.order_by('-created_at').first()

        # 2. Validation Checks
        if not otp_obj:
            messages.error(request, "Verification session not found. Please sign up again.")
            return redirect("seller_verify_otp")

        if otp_obj.is_expired:
            messages.error(request, "The verification code has expired. Please request a fresh one.")
            return redirect("seller_verify_otp")

        if otp_obj.otp != otp_input:
            messages.error(request, "Invalid verification code. Please check your email and try again.")
            return redirect("seller_verify_otp")
            
        # 3. SUCCESS — Commit to Database
        with transaction.atomic():
            # 1. Create the User Account
            user = CustomUser.objects.create_user(
                email=data['email'],
                password=data['password'],
                first_name=data['first_name'],
                last_name=data['last_name'],
                phone_number=data['phone_number']
            )
            
            # 2. Create Seller Profile
            Seller.objects.create(user=user, store_name=f"{user.first_name}'s Store")
            
            # 3. Create Wallet
            Wallet.objects.get_or_create(user=user)
            
            # Cleanup
            otp_obj.delete()
            del request.session['pending_seller_data']
            del request.session['verify_email']
            
            # Log the user in
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, 'Welcome to the TimeHub Seller Panel!')
            return redirect('seller_dashboard')
            
    # Calculate seconds remaining for UI timer
    seconds_left = 0
    latest_otp = EmailOTP.objects.filter(email=email).order_by('-created_at').first()
    if not latest_otp:
        user_obj = CustomUser.objects.filter(email=email).first()
        if user_obj:
            latest_otp = user_obj.otps.order_by('-created_at').first()
            
    if latest_otp:
        expiry = latest_otp.created_at + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
        seconds_left = max(0, int((expiry - timezone.now()).total_seconds()))

    return render(request, 'seller_verify_otp.html', {
        'email': email, 'seconds_left': seconds_left
    })


@never_cache
def seller_resend_otp(request):
    """Resend a new OTP to the pending seller email."""
    email = request.session.get('verify_email')
    if not email:
        messages.error(request, "Session expired, please register again.")
        return redirect('seller_signup')

    # Cooldown Security Check
    last_otp = EmailOTP.objects.filter(email=email).order_by('-created_at').first()
    if not last_otp:
        u = CustomUser.objects.filter(email=email).first()
        if u:
            last_otp = u.otps.order_by('-created_at').first()

    if last_otp and (timezone.now() - last_otp.created_at).total_seconds() < settings.RESET_OTP_COOLDWON_SEC:
        messages.error(request, "Security wait: Please wait a moment before requesting another code.")
        return redirect("seller_verify_otp")
        
    # Generate new OTP and send
    otp_obj = EmailOTP.objects.create(email=email)
    send_otp_email(email, otp_obj.otp, context="verification")
    
    messages.success(request, f"A new security code has been dispatched to {email}.")
    return redirect('seller_verify_otp')


@never_cache
def seller_forgot_password(request):
    """Send a password-reset OTP to the seller's email."""
    if request.user.is_authenticated:
        return redirect('seller_dashboard')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        try:
            user = CustomUser.objects.get(email=email)
            if not hasattr(user, 'seller_profile'):
                messages.error(request, 'No seller account found with that email.')
                return render(request, 'seller_forgot_password.html')
        except CustomUser.DoesNotExist:
            messages.error(request, 'No account found with that email.')
            return render(request, 'seller_forgot_password.html')

        # Generate OTP and store reset session
        otp_obj = EmailOTP.objects.create(user=user)
        request.session['seller_reset_email'] = email
        send_otp_email(email, otp_obj.otp, context="password_reset")
        messages.success(request, 'A reset code has been sent to your email.')
        return redirect('seller_verify_otp_reset')

    return render(request, 'seller_forgot_password.html')


@never_cache
def seller_verify_otp_reset(request):
    """Verify OTP for seller password reset."""
    email = request.session.get('seller_reset_email')
    if not email:
        return redirect('seller_forgot_password')

    if request.method == 'POST':
        otp_input = request.POST.get('otp', '').strip()

        try:
            user = CustomUser.objects.get(email=email)
            otp_obj = user.otps.latest('created_at')
        except (CustomUser.DoesNotExist, EmailOTP.DoesNotExist):
            messages.error(request, 'Verification session not found. Please restart the reset process.')
            return redirect('seller_forgot_password')

        if otp_obj.is_expired:
            messages.error(request, 'The code has expired. Please request a new one.')
            return redirect('seller_verify_otp_reset')

        if otp_obj.otp != otp_input:
            messages.error(request, 'Incorrect verification code. Please try again.')
            return redirect('seller_verify_otp_reset')

        # Mark session as verified
        otp_obj.delete()
        request.session['seller_otp_verified'] = True
        return redirect('seller_reset_password')

    # Timer logic
    seconds_left = 0
    try:
        user = CustomUser.objects.get(email=email)
        latest = user.otps.latest('created_at')
        expiry = latest.created_at + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
        seconds_left = max(0, int((expiry - timezone.now()).total_seconds()))
    except Exception:
        pass

    return render(request, 'seller_verify_otp_reset.html', {
        'email': email, 'seconds_left': seconds_left
    })


@never_cache
def seller_reset_password(request):
    """Reset password for the seller after OTP verification."""
    if not request.session.get('seller_otp_verified'):
        return redirect('seller_forgot_password')

    if request.method == 'POST':
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')

        if len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
            return render(request, 'seller_reset_password.html')

        if password != confirm:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'seller_reset_password.html')

        email = request.session.get('seller_reset_email')
        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            messages.error(request, 'Session expired. Please start again.')
            return redirect('seller_forgot_password')

        user.set_password(password)
        user.save()

        # Clear all reset session flags
        request.session.pop('seller_otp_verified', None)
        request.session.pop('seller_reset_email', None)

        messages.success(request, 'Password reset successful! You can now sign in.')
        return redirect('seller_login')

    return render(request, 'seller_reset_password.html')



@never_cache
def seller_login(request):
    """Standard login for sellers."""
    if request.user.is_authenticated:
        if hasattr(request.user, 'seller_profile'):
            if request.user.seller_profile.is_blocked:
                logout(request)
                messages.error(request, "Your seller account has been blocked by the administrator.")
                return redirect('seller_login')
            return redirect('seller_dashboard')
        else:
            return redirect('seller_signup')

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            user = authenticate(request, username=email, password=password)
            
            if user:
                if user.is_active and hasattr(user, 'seller_profile'):
                    if user.seller_profile.is_blocked:
                        messages.error(request, 'Your seller account has been blocked by the administrator.')
                    else:
                        login(request, user)
                        messages.success(request, f'Welcome back, {user.first_name or user.email}')
                        return redirect('seller_dashboard')
                elif not user.is_active:
                    messages.error(request, 'Your account is deactivated.')
                else:
                    messages.error(request, 'This account does not have seller access.')
            else:
                messages.error(request, 'Invalid credentials.')
    else:
        form = LoginForm()
    
    return render(request, 'login_acc.html', {'form': form})


def seller_logout(request):
    """Log out the seller."""
    logout(request)
    messages.success(request, 'Logged out successfully.')
    return redirect('seller_login')


@login_required
def become_seller(request):
    """Upgrade existing user to seller profile."""
    if hasattr(request.user, 'seller_profile'):
        return redirect('seller_dashboard')
    
    if request.method == 'POST':
        with transaction.atomic():
            Seller.objects.create(
                user=request.user, 
                store_name=f"{request.user.first_name}'s Store"
            )
            Wallet.objects.get_or_create(user=request.user)
            
        messages.success(request, "You are now registered as a seller!")
        return redirect('seller_dashboard')
    
    return redirect('seller_signup')




@seller_required
def seller_dashboard(request):
    """Display seller dashboard with quick stats."""
    seller = request.user.seller_profile
    count = Product.objects.filter(seller=seller, is_deleted=False).count()
    return render(request, 'seller_dashboard.html', {
        'active_menu': 'dashboard',
        'products_count': count,
    })


@seller_required
def seller_product_sell_list(request):
    """Lists all products owned by the seller with search support."""
    seller = request.user.seller_profile
    query = request.GET.get('q', '').strip()
    
    products = Product.objects.filter(seller=seller, is_deleted=False).order_by('-created_at')
    if query:
        products = products.filter(name__icontains=query)
        
    return render(request, 'product_sell_list.html', {
        'products': products,
        'active_menu': 'my_products'
    })




def ensure_default_colors():
    """Seed default colors if none exist in the database."""
    if not Color.objects.exists():
        default_colors = [
            ('Black', '#000000'),
            ('Brown', '#8B4513'),
            ('Silver', '#C0C0C0'),
            ('Gold', '#FFD700'),
            ('Blue', '#0000FF'),
            ('Red', '#FF0000'),
            ('Green', '#008000'),
            ('White', '#FFFFFF'),
            ('Grey', '#808080'),
            ('Rose Gold', '#B76E79'),
            ('Orange', '#FFA500'),
            ('Yellow', '#FFFF00'),
        ]
        for name, hex_code in default_colors:
            Color.objects.get_or_create(name=name, defaults={'hex_code': hex_code})


@seller_required
def seller_product_add(request):
    """Add a new product with images and variants."""
    ensure_default_colors()
    seller = request.user.seller_profile
    
    if request.method == 'POST':
        try:
            # 1. Gather Basic Product Info
            p_data = {
                'seller': seller,
                'name': request.POST.get('name'),
                'brand': request.POST.get('brand', 'TimeHub'),
                'collection_id': request.POST.get('collection_id'),
                'price': request.POST.get('price'),
                'discount_price': request.POST.get('discount_price') or None,
                'description': request.POST.get('description'),
                'gender': request.POST.get('gender'),
                'occasion': request.POST.get('occasion'),
                'function': request.POST.get('function'),
                'features': request.POST.get('features'),
                'is_active': request.POST.get('is_active') == 'on'
            }
            
            with transaction.atomic():
                # 2. Create Base Product
                product = Product.objects.create(**p_data)
                
                # 3. Handle Product Images (up to 3)
                for i in range(1, 4):
                    img = request.FILES.get(f'product_image_{i}')
                    if img:
                        obj = ProductImage.objects.create(product=product, image=img, is_main=(i == 1))
                        if i == 1:
                            product.image = obj.image
                            product.save()
                
                # 4. Handle Variants
                skus = request.POST.getlist('variant_sku[]')
                mats = request.POST.getlist('variant_strap_material[]')
                stks = request.POST.getlist('variant_stock[]')
                clrs = request.POST.getlist('variant_strap_color[]')
                desc = request.POST.getlist('variant_description[]')
                idxs = request.POST.getlist('variant_image_idx[]')
                
                total_stock = 0
                for i in range(len(skus)):
                    qty = int(stks[i]) if (i < len(stks) and stks[i]) else 0
                    total_stock += qty
                    
                    sku_val = skus[i] if i < len(skus) else ''
                    mat_val = mats[i] if i < len(mats) else ''
                    clr_val = clrs[i] if i < len(clrs) else ''
                    desc_val = desc[i] if i < len(desc) else ''
                    
                    variant = ProductVariant.objects.create(
                        product=product, sku=sku_val, strap_material=mat_val,
                        stock=qty, strap_color=clr_val, description=desc_val
                    )
                    
                    # Handle Images for this specific variant
                    v_idx = idxs[i] if i < len(idxs) else None
                    if v_idx:
                        for sub in range(1, 4):
                            v_img = request.FILES.get(f'variant_image_input_{v_idx}_{sub}') or \
                                    request.FILES.get(f'variant_image_{v_idx}_{sub}')
                            if v_img:
                                vi = VariantImage.objects.create(variant=variant, image=v_img, is_main=(sub == 1))
                                if sub == 1:
                                    variant.image = vi.image
                                    variant.save()
                
                # Sync total product stock and color filters
                active_variants = product.variants.filter(is_active=True)
                product.stock = total_stock
                
                # Set dynamic product colors from active variants
                product.colors.set(Color.objects.filter(name__in=active_variants.values_list('strap_color', flat=True).distinct()))
                
                # Ensure product has a main/fallback image
                if not product.image:
                    main_img = ProductImage.objects.filter(product=product).first()
                    if main_img:
                        product.image = main_img.image
                    else:
                        v_with_img = active_variants.exclude(image="").exclude(image=None).first()
                        if v_with_img:
                            product.image = v_with_img.image
                
                product.save()
                
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'message': 'Product launched!'})
            messages.success(request, 'Product added successfully!')
            return redirect('seller_product_sell_list')

        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, f'Error: {str(e)}')
            
    return render(request, 'product_add.html', {
        'active_menu': 'add_product',
        'all_categories': Collection.objects.filter(is_deleted=False),
        'all_colors': Color.objects.all()
    })


@seller_required
def seller_product_edit(request, product_id):
    """Update existing product details and images."""
    ensure_default_colors()
    seller = request.user.seller_profile
    product = get_object_or_404(Product, id=product_id, seller=seller)
    
    if request.method == 'POST':
        try:
            product.name = request.POST.get('name')
            product.brand = request.POST.get('brand', 'TimeHub')
            product.collection_id = request.POST.get('collection_id')
            product.price = request.POST.get('price')
            if 'discount_price' in request.POST:
                product.discount_price = request.POST.get('discount_price') or None
            product.description = request.POST.get('description')
            product.gender = request.POST.get('gender')
            product.occasion = request.POST.get('occasion')
            product.function = request.POST.get('function')
            product.features = request.POST.get('features')
            product.is_active = request.POST.get('is_active') == 'on'
            
            with transaction.atomic():
                product.save()
                
                # Update Product Images
                existing = list(product.images.all())
                for i in range(1, 4):
                    file = request.FILES.get(f'product_image_{i}')
                    is_deleted = request.POST.get(f'delete_image_{i}') == '1'

                    if file:
                        if len(existing) >= i:
                            target = existing[i-1]
                            target.image = file
                            target.save()
                        else:
                            ProductImage.objects.create(product=product, image=file, is_main=(i==1))
                        # Sync main thumbnail if updating slot 1
                        if i == 1:
                            product.image = file
                            product.save()
                    elif is_deleted and len(existing) >= i:
                        existing[i-1].delete()
                        if i == 1:
                            product.image = None
                            product.save()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success'})
            messages.success(request, 'Changes saved.')
            return redirect('seller_product_sell_list')
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, str(e))

    return render(request, 'product_add.html', {
        'product': product, 'is_edit': True, 'active_menu': 'my_products',
        'all_categories': Collection.objects.filter(is_deleted=False),
        'all_colors': Color.objects.all()
    })




@seller_required
def seller_wallet(request):
    """View seller earnings and transaction history."""
    from .models import SellerEarnings
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    txs = WalletTransaction.objects.filter(wallet=wallet).order_by('-timestamp')
    
    seller = request.user.seller_profile
    pending = SellerEarnings.objects.filter(seller=seller, status='Pending').order_by('-created_at')
        
    return render(request, 'seller_wallet.html', {
        'wallet': wallet, 'transactions': txs, 'pending_earnings': pending,
        'active_menu': 'wallet'
    })




@seller_required
def seller_settings(request):
    """Update store name and security settings."""
    seller = request.user.seller_profile
    if request.method == 'POST':
        fname = request.POST.get('first_name', '').strip()
        lname = request.POST.get('last_name', '').strip()
        store = request.POST.get('store_name', '').strip()
        pwd = request.POST.get('password')
        cpwd = request.POST.get('confirm_password')
        
        if not fname or not store:
            messages.error(request, "Name and Store Name are mandatory.")
            return redirect('seller_settings')
            
        if pwd:
            if len(pwd) < 8:
                messages.error(request, "Password too short.")
                return redirect('seller_settings')
            if pwd != cpwd:
                messages.error(request, "Passwords mismatch.")
                return redirect('seller_settings')
        
        # Apply Changes
        request.user.first_name, request.user.last_name = fname, lname
        request.user.save()
        seller.store_name = store
        seller.save()
        
        if pwd:
            request.user.set_password(pwd)
            request.user.save()
            # Refresh session to prevent auto-logout
            login(request, request.user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, "Credentials and settings updated.")
        else:
            messages.success(request, "Settings saved.")
        return redirect('seller_settings')
        
    return render(request, 'seller_settings.html', {'active_menu': 'settings'})


@seller_required
def seller_product_status(request):
    """View sales status and performance for a product."""
    seller = request.user.seller_profile
    p_id = request.GET.get('id')
    
    all_p = Product.objects.filter(seller=seller, is_deleted=False).order_by('-created_at')
    product = get_object_or_404(Product, id=p_id, seller=seller) if p_id else all_p.first()
    
    # Check if this product has generated any revenue
    is_sold = product.orderitem_set.filter(order__is_paid=True).exists() if product else False
    
    return render(request, 'product_status.html', {
        'product': product, 'all_products': all_p, 'is_sold': is_sold,
        'active_menu': 'product_status'
    })
