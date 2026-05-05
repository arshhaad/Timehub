from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Seller
from user_apps.core.models import Product, Collection, Wallet, WalletTransaction, ProductImage, ProductVariant, VariantImage, Color
from user_apps.accounts.forms import SignupForm, LoginForm
from user_apps.accounts.models import CustomUser, EmailOTP
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.cache import never_cache
from django.db import transaction
from datetime import timedelta
from django.utils import timezone
from django.http import JsonResponse

@never_cache
def seller_signup(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'seller_profile'):
            return redirect('seller_dashboard')
        # If logged in as non-seller, show the option to become one
        return render(request, 'acc_create.html', {'is_authenticated_non_seller': True})
    
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            password1 = form.cleaned_data.get('password1')
            password2 = form.cleaned_data.get('password2')
            
            if password1 != password2:
                messages.error(request, "Passwords do not match.")
                return render(request, 'acc_create.html', {'form': form})

            email = form.cleaned_data.get('email').lower()
            # Store signup data in session
            request.session['pending_seller_data'] = {
                'email': email,
                'first_name': form.cleaned_data.get('first_name'),
                'last_name': form.cleaned_data.get('last_name'),
                'phone_number': form.cleaned_data.get('phone_number'),
                'password': form.cleaned_data.get('password1'),
            }
            
            # Create OTP
            otp_obj = EmailOTP.objects.create(email=email)
            
            # Send Email
            send_mail(
                subject='Verify Your TimeHub Seller Account ⏱',
                message=f'Welcome to TimeHub! Your verification code is: {otp_obj.otp}. Valid for 1 minute.',
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[email],
            )
            
            request.session['verify_email'] = email
            messages.success(request, 'Verification code sent to your email.')
            return redirect('seller_verify_otp')
    else:
        form = SignupForm()
    
    return render(request, 'acc_create.html', {'form': form})

@never_cache
def seller_verify_otp(request):
    email = request.session.get('verify_email')
    pending_data = request.session.get('pending_seller_data')
    
    if not email or not pending_data:
        return redirect('seller_signup')
    
    if request.method == 'POST':
        otp_input = request.POST.get('otp')
        otp_obj = EmailOTP.objects.filter(email=email).order_by('-created_at').first()
        
        if otp_obj and not otp_obj.is_expired and otp_obj.otp == otp_input:
            with transaction.atomic():
                # Create User
                user = CustomUser.objects.create_user(
                    email=pending_data['email'],
                    password=pending_data['password'],
                    first_name=pending_data['first_name'],
                    last_name=pending_data['last_name'],
                    phone_number=pending_data['phone_number']
                )
                
                # Create Seller Profile
                Seller.objects.create(user=user, store_name=f"{user.first_name}'s Store")
                
                # Create Wallet for user
                Wallet.objects.get_or_create(user=user)
                
                # Cleanup
                otp_obj.delete()
                del request.session['pending_seller_data']
                del request.session['verify_email']
                
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request, 'Welcome to TimeHub Seller Panel!')
                return redirect('seller_dashboard')
        else:
            messages.error(request, 'Invalid or expired OTP.')
            
    # Get latest OTP for timer
    seconds_left = 0
    otp_obj = EmailOTP.objects.filter(email=email).order_by('-created_at').first()
    if otp_obj:
        expiry_time = otp_obj.created_at + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
        seconds_left = max(0, int((expiry_time - timezone.now()).total_seconds()))

    return render(request, 'seller_verify_otp.html', {
        'email': email,
        'seconds_left': seconds_left
    })

@never_cache
def seller_login(request):
    if request.user.is_authenticated:
        return redirect('seller_dashboard')

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            user = authenticate(request, username=email, password=password)
            
            if user:
                if user.is_active:
                    if hasattr(user, 'seller_profile'):
                        login(request, user)
                        messages.success(request, f'Welcome back, {user.get_full_name() or user.email}')
                        return redirect('seller_dashboard')
                    else:
                        messages.error(request, 'Access Denied: This account is not registered as a seller.')
                else:
                    messages.error(request, 'Your account has been deactivated.')
            else:
                messages.error(request, 'Invalid email or password.')
    else:
        form = LoginForm()
    
    return render(request, 'login_acc.html', {'form': form})

def seller_logout(request):
    logout(request)
    messages.success(request, 'Successfully logged out.')
    return redirect('seller_login')

@login_required
def become_seller(request):
    if hasattr(request.user, 'seller_profile'):
        return redirect('seller_dashboard')
    
    if request.method == 'POST':
        with transaction.atomic():
            Seller.objects.create(
                user=request.user, 
                store_name=f"{request.user.first_name}'s Store"
            )
            # Ensure wallet exists
            Wallet.objects.get_or_create(user=request.user)
            
        messages.success(request, "Congratulations! You are now a registered seller.")
        return redirect('seller_dashboard')
    
    return redirect('seller_signup')

@login_required
def seller_dashboard(request):
    try:
        seller = request.user.seller_profile
    except Seller.DoesNotExist:
        messages.error(request, "You need a seller account to access the dashboard.")
        return redirect('seller_signup')
        
    products_count = Product.objects.filter(seller=seller, is_deleted=False).count()
    return render(request, 'seller_dashboard.html', {
        'active_menu': 'dashboard',
        'products_count': products_count,
    })

@login_required
def seller_product_sell_list(request):
    seller = get_object_or_404(Seller, user=request.user)
    query = request.GET.get('q')
    
    if query:
        products = Product.objects.filter(
            seller=seller, 
            name__icontains=query, 
            is_deleted=False
        ).order_by('-created_at')
    else:
        products = Product.objects.filter(seller=seller, is_deleted=False).order_by('-created_at')
        
    return render(request, 'product_sell_list.html', {
        'products': products,
        'active_menu': 'my_products'
    })

@login_required
def seller_product_add(request):
    seller = get_object_or_404(Seller, user=request.user)
    if request.method == 'POST':
        try:
            name = request.POST.get('name')
            brand = request.POST.get('brand', 'TimeHub')
            collection_id = request.POST.get('collection_id')
            price = request.POST.get('price')
            discount_price = request.POST.get('discount_price')
            description = request.POST.get('description')
            gender = request.POST.get('gender')
            occasion = request.POST.get('occasion')
            function = request.POST.get('function')
            features = request.POST.get('features')
            is_active = request.POST.get('is_active') == 'on'
            
            with transaction.atomic():
                # 1. Create Product
                product = Product.objects.create(
                    seller=seller,
                    name=name,
                    brand=brand,
                    collection_id=collection_id,
                    price=price,
                    discount_price=discount_price if discount_price else None,
                    description=description,
                    gender=gender,
                    occasion=occasion,
                    function=function,
                    features=features,
                    is_active=is_active
                )
                
                # 2. Handle Main Product Images
                for i in range(1, 4):
                    img_file = request.FILES.get(f'product_image_{i}')
                    if img_file:
                        img_obj = ProductImage.objects.create(
                            product=product,
                            image=img_file,
                            is_main=(i == 1)
                        )
                        if i == 1:
                            product.image = img_obj.image
                            product.save()
                
                # 3. Handle Variants
                skus = request.POST.getlist('variant_sku[]')
                materials = request.POST.getlist('variant_strap_material[]')
                stocks = request.POST.getlist('variant_stock[]')
                strap_colors = request.POST.getlist('variant_strap_color[]')
                v_descriptions = request.POST.getlist('variant_description[]')
                v_indices = request.POST.getlist('variant_image_idx[]')
                
                total_stock = 0
                for i in range(len(skus)):
                    variant = ProductVariant.objects.create(
                        product=product,
                        sku=skus[i],
                        strap_material=materials[i],
                        stock=int(stocks[i]),
                        strap_color=strap_colors[i],
                        description=v_descriptions[i]
                    )
                    total_stock += int(stocks[i])
                    
                    # Handle Variant Images
                    idx = v_indices[i]
                    for sub in range(1, 4):
                        v_img = request.FILES.get(f'variant_image_input_{idx}_{sub}')
                        if not v_img:
                            v_img = request.FILES.get(f'variant_image_{idx}_{sub}')
                            
                        if v_img:
                            VariantImage.objects.create(
                                variant=variant,
                                image=v_img
                            )
                
                # Update total stock
                product.stock = total_stock
                product.save()
                
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'message': 'Product added successfully!'})
            messages.success(request, 'Product added successfully!')
            return redirect('seller_product_sell_list')
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, f'Error: {str(e)}')
            
    all_categories = Collection.objects.filter(is_deleted=False)
    all_colors = Color.objects.all()
    
    return render(request, 'product_add.html', {
        'active_menu': 'add_product',
        'all_categories': all_categories,
        'all_colors': all_colors
    })

@login_required
def seller_product_status(request):
    seller = get_object_or_404(Seller, user=request.user)
    product_id = request.GET.get('id')
    
    all_products = Product.objects.filter(seller=seller, is_deleted=False).order_by('-created_at')
    
    if product_id:
        product = get_object_or_404(Product, id=product_id, seller=seller)
    else:
        product = all_products.first()
        
    is_sold = False
    if product:
        # Check if any quantity has been sold (across variants)
        is_sold = product.orderitem_set.filter(order__is_paid=True).exists()
    
    return render(request, 'product_status.html', {
        'product': product,
        'all_products': all_products,
        'is_sold': is_sold,
        'active_menu': 'product_status'
    })

@login_required
def seller_wallet(request):
    from .models import SellerEarnings
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    transactions = WalletTransaction.objects.filter(wallet=wallet).order_by('-timestamp')
    
    seller = getattr(request.user, 'seller_profile', None)
    pending_earnings = []
    if seller:
        pending_earnings = SellerEarnings.objects.filter(seller=seller, status='Pending').order_by('-created_at')
        
    return render(request, 'seller_wallat.html', {
        'wallet': wallet,
        'transactions': transactions,
        'pending_earnings': pending_earnings,
        'active_menu': 'wallet'
    })
@login_required
def seller_settings(request):
    seller = get_object_or_404(Seller, user=request.user)
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        store_name = request.POST.get('store_name', '').strip()
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        
        # Validation
        if not first_name:
            messages.error(request, "First name is required.")
            return redirect('seller_settings')
            
        if not store_name:
            messages.error(request, "Store name is required.")
            return redirect('seller_settings')
            
        if password:
            if len(password) < 8:
                messages.error(request, "Password must be at least 8 characters long.")
                return redirect('seller_settings')
            if password != confirm_password:
                messages.error(request, "Passwords do not match.")
                return redirect('seller_settings')
        
        # Save Data
        request.user.first_name = first_name
        request.user.last_name = last_name
        request.user.save()
        
        seller.store_name = store_name
        seller.save()
        
        if password:
            request.user.set_password(password)
            request.user.save()
            login(request, request.user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, "Settings and password updated successfully.")
        else:
            messages.success(request, "Settings updated successfully.")
            
        return redirect('seller_settings')
        
    return render(request, 'seller_settings.html', {
        'active_menu': 'settings'
    })

@login_required
def seller_product_edit(request, product_id):
    seller = get_object_or_404(Seller, user=request.user)
    product = get_object_or_404(Product, id=product_id, seller=seller)
    
    if request.method == 'POST':
        try:
            product.name = request.POST.get('name')
            product.brand = request.POST.get('brand', 'TimeHub')
            product.collection_id = request.POST.get('collection_id')
            product.price = request.POST.get('price')
            product.discount_price = request.POST.get('discount_price') or None
            product.description = request.POST.get('description')
            product.gender = request.POST.get('gender')
            product.occasion = request.POST.get('occasion')
            product.function = request.POST.get('function')
            product.features = request.POST.get('features')
            product.is_active = request.POST.get('is_active') == 'on'
            
            with transaction.atomic():
                product.save()
                
                # Update images — respect delete flags from X button clicks
                existing_imgs = list(product.images.all())
                for i in range(1, 4):
                    img_file  = request.FILES.get(f'product_image_{i}')
                    delete_flag = request.POST.get(f'delete_image_{i}') == '1'

                    if img_file:
                        if len(existing_imgs) >= i:
                            target_img = existing_imgs[i - 1]
                            target_img.image = img_file
                            target_img.save()
                            if i == 1:
                                product.image = target_img.image
                                product.save()
                        else:
                            img_obj = ProductImage.objects.create(
                                product=product,
                                image=img_file,
                                is_main=(i == 1)
                            )
                            if i == 1:
                                product.image = img_obj.image
                                product.save()
                    elif delete_flag:
                        # User clicked X with no replacement — delete the existing image
                        if len(existing_imgs) >= i:
                            existing_imgs[i - 1].delete()
                            if i == 1:
                                product.image = None
                                product.save()

                
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'message': 'Product updated successfully!'})
            messages.success(request, 'Product updated successfully!')
            return redirect('seller_product_sell_list')
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, f'Error: {str(e)}')

    all_categories = Collection.objects.filter(is_deleted=False)
    all_colors = Color.objects.all()
    
    return render(request, 'product_add.html', {
        'product': product,
        'is_edit': True,
        'active_menu': 'my_products',
        'all_categories': all_categories,
        'all_colors': all_colors
    })
