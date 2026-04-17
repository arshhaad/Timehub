from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .models import Address
from .forms import AddressForm, UserEditForm
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from django.http import JsonResponse
import json
from decimal import Decimal
from user_apps.core.models import Cart, CartItem, Product, WishlistItem, Wishlist, Order
from user_apps.accounts.models import EmailOTP, CustomUser
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone


@login_required
@never_cache
def dashboard(request):
    user = request.user
    
    # Fetch actual stats
    total_orders = user.orders.count()
    wishlist, _ = Wishlist.objects.get_or_create(user=user)
    saved_items = wishlist.items.count()
    
    stats = {
        'total_orders': total_orders,
        'saved_items': saved_items,
        'reward_points': 0, # Model not create 
    }
    
    recent_orders = user.orders.order_by('-created_at')[:5]
    
    context = {
        'user': user,
        'stats': stats,
        'recent_orders': recent_orders,
        'referral_code': 'TIMEHUB-JS2024', # test value
    }
    
    return render(request, 'user_dashboard.html', context)


@login_required
@never_cache
def address_list(request):
    addresses = Address.objects.filter(user=request.user)
    return render(request, 'address.html', {'addresses': addresses})


@login_required
@never_cache
def add_address(request):
    if request.method == 'POST':
        form = AddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user

            # default address
            if address.is_default:
                Address.objects.filter(user=request.user).update(is_default=False)

            address.save()
            return redirect('address_list')
    else:
        form = AddressForm()

    return render(request, 'address_form.html', {'form': form})



@login_required
@never_cache
def edit_address(request, id):
    address = get_object_or_404(Address, id=id, user=request.user)

    if request.method == 'POST':
        form = AddressForm(request.POST, instance=address)
        if form.is_valid():
            address = form.save(commit=False)

            if address.is_default:
                Address.objects.filter(user=request.user).exclude(id=id).update(is_default=False)

            address.save()
            return redirect('address_list')
    else:
        form = AddressForm(instance=address)

    return render(request, 'address_form.html', {'form': form})

@login_required
@never_cache
def delete_address(request, id):
    address = get_object_or_404(Address, id=id, user=request.user)
    address.delete()
    return redirect('address_list')

@login_required
@never_cache
def toggle_default_address(request, id):
    address = get_object_or_404(Address, id=id, user=request.user)
    
    if not address.is_default:
        # Unset others and set this one
        Address.objects.filter(user=request.user, is_default=True).update(is_default=False)
        address.is_default = True
        address.save()
    else:
        # off
        address.is_default = False
        address.save()
        
    return redirect('address_list')


@login_required
@never_cache
def edit_profile(request):
    if request.method == 'POST':
        form = UserEditForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            new_email = form.cleaned_data.get('email')
            
            # Check if email is being changed
            if new_email and new_email != request.user.email:
                if CustomUser.objects.filter(email=new_email).exclude(id=request.user.id).exists():
                    messages.error(request, 'This email is already in use by another account.')
                    return render(request, 'edit_profile.html', {'form': form})

                # Save everything except email first
                user = form.save(commit=False)
                # Keep original email for now
                user.email = request.user.email
                user.save()
                # Save M2M (like colors if any, though User doesn't have them in Meta)
                form.save_m2m()

                # Store pending email in session
                request.session['pending_email_change'] = new_email
                
                # Send OTP to NEW email
                otp_obj = EmailOTP.objects.create(user=request.user)
                
                send_mail(
                    "Verify Your New Email",
                    f"Your OTP for changing email to {new_email} is: {otp_obj.otp}",
                    settings.EMAIL_HOST_USER,
                    [new_email],
                )
                
                messages.info(request, f"Profile updated. Now please verify the OTP sent to {new_email} to complete your email change.")
                return redirect('verify_email_change')
            
            form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('user_dashboard')
    else:
        form = UserEditForm(instance=request.user)

    return render(request, 'edit_profile.html', {'form': form})


@login_required
@never_cache
def verify_email_change(request):
    new_email = request.session.get('pending_email_change')
    if not new_email:
        return redirect('edit_profile')
        
    if request.method == 'POST':
        otp_input = request.POST.get('otp', '').strip()
        try:
            otp_obj = request.user.otps.latest('created_at')
            
            if otp_obj.is_expired:
                messages.error(request, 'OTP expired. Please try changing your email again.')
                return redirect('edit_profile')
                
            if otp_obj.otp == otp_input:
                user = request.user
                user.email = new_email
                user.save()
                
                # Clean up session
                if 'pending_email_change' in request.session:
                    del request.session['pending_email_change']
                
                otp_obj.delete()
                messages.success(request, 'Email updated successfully!')
                return redirect('user_dashboard')
            else:
                messages.error(request, 'Invalid OTP. Please try again.')
        except EmailOTP.DoesNotExist:
            messages.error(request, 'No OTP found. Please try again.')
            return redirect('edit_profile')
            
    return render(request, 'verify_email_otp.html', {'new_email': new_email})


@login_required
@never_cache
def resend_email_otp(request):
    new_email = request.session.get('pending_email_change')
    if not new_email:
        return redirect('edit_profile')
        
    # Optional Cooldown check (similar to accounts app)
    # last_otp = request.user.otps.order_by('-created_at').first()
    # if last_otp and ...

    otp_obj = EmailOTP.objects.create(user=request.user)
    
    send_mail(
        "Verify Your New Email (Resent)",
        f"Your OTP for changing email to {new_email} is: {otp_obj.otp}",
        settings.EMAIL_HOST_USER,
        [new_email],
    )
    
    messages.success(request, f"A new OTP has been sent to {new_email}.")
    return redirect('verify_email_change')


@login_required
@never_cache
def account_edit(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  
            messages.success(request, 'Your password was successfully updated!')
            return redirect('user_dashboard')
        else:
            messages.error(request, 'Please correct the error below.')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'account_edit.html', {
        'form': form
    })

@login_required
@never_cache
def notifications_view(request):
    from user_apps.core.models import Notification
    # Get all notifications for the user, ordered by newest first
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    
    # Mark them as read automatically upon viewing
    unread_notifications = notifications.filter(is_read=False)
    if unread_notifications.exists():
        unread_notifications.update(is_read=True)
        
    return render(request, 'notifications.html', {
        'notifications': notifications
    })

@login_required
@never_cache
def cart_view(request):
    cart, created = Cart.objects.get_or_create(user=request.user)
    items = cart.items.select_related('product').all()
    subtotal = sum(item.total_price for item in items)
    tax = subtotal * Decimal('0.05') # 5% tax
    shipping = Decimal('0.00')
    if subtotal >= Decimal('20000.00'):
        shipping = Decimal('99.00')
    elif subtotal >= Decimal('5000.00'):
        shipping = Decimal('49.00')
    total = subtotal + tax + shipping
    
    has_stock_issues = False
    for item in items:
        if item.product.stock == 0 or not item.product.is_active or item.product.is_deleted or item.product.collection.is_deleted:
            has_stock_issues = True
            break
        elif item.quantity > item.product.stock:
            has_stock_issues = True
            break
            
    return render(request, 'cart.html', {
        'cart': cart,
        'items': items,
        'subtotal': subtotal,
        'shipping': shipping,
        'tax': tax,
        'total': total,
        'has_stock_issues': has_stock_issues
    })

@login_required
def add_to_cart(request, product_id):
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        
        try:
            data = json.loads(request.body)
            quantity = int(data.get('quantity', 1))
            variant_id = data.get('variant_id')
        except:
            quantity = 1
            variant_id = None
            
        # Prevent adding blocked/unlisted products
        if not product.is_active or product.is_deleted or product.collection.is_deleted:
            return JsonResponse({'success': False, 'error': 'Product is currently unavailable'})
            
        variant = None
        if variant_id:
            from user_apps.core.models import ProductVariant
            variant = ProductVariant.objects.filter(id=variant_id, product=product).first()
        
        # Check stock of variant if it exists, else base product
        available_stock = variant.stock if variant else product.stock
        if available_stock <= 0:
            return JsonResponse({'success': False, 'error': 'Item is out of stock'})
        
        MAX_QTY = 10
        if quantity > MAX_QTY:
            return JsonResponse({'success': False, 'error': f'Maximum quantity per item is {MAX_QTY}'})
        if quantity > available_stock:
            return JsonResponse({'success': False, 'error': f'Only {available_stock} items available in stock'})
            
        cart, created = Cart.objects.get_or_create(user=request.user)
        
        # Check if item exists in cart
        cart_item, item_created = CartItem.objects.get_or_create(
            cart=cart, 
            product=product,
            variant=variant,
            defaults={'quantity': quantity}
        )
        
        if not item_created:
            if cart_item.quantity + quantity <= min(available_stock, MAX_QTY):
                cart_item.quantity += quantity
                cart_item.save()
            elif cart_item.quantity >= MAX_QTY:
                return JsonResponse({'success': False, 'error': f'Maximum quantity limit reached in your cart.'})
            else:
                return JsonResponse({'success': False, 'error': f'Only {available_stock} items available. You already have {cart_item.quantity} in cart.'})
                
        # Remove from wishlist when added to cart
        if hasattr(request.user, 'wishlist'):
            WishlistItem.objects.filter(wishlist=request.user.wishlist, product=product).delete()
                
        # Total cart items count
        cart_count = sum(item.quantity for item in cart.items.all())
                
        return JsonResponse({'success': True, 'message': 'Added to cart', 'cart_count': cart_count})
        
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def update_cart(request, item_id):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            action = data.get('action')
            cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
            product = cart_item.product
            
            MAX_QTY = 10
            
            if action == 'increase':
                if not product.is_active or product.is_deleted or product.collection.is_deleted:
                     return JsonResponse({'success': False, 'error': 'Product is currently unavailable'})
                
                if cart_item.quantity < min(product.stock, MAX_QTY):
                    cart_item.quantity += 1
                    cart_item.save()
                elif cart_item.quantity >= MAX_QTY:
                    return JsonResponse({'success': False, 'error': 'Maximum quantity limit reached'})
                else:
                    return JsonResponse({'success': False, 'error': 'Not enough stock'})
            
            elif action == 'decrease':
                if cart_item.quantity > 1:
                    cart_item.quantity -= 1
                    cart_item.save()
                else:
                    return JsonResponse({'success': False, 'error': 'Minimum quantity is 1. Use remove instead.'})
            else:
                return JsonResponse({'success': False, 'error': 'Invalid action'})
                
            # Recalculate totals
            cart = cart_item.cart
            items = cart.items.select_related('product').all()
            subtotal = sum(item.total_price for item in items)
            tax = subtotal * Decimal('0.05')
            shipping = Decimal('0.00')
            if subtotal >= Decimal('20000.00'):
                shipping = Decimal('99.00')
            elif subtotal >= Decimal('5000.00'):
                shipping = Decimal('49.00')
            total = subtotal + tax + shipping
            cart_count = sum(item.quantity for item in items)
            
            return JsonResponse({
                'success': True,
                'cart_count': cart_count,
                'item_total': str(cart_item.total_price),
                'item_quantity': cart_item.quantity,
                'subtotal': str(subtotal),
                'shipping': str(shipping),
                'tax': str(round(tax, 2)),
                'total': str(round(total, 2))
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
            
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def remove_from_cart(request, item_id):
    # Ensure the item belongs to the user's cart
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    cart_item.delete()
    messages.success(request, 'Item removed from cart.')
    return redirect('cart_view')

@login_required
@never_cache
def wishlist_view(request):
    wishlist, created = Wishlist.objects.get_or_create(user=request.user)
    items = wishlist.items.select_related('product').all()
    return render(request, 'wishlist.html', {
        'items': items
    })

def toggle_wishlist(request, product_id):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Please login to modify your wishlist.'})
        
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        wishlist, created = Wishlist.objects.get_or_create(user=request.user)
        
        wishlist_item = WishlistItem.objects.filter(wishlist=wishlist, product=product).first()
        
        if wishlist_item:
            wishlist_item.delete()
            action = 'removed'
        else:
            # Only check availability when ADDING (stock is okay for wishlist)
            if not product.is_active or product.is_deleted or product.collection.is_deleted:
                return JsonResponse({'success': False, 'error': 'Product is currently unavailable'})
                
            WishlistItem.objects.create(wishlist=wishlist, product=product)
            action = 'added'
            
        wishlist_count = wishlist.items.count()
        return JsonResponse({'success': True, 'action': action, 'wishlist_count': wishlist_count})
        
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def remove_wishlist_item(request, item_id):
    if request.method == 'POST':
        wishlist_item = get_object_or_404(WishlistItem, id=item_id, wishlist__user=request.user)
        wishlist_item.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def save_for_later(request, item_id):
    if request.method == 'POST':
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        product = cart_item.product
        
        # Add to wishlist
        wishlist, created = Wishlist.objects.get_or_create(user=request.user)
        WishlistItem.objects.get_or_create(wishlist=wishlist, product=product)
        
        # Delete from cart
        cart_item.delete()
        
        # Recalculate totals
        cart = request.user.cart
        items = cart.items.select_related('product').all()
        subtotal = sum(item.total_price for item in items)
        tax = subtotal * Decimal('0.05')
        shipping = Decimal('0.00')
        if subtotal > 0 and subtotal < Decimal('5000.00'):
            shipping = Decimal('99.00')
        total = subtotal + tax + shipping
        cart_count = sum(item.quantity for item in items)
        
        return JsonResponse({
            'success': True,
            'cart_count': cart_count,
            'subtotal': str(subtotal),
            'shipping': str(shipping),
            'tax': str(round(tax, 2)),
            'total': str(round(total, 2))
        })
    return JsonResponse({'success': False, 'error': 'Invalid request'})
