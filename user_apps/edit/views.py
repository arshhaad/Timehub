"""User Profile & Shopping Views."""

import json
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect, reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.db.models import Sum
from django.conf import settings
from django.utils import timezone

from .models import Address
from .forms import AddressForm, UserEditForm
from user_apps.accounts.models import EmailOTP, CustomUser
from user_apps.accounts.utils import send_otp_email
from user_apps.core.models import (
    Cart, CartItem, Product, WishlistItem, 
    Wishlist, Order, Wallet, WalletTransaction, Notification
)




@login_required
@never_cache
def dashboard(request):
    """Show user account dashboard summary."""
    user = request.user
    
    # 1. Ensure user has a unique referral code
    if not user.referral_code:
        from user_apps.core.signals import generate_referral_code
        code = f"TH-{generate_referral_code()}"
        while CustomUser.objects.filter(referral_code=code).exists():
            code = f"TH-{generate_referral_code()}"
        user.referral_code = code
        user.save(update_fields=['referral_code'])
    
    # 2. Gather simple statistics
    total_orders = user.orders.count()
    wishlist, _ = Wishlist.objects.get_or_create(user=user)
    saved_items = wishlist.items.count()
    
    stats = {
        'total_orders': total_orders,
        'saved_items': saved_items,
        'reward_points': 0, # Future feature placeholder
    }
    
    recent_orders = user.orders.order_by('-created_at')[:5]
    
    context = {
        'user': user,
        'stats': stats,
        'recent_orders': recent_orders,
        'referral_code': user.referral_code,
        "referral_url": request.build_absolute_uri(reverse('referral_redirect', args=[user.referral_code])),
    }
    return render(request, 'user_dashboard.html', context)


@login_required
@never_cache
def edit_profile(request):
    """Update user profile personal information."""
    if request.method == 'POST':
        form = UserEditForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            new_email = form.cleaned_data.get('email')
            
            # Check if user is trying to change their email address
            if new_email and new_email != request.user.email:
                # Security: Check if new email is already taken
                if CustomUser.objects.filter(email=new_email).exclude(id=request.user.id).exists():
                    messages.error(request, 'This email is already linked to another account.')
                    return render(request, 'edit_profile.html', {'form': form})

                # Save non-email changes first
                user = form.save(commit=False)
                user.email = request.user.email # Revert email for now
                user.save()
                form.save_m2m()

                # Trigger OTP Verification Flow
                request.session['pending_email_change'] = new_email
                otp_obj = EmailOTP.objects.create(user=request.user)
                send_otp_email(new_email, otp_obj.otp, context="email_change")
                
                messages.info(request, f"Please verify the code sent to {new_email} to update your email.")
                return redirect('verify_email_change')
            
            # Standard profile update (no email change)
            form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('user_dashboard')
    else:
        form = UserEditForm(instance=request.user)

    return render(request, 'edit_profile.html', {'form': form})


@login_required
@never_cache
def account_edit(request):
    """Change account security password."""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            # Important: Keep the user logged in after password change
            update_session_auth_hash(request, user)  
            messages.success(request, 'Password updated successfully!')
            return redirect('user_dashboard')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PasswordChangeForm(request.user)
    
    return render(request, 'account_edit.html', {'form': form}, status=400 if request.method == 'POST' else 200)




@login_required
@never_cache
def verify_email_change(request):
    """Verify OTP for email update request."""
    new_email = request.session.get('pending_email_change')
    if not new_email:
        return redirect('edit_profile')
        
    if request.method == 'POST':
        otp_input = request.POST.get('otp', '').strip()
        try:
            # Check against the latest OTP issued to this user
            otp_obj = request.user.otps.latest('created_at')
            
            if otp_obj.is_expired:
                messages.error(request, 'Verification code expired. Please try again.')
                return redirect('edit_profile')
                
            if otp_obj.otp == otp_input:
                # Verification success — update the email for real
                user = request.user
                user.email = new_email
                user.save()
                
                # Cleanup
                if 'pending_email_change' in request.session:
                    del request.session['pending_email_change']
                otp_obj.delete()
                
                messages.success(request, 'Email address updated successfully!')
                return redirect('user_dashboard')
            else:
                messages.error(request, 'Incorrect code. Please try again.')
        except EmailOTP.DoesNotExist:
            messages.error(request, 'Session expired. Please restart the process.')
            return redirect('edit_profile')
            
    return render(request, 'verify_email_otp.html', {'new_email': new_email})


@login_required
@never_cache
def resend_email_otp(request):
    """Resend OTP for email verification."""
    new_email = request.session.get('pending_email_change')
    if not new_email:
        return redirect('edit_profile')
        
    otp_obj = EmailOTP.objects.create(user=request.user)
    send_otp_email(new_email, otp_obj.otp, context="email_change")
    
    messages.success(request, f"A new code has been sent to {new_email}.")
    return redirect('verify_email_change')




@login_required
@never_cache
def address_list(request):
    """List all saved delivery addresses."""
    addresses = Address.objects.filter(user=request.user)
    return render(request, 'address.html', {'addresses': addresses})


@login_required
@never_cache
def add_address(request):
    """Create a new delivery address."""
    next_url = request.GET.get('next') or request.POST.get('next') or 'address_list'
    if request.method == 'POST':
        form = AddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user
            # Ensure only one default address exists
            if address.is_default:
                Address.objects.filter(user=request.user).update(is_default=False)
            address.save()
            messages.success(request, 'New address saved!')
            return redirect(next_url)
    else:
        form = AddressForm()
    return render(request, 'address_form.html', {'form': form, 'next': next_url})


@login_required
@never_cache
def edit_address(request, address_uuid):
    """Update an existing delivery address."""
    address = get_object_or_404(Address, uuid=address_uuid, user=request.user)
    next_url = request.GET.get('next') or request.POST.get('next') or 'address_list'
    if request.method == 'POST':
        form = AddressForm(request.POST, instance=address)
        if form.is_valid():
            address = form.save(commit=False)
            if address.is_default:
                Address.objects.filter(user=request.user).exclude(uuid=address_uuid).update(is_default=False)
            address.save()
            messages.success(request, 'Address updated.')
            return redirect(next_url)
    else:
        form = AddressForm(instance=address)
    return render(request, 'address_form.html', {'form': form, 'next': next_url})


@login_required
@never_cache
def delete_address(request, address_uuid):
    """Delete a saved delivery address."""
    address = get_object_or_404(Address, uuid=address_uuid, user=request.user)
    address.delete()
    messages.success(request, 'Address removed.')
    return redirect('address_list')


@login_required
@never_cache
def toggle_default_address(request, address_uuid):
    """Set an address as the primary default."""
    address = get_object_or_404(Address, uuid=address_uuid, user=request.user)
    if not address.is_default:
        Address.objects.filter(user=request.user, is_default=True).update(is_default=False)
        address.is_default = True
    else:
        address.is_default = False
    address.save()
    return redirect('address_list')




@login_required
@never_cache
def cart_view(request):
    """View shopping cart and price breakdown."""
    cart, _ = Cart.objects.get_or_create(user=request.user)
    items = cart.items.select_related('product', 'variant').all()
    
    # 1. Base Calculations & Offer Savings
    from django.utils import timezone as _tz
    _now = _tz.now()

    base_subtotal = Decimal('0')
    product_offer_savings = Decimal('0')
    category_offer_savings = Decimal('0')
    subtotal = Decimal('0')

    for item in items:
        # The price as it appears in the catalog (usually discounted)
        item_price = item.variant.display_price if item.variant else item.product.display_price
        # The original price (before any offers)
        original_price = item.variant.effective_price if item.variant else item.product.price
        
        subtotal += item_price * item.quantity
        base_subtotal += original_price * item.quantity
        
        # Calculate specific offer savings for this item
        saving_per_unit = max(Decimal('0'), original_price - item_price)
        if saving_per_unit > 0:
            p_off = item.product.product_offers.filter(
                is_active=True, valid_from__lte=_now, valid_to__gte=_now
            ).order_by('-discount_percentage').first()
            c_off = item.product.collection.category_offers.filter(
                is_active=True, valid_from__lte=_now, valid_to__gte=_now
            ).order_by('-discount_percentage').first()
            
            p_disc = p_off.discount_percentage if p_off else 0
            c_disc = c_off.discount_percentage if c_off else 0
            
            if p_disc >= c_disc:
                product_offer_savings += saving_per_unit * item.quantity
            else:
                category_offer_savings += saving_per_unit * item.quantity

    # Shipping: Free on ₹5000+ else ₹49 (calculated on the discounted subtotal)
    if subtotal == 0: shipping = Decimal('0.00')
    elif subtotal >= Decimal('5000.00'): shipping = Decimal('0.00')
    else: shipping = Decimal('49.00')

    # 2. Discount Logic (Coupon & Referral)
    from admin_apps.offers.services import get_referral_first_order_discount
    coupon_discount = Decimal('0')
    if cart.coupon and cart.coupon.is_valid_for_user(request.user)[0]:
        # Narrow down collection-specific coupons
        if cart.coupon.applicable_collection:
            collection_ids = cart.coupon.applicable_collection.get_all_descendant_ids()
            applicable_items = [i for i in items if i.product.collection_id in collection_ids]
            applicable_subtotal = sum(i.total_price for i in applicable_items)
        else:
            applicable_subtotal = subtotal
            
        if applicable_subtotal >= cart.coupon.min_purchase_amount:
            if cart.coupon.discount_type == 'percentage':
                coupon_discount = (applicable_subtotal * cart.coupon.discount_value) / Decimal('100')
                if cart.coupon.max_discount_amount:
                    coupon_discount = min(coupon_discount, cart.coupon.max_discount_amount)
            else:
                coupon_discount = min(cart.coupon.discount_value, applicable_subtotal)

    referral_discount = get_referral_first_order_discount(request.user, items=items)
    discount = coupon_discount + referral_discount

    # 3. Final Totals
    taxable = max(Decimal('0'), subtotal - discount)
    tax = round(taxable * Decimal('0.03'), 2)
    total = taxable + tax + shipping

    # 4. Availability Warnings
    has_stock_issues = False
    for item in items:
        if not item.product.is_active or item.product.is_deleted:
            has_stock_issues = True; break
        
        stock = item.variant.stock if item.variant else item.product.stock
        if stock < item.quantity:
            has_stock_issues = True; break
            
    # Progress bar for free shipping
    shipping_needed = max(0, Decimal('5000.00') - subtotal)
    shipping_percent = min(100, int((subtotal / Decimal('5000.00')) * 100)) if subtotal < Decimal('5000.00') else 100

    total_saved = product_offer_savings + category_offer_savings + coupon_discount + referral_discount

    return render(request, 'cart.html', {
        'cart': cart, 'items': items,
        'base_subtotal': base_subtotal,
        'subtotal': subtotal, # This is the taxable amount before coupon/referral
        'product_offer_savings': product_offer_savings,
        'category_offer_savings': category_offer_savings,
        'coupon_discount': coupon_discount,
        'referral_discount': referral_discount,
        'total_saved': total_saved,
        'shipping': shipping, 'tax': tax, 'total': total,
        'has_stock_issues': has_stock_issues,
        'shipping_needed': shipping_needed, 'shipping_percentage': shipping_percent
    })


@login_required
def add_to_cart(request, product_uuid):
    """Add a product or variant to the cart."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'})

    product = get_object_or_404(Product, uuid=product_uuid)
    
    try:
        data = json.loads(request.body)
        quantity = int(data.get('quantity', 1))
        variant_id = data.get('variant_id')
    except:
        quantity, variant_id = 1, None
            
    # Basic Validation
    if not product.is_active or product.is_deleted or product.collection.is_deleted:
        return JsonResponse({'success': False, 'error': 'Product is currently unavailable'})
            
    # Resolve Variant
    active_variants = product.variants.filter(is_active=True)
    variant = active_variants.filter(id=variant_id).first() if variant_id else None
    
    if not variant and active_variants.exists():
        # Fallback to first available if none selected
        variant = active_variants.first()
        
    # Stock Check
    stock = variant.stock if variant else product.stock
    if stock <= 0: return JsonResponse({'success': False, 'error': 'Item is out of stock'})
        
    MAX_QTY = 10
    if quantity > stock: return JsonResponse({'success': False, 'error': f'Only {stock} items left'})
    if quantity > MAX_QTY: return JsonResponse({'success': False, 'error': f'Maximum {MAX_QTY} per item allowed'})
            
    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart_item, created = CartItem.objects.get_or_create(
        cart=cart, product=product, variant=variant,
        defaults={'quantity': quantity}
    )
    
    if not created:
        if cart_item.quantity + quantity <= min(stock, MAX_QTY):
            cart_item.quantity += quantity
            cart_item.save()
        else:
            return JsonResponse({'success': False, 'error': 'Cannot add more: Stock or Limit reached'})
                
    # Cleanup Wishlist if added to cart
    WishlistItem.objects.filter(wishlist__user=request.user, product=product).delete()
                
    count = sum(i.quantity for i in cart.items.all())
    return JsonResponse({
        'success': True, 
        'message': 'Added to cart', 
        'cart_count': count,
        'item_id': cart_item.id
    })


@login_required
def update_cart(request, item_id):
    """Adjust item quantity in the cart."""
    if request.method != 'POST': return JsonResponse({'success': False})

    try:
        data = json.loads(request.body)
        action = data.get('action')
        item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        
        # Increase/Decrease Logic
        if action == 'increase':
            stock = item.variant.stock if item.variant else item.product.stock
            if item.quantity >= 10: return JsonResponse({'success': False, 'error': 'Limit: 10 units'})
            if item.quantity >= stock: return JsonResponse({'success': False, 'error': 'Out of stock'})
            item.quantity += 1
        elif action == 'decrease' and item.quantity > 1:
            item.quantity -= 1
        else:
            return JsonResponse({'success': False, 'error': 'Invalid action'})
            
        item.save()
        
        # Fresh Totals Calculation
        cart = item.cart  # re-bind after item.save()
        all_items = cart.items.select_related('product', 'variant').all()
        from django.utils import timezone as _tz
        from admin_apps.offers.services import get_referral_first_order_discount
        _now = _tz.now()

        base_subtotal = Decimal('0')
        product_offer_savings = Decimal('0')
        category_offer_savings = Decimal('0')
        subtotal = Decimal('0')

        for i in all_items:
            i_price = i.variant.display_price if i.variant else i.product.display_price
            orig_price = i.variant.effective_price if i.variant else i.product.price

            subtotal += i_price * i.quantity
            base_subtotal += orig_price * i.quantity

            save_per = max(Decimal('0'), orig_price - i_price)
            if save_per > 0:
                p_o = i.product.product_offers.filter(
                    is_active=True, valid_from__lte=_now, valid_to__gte=_now
                ).order_by('-discount_percentage').first()
                c_o = i.product.collection.category_offers.filter(
                    is_active=True, valid_from__lte=_now, valid_to__gte=_now
                ).order_by('-discount_percentage').first()
                if (p_o.discount_percentage if p_o else 0) >= (c_o.discount_percentage if c_o else 0):
                    product_offer_savings += save_per * i.quantity
                else:
                    category_offer_savings += save_per * i.quantity

        # Coupon discount (on post-offer subtotal)
        coupon_discount = Decimal('0')
        if cart.coupon and cart.coupon.is_valid_for_user(cart.user)[0]:
            if cart.coupon.applicable_collection:
                collection_ids = cart.coupon.applicable_collection.get_all_descendant_ids()
                applicable_items = [i for i in all_items if i.product.collection_id in collection_ids]
                applicable_subtotal = sum(i.total_price for i in applicable_items)
            else:
                applicable_subtotal = subtotal
            if applicable_subtotal >= cart.coupon.min_purchase_amount:
                if cart.coupon.discount_type == 'percentage':
                    coupon_discount = (applicable_subtotal * cart.coupon.discount_value) / Decimal('100')
                    if cart.coupon.max_discount_amount:
                        coupon_discount = min(coupon_discount, cart.coupon.max_discount_amount)
                else:
                    coupon_discount = min(cart.coupon.discount_value, applicable_subtotal)

        referral_discount = get_referral_first_order_discount(cart.user, items=all_items)
        discount = coupon_discount + referral_discount

        # Shipping: based on post-offer subtotal
        ship = Decimal('0') if subtotal == 0 or subtotal >= Decimal('5000') else Decimal('49')

        # Tax on (subtotal − coupon/referral discount)
        taxable = max(Decimal('0'), subtotal - discount)
        tax = round(taxable * Decimal('0.03'), 2)
        total = taxable + tax + ship
        total_saved = product_offer_savings + category_offer_savings + coupon_discount + referral_discount

        return JsonResponse({
            'success': True,
            'cart_count': sum(i.quantity for i in all_items),
            'item_total': str(item.total_price),
            'item_quantity': item.quantity,
            'base_subtotal': str(base_subtotal),
            'subtotal': str(subtotal),
            'product_offer_savings': str(product_offer_savings),
            'category_offer_savings': str(category_offer_savings),
            'coupon_discount': str(coupon_discount),
            'referral_discount': str(referral_discount),
            'shipping': str(ship),
            'tax': str(tax),
            'total': str(total),
            'total_saved': str(total_saved),
            'shipping_needed': str(max(Decimal('0'), Decimal('5000') - subtotal))
        })
    except: return JsonResponse({'success': False})


@login_required
def remove_from_cart(request, item_id):
    """Remove an item from the shopping cart."""
    item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    item.delete()
    messages.success(request, 'Item removed.')
    return redirect('cart_view')


@login_required
@never_cache
def wishlist_view(request):
    """View saved items in the wishlist."""
    wishlist, _ = Wishlist.objects.get_or_create(user=request.user)
    items = wishlist.items.select_related('product').all()
    return render(request, 'wishlist.html', {'items': items})


def toggle_wishlist(request, product_uuid):
    """Add or remove an item from the wishlist."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Please login first.'})
        
    if request.method == 'POST':
        product = get_object_or_404(Product, uuid=product_uuid)
        wishlist, _ = Wishlist.objects.get_or_create(user=request.user)
        
        item = WishlistItem.objects.filter(wishlist=wishlist, product=product).first()
        if item:
            item.delete()
            status = 'removed'
        else:
            # Check availability only for adding
            if not product.is_active or product.is_deleted:
                return JsonResponse({'success': False, 'error': 'Unavailable'})
            WishlistItem.objects.create(wishlist=wishlist, product=product)
            status = 'added'
            
        return JsonResponse({'success': True, 'action': status, 'wishlist_count': wishlist.items.count()})
    return JsonResponse({'success': False})


@login_required
def remove_wishlist_item(request, item_id):
    """Remove a specific item from the wishlist."""
    item = get_object_or_404(WishlistItem, id=item_id, wishlist__user=request.user)
    item.delete()
    messages.success(request, 'Item removed from wishlist.')
    return redirect('wishlist_view')


@login_required
def save_for_later(request, item_id):
    """Move an item from cart to wishlist."""
    if request.method == 'POST':
        item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        wishlist, _ = Wishlist.objects.get_or_create(user=request.user)
        WishlistItem.objects.get_or_create(wishlist=wishlist, product=item.product)
        item.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False})


@login_required
@never_cache
def notifications_view(request):
    """View system and order notifications."""
    notes = Notification.objects.filter(user=request.user).order_by('-created_at')
    # Auto-read on view
    notes.filter(is_read=False).update(is_read=True)
    return render(request, 'notifications.html', {'notifications': notes})


@login_required
@never_cache
def wallet_view(request):
    """View wallet balance and transactions."""
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    txs = wallet.transactions.all().order_by('-timestamp')
    
    # Summary Metrics
    added = txs.filter(transaction_type='Credit').aggregate(t=Sum('amount'))['t'] or 0
    spent = txs.filter(transaction_type='Debit').aggregate(t=Sum('amount'))['t'] or 0
    rewards = txs.filter(transaction_type='Credit', description__icontains='Referral').aggregate(t=Sum('amount'))['t'] or 0
    
    return render(request, 'wallet.html', {
        'wallet': wallet, 'transactions': txs,
        'total_added': added, 'total_spent': spent, 'total_rewards': rewards,
        'active_menu': 'wallet',
    })
