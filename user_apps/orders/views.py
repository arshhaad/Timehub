import json
from decimal import Decimal
import random
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404, reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.http import JsonResponse
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from user_apps.core.models import Cart, CartItem, Order, OrderItem, Product, Wallet, WalletTransaction
from admin_apps.offers.models import Coupon
from user_apps.edit.models import Address
from django.conf import settings
from admin_apps.offers.services import get_referral_first_order_discount
try:
    import razorpay
    RAZORPAY_CLIENT = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
except ImportError:
    RAZORPAY_CLIENT = None


SHIPPING_CHARGE = Decimal('49.00')
TAX_RATE = Decimal('0.03')  # 3% GST


def get_cart_totals(cart):
    """Helper to calculate subtotal, shipping, tax, discount and final total for a cart."""
    items = cart.items.select_related('product', 'variant').all()
    subtotal = sum(item.total_price for item in items)
    
    # Shipping logic
    if subtotal == 0:
        shipping = Decimal('0.00')
    elif subtotal >= Decimal('5000.00'):
        shipping = Decimal('0.00')
    else:
        shipping = Decimal('49.00')
    
    # Discount logic
    discount = Decimal('0')
    if cart.coupon and cart.coupon.is_valid and subtotal >= cart.coupon.min_purchase_amount:
        if cart.coupon.discount_type == 'percentage':
            discount = (subtotal * cart.coupon.discount_value) / Decimal('100')
            if cart.coupon.max_discount_amount:
                discount = min(discount, cart.coupon.max_discount_amount)
        else:
            discount = cart.coupon.discount_value
    # Referral First Order Discount
    referral_discount = get_referral_first_order_discount(cart.user, subtotal)
    discount += referral_discount
            
    taxable_amount = max(Decimal('0'), subtotal - discount)
    tax = round(taxable_amount * TAX_RATE, 2)
    total = taxable_amount + tax + shipping
    
    return {
        'items': items,
        'subtotal': subtotal,
        'shipping': shipping,
        'tax': tax,
        'discount': discount,
        'total': total
    }


from django.views.decorators.csrf import ensure_csrf_cookie

@login_required
@never_cache
@ensure_csrf_cookie
def checkout_page(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    items = cart.items.select_related('product').all()

    if not items.exists():
        messages.warning(request, 'Your cart is empty. Add items before checking out.')
        return redirect('cart_view')

    subtotal = sum(item.total_price for item in items)
    if subtotal == 0:
        shipping = Decimal('0.00')
    elif subtotal >= Decimal('5000.00'):
        shipping = Decimal('0.00')
    else:
        shipping = Decimal('49.00')
    
    tax = Decimal('0')
    discount = Decimal('0')
    if cart.coupon:
        if cart.coupon.is_valid and subtotal >= cart.coupon.min_purchase_amount:
            if cart.coupon.discount_type == 'percentage':
                discount = (subtotal * cart.coupon.discount_value) / Decimal('100')
                if cart.coupon.max_discount_amount:
                    discount = min(discount, cart.coupon.max_discount_amount)
            else:
                discount = cart.coupon.discount_value
        else:
            # Coupon no longer valid or min amount not met
            cart.coupon = None
            cart.save()
            
    # Referral First Order Discount
    referral_discount = get_referral_first_order_discount(request.user, subtotal)
    discount += referral_discount
            
    taxable_amount = subtotal - discount
    if taxable_amount < Decimal('0'): taxable_amount = Decimal('0')
    tax = round(taxable_amount * TAX_RATE, 2)
    total = taxable_amount + tax + shipping

    addresses = Address.objects.filter(user=request.user)
    default_address = addresses.filter(is_default=True).first() or addresses.first()

    if request.method == 'POST':
        address_id = request.POST.get('address_id')
        payment_method = request.POST.get('payment_method', 'cod')

        if not address_id:
            messages.error(request, 'Please select a delivery address.')
            return render(request, 'checkout_page.html', {
                'items': items, 'subtotal': subtotal, 'tax': tax,
                'shipping': shipping, 'discount': discount, 'total': total,
                'cart': cart, 'addresses': addresses, 'default_address': default_address,
            })

        address = get_object_or_404(Address, id=address_id, user=request.user)

        # Snapshot address in JSON so order history is preserved even if address changes
        address_data = {
            'full_name': address.full_name,
            'street': address.street,
            'city': address.city,
            'state': address.state,
            'postal_code': address.postal_code,
            'country': address.country,
            'phone': address.phone,
        }

        with transaction.atomic():
            # Generate estimated delivery date (3–7 days from now) and save it
            days_to_delivery = random.randint(3, 7)
            estimated_delivery_date = (timezone.now() + timedelta(days=days_to_delivery)).date()

            # Wallet deduction if applicable
            if payment_method == 'wallet':
                wallet, _ = Wallet.objects.get_or_create(user=request.user)
                if wallet.balance < total:
                    messages.error(request, 'Insufficient wallet balance.')
                    return render(request, 'checkout_page.html', {
                        'items': items, 'subtotal': subtotal, 'tax': tax,
                        'shipping': shipping, 'discount': discount, 'total': total,
                        'cart': cart, 'addresses': addresses, 'default_address': default_address,
                    })
                wallet.balance -= total
                wallet.save()
                
            order = Order.objects.create(
                user=request.user,
                address_snapshot=json.dumps(address_data),
                payment_method=payment_method,
                subtotal=subtotal,
                tax=tax,
                shipping_charge=shipping,
                discount=discount,
                total_amount=total,
                status='Pending',
                is_paid=True if payment_method == 'wallet' else False,
                scheduled_delivery_date=estimated_delivery_date,
                coupon_code=cart.coupon.code if cart.coupon else None,
            )

            if payment_method == 'wallet':
                WalletTransaction.objects.create(
                    wallet=wallet,
                    transaction_type='Debit',
                    amount=total,
                    description=f'Payment for Order #{order.id}'
                )

            if cart.coupon:
                cart.coupon.used_count += 1
                cart.coupon.save()

            for item in items:
                available_stock = item.variant.stock if item.variant else item.product.stock
                if available_stock < item.quantity:
                    messages.error(request, f"Sorry, only {available_stock} units of {item.product.name} are available.")
                    raise Exception("Insufficient stock")

                price_at_purchase = item.variant.effective_discount_price if item.variant else (item.product.discount_price or item.product.price)
                
                OrderItem.objects.create(
                    order=order,
                    product=item.product,
                    variant=item.variant,
                    quantity=item.quantity,
                    price=price_at_purchase,
                )
                
                # Decrement Stock
                if item.variant:
                    item.variant.stock -= item.quantity
                    item.variant.save()
                else:
                    item.product.stock -= item.quantity
                    item.product.save()

            # Clear cart
            cart.items.all().delete()

        if payment_method == 'razorpay':
            return redirect('payments:start_payment', order_id=order.id)

        return redirect('order_success', order_uuid=order.uuid)

    # Provide an estimated delivery date (randomly 1-7 days from today) for display
    days_to_add = random.randint(1, 7)
    estimated_delivery = timezone.now() + timedelta(days=days_to_add)

    # Fetch active coupons for the modal
    now = timezone.now()
    active_coupons = Coupon.objects.filter(is_active=True, valid_from__lte=now, valid_to__gte=now)
    # Exclude those that reached usage limit
    active_coupons = [c for c in active_coupons if c.is_valid]

    return render(request, 'checkout_page.html', {
        'items': items,
        'subtotal': subtotal,
        'tax': tax,
        'shipping': shipping,
        'discount': discount,
        'total': total,
        'cart': cart,
        'addresses': addresses,
        'default_address': default_address,
        'estimated_delivery': estimated_delivery,
        'active_coupons': active_coupons,
    })



@login_required
@never_cache
def order_success(request, order_uuid):
    order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
    order_items = order.items.select_related('product').all()
    try:
        address = json.loads(order.address_snapshot)
    except (json.JSONDecodeError, TypeError):
        address = {}

    return render(request, 'order_success.html', {
        'order': order,
        'order_items': order_items,
        'address': address,
    })


@login_required
def order_history(request):
    orders = Order.objects.filter(user=request.user).prefetch_related('items__product').order_by('-created_at')
    
    query = request.GET.get('q', '').strip()
    if query:
        orders = orders.filter(
            Q(id__icontains=query) |
            Q(items__product__name__icontains=query)
        ).distinct()
    
    return render(request, 'order_history.html', {'orders': orders, 'query': query})


@login_required
def order_detail(request, order_uuid):
    if request.user.is_staff or request.user.is_superuser:
        order = get_object_or_404(Order, uuid=order_uuid)
    else:
        order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
    items = order.items.select_related('product').all()
    address = {}
    try:
        address = json.loads(order.address_snapshot)
    except:
        pass
    
    # Auto-fix totals for pending/processing/shipped orders to reflect latest logic
    if order.status in ['Pending', 'Processing', 'Shipped']:
        order.update_totals()
    
    from datetime import datetime
    return render(request, 'order_detail.html', {
        'order': order,
        'items': items,
        'address': address,
        'today': datetime.now()
    })


@login_required
def cancel_order(request, order_uuid):
    order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
    
    if request.method == 'GET':
        if order.status not in ['Pending', 'Processing']:
            messages.error(request, 'This order cannot be cancelled')
            return redirect('order_detail', order_uuid=order.uuid)
        return render(request, 'cancel.html', {'order': order})
        
    if request.method == 'POST' and order.status in ['Pending', 'Processing']:
        reason = request.POST.get('reason', 'User cancelled')
        with transaction.atomic():
            original_total = order.total_amount

            order.status = 'Cancelled'
            order.cancel_reason = reason
            order.save()
            
            # Increment Stock
            for item in order.items.filter(is_cancelled=False):
                if item.variant:
                    item.variant.stock += item.quantity
                    item.variant.save()
                else:
                    product = item.product
                    product.stock += item.quantity
                    product.save()
                item.is_cancelled = True
                item.cancel_reason = 'Order cancelled'
                item.save()
            
            order.update_totals()
            
            if order.payment_method in ['razorpay', 'wallet']:
                wallet, _ = Wallet.objects.get_or_create(user=request.user)
                wallet.balance += original_total
                wallet.save()
                WalletTransaction.objects.create(
                    wallet=wallet,
                    transaction_type='Credit',
                    amount=original_total,
                    description=f'Refund for cancelled Order #{order.id}'
                )
                
        messages.success(request, f'Order #{order.id} has been cancelled.')
    else:
        messages.error(request, 'This order cannot be cancelled.')
    return redirect('order_detail', order_uuid=order.uuid)


@login_required
def cancel_order_item(request, item_uuid):
    if request.method != 'POST':
        return redirect('order_history')
        
    item = get_object_or_404(OrderItem, uuid=item_uuid, order__user=request.user)
    order = item.order
    
    if order.status in ['Pending', 'Processing'] and not item.is_cancelled:
        reason = request.POST.get('reason', 'User cancelled')
        with transaction.atomic():
            original_total = order.total_amount

            item.is_cancelled = True
            item.cancel_reason = reason
            item.save()
            
            # Increment Stock
            if item.variant:
                item.variant.stock += item.quantity
                item.variant.save()
            else:
                product = item.product
                product.stock += item.quantity
                product.save()
            
            # Note: We are no longer automatically cancelling the entire order 
            # when all items are cancelled to allow for more granular control.
            order.update_totals()
            
            if order.payment_method in ['razorpay', 'wallet']:
                refund_amount = original_total - order.total_amount
                if refund_amount > 0:
                    wallet, _ = Wallet.objects.get_or_create(user=request.user)
                    wallet.balance += refund_amount
                    wallet.save()
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        transaction_type='Credit',
                        amount=refund_amount,
                        description=f'Refund for cancelled item in Order #{order.id}'
                    )
                
        messages.success(request, f'Item "{item.product.name}" has been cancelled.')
    else:
        messages.error(request, 'This item cannot be cancelled.')
        
    return redirect('order_detail', order_uuid=order.uuid)


@login_required
def return_order(request, order_uuid):
    if request.method != 'POST':
        return redirect('order_history')
        
    order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
    
    if order.status == 'Delivered':
        reason = request.POST.get('reason')
        if not reason:
            messages.error(request, 'Please provide a reason for the return.')
            return redirect('order_detail', order_uuid=order.uuid)
            
        order.status = 'Return Requested'
        order.return_status = 'Requested'
        order.return_reason = reason
        order.save()
        messages.success(request, 'Return request submitted successfully.')
    else:
        messages.error(request, 'This order is not eligible for return.')
        
    return redirect('order_detail', order_uuid=order.uuid)


@login_required
def download_invoice(request, order_uuid):
    order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
    items = order.items.filter(is_cancelled=False)
    try:
        address = json.loads(order.address_snapshot)
    except:
        address = {}
        
    # Auto-fix totals for pending/processing/shipped orders to reflect latest logic
    if order.status in ['Pending', 'Processing', 'Shipped']:
        order.update_totals()
        
    return render(request, 'invoice.html', {
        'order': order,
        'items': items,
        'address': address
    })

@login_required
def reschedule_order(request, order_uuid):
    order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
    
    if order.status not in ['Pending', 'Processing']:
        messages.error(request, f"Order cannot be rescheduled as it is currently {order.status}.")
        return redirect('order_detail', order_uuid=order.uuid)

    if order.reschedule_count >= 1:
        messages.error(request, "This order has already been successfully rescheduled once and cannot be changed again.")
        return redirect('order_detail', order_uuid=order.uuid)

    if order.reschedule_status == 'Pending':
        messages.error(request, "A reschedule request is already pending for this order.")
        return redirect('order_detail', order_uuid=order.uuid)

    if order.reschedule_status == 'Rejected':
        messages.error(request, "Your previous reschedule request was declined and cannot be resubmitted for this order.")
        return redirect('order_detail', order_uuid=order.uuid)

    if request.method == 'GET':
        from datetime import datetime
        return render(request, 'Rq_reschedule.html', {
            'order': order,
            'today': datetime.now()
        })

    if request.method == 'POST':
        new_date = request.POST.get('scheduled_date')
        new_time = request.POST.get('scheduled_time')
        reason = request.POST.get('reschedule_reason', '').strip()
        
        if reason and len(reason) >= 8:
            from datetime import datetime
            try:
                if new_date:
                    date_obj = datetime.strptime(new_date, '%Y-%m-%d').date()
                    if date_obj < datetime.now().date():
                        messages.error(request, "Delivery date cannot be in the past.")
                        return redirect('reschedule_order', order_uuid=order.uuid)
                    order.requested_reschedule_date = date_obj

                if new_time:
                    time_obj = datetime.strptime(new_time, '%H:%M').time()
                    order.requested_reschedule_time = time_obj
                
                order.reschedule_reason = reason
                order.reschedule_status = 'Pending'
                order.save()
                display_date = date_obj if new_date else order.requested_reschedule_date
                messages.success(request, f"Reschedule request for {display_date.strftime('%B %d, %Y') if display_date else 'delivery'} submitted.")
            except ValueError:
                messages.error(request, "Invalid date or time format.")
        else:
            messages.error(request, "A valid and detailed reason is required to reschedule.")
        
        return redirect('order_detail', order_uuid=order.uuid)
    return redirect('order_history')

@login_required
def track_order(request, order_uuid):
    from django.shortcuts import get_object_or_404
    if request.user.is_staff or request.user.is_superuser:
        order = get_object_or_404(Order, uuid=order_uuid)
    else:
        order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
        
    items = order.items.select_related('product').all()
    try:
        address = json.loads(order.address_snapshot)
    except:
        address = {}
    return render(request, 'track_order.html', {'order': order, 'items': items, 'address': address})


@login_required
def add_address(request):
# ... (rest of the file)
    """AJAX endpoint to add a new address from checkout page."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = request.POST

        from user_apps.edit.forms import AddressForm
        form = AddressForm(data)
        
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user
            address.is_default = False
            address.save()

            return JsonResponse({
                'success': True,
                'address': {
                    'uuid': str(address.uuid),
                    'full_name': address.full_name,
                    'street': address.street,
                    'city': address.city,
                    'state': address.state,
                    'postal_code': address.postal_code,
                    'country': address.country,
                    'phone': address.phone,
                    'is_default': address.is_default,
                }
            })
        else:
            # Return field-specific errors
            return JsonResponse({
                'success': False,
                'errors': {field: errors[0] for field, errors in form.errors.items()}
            })

    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required
def edit_address(request, address_uuid):
    """AJAX endpoint to edit an address from checkout page."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = request.POST
            
        address = get_object_or_404(Address, uuid=address_uuid, user=request.user)

        from user_apps.edit.forms import AddressForm
        form = AddressForm(data, instance=address)
        
        if form.is_valid():
            updated_address = form.save(commit=False)
            # Default keeps its old value because the form doesn't handle is_default 
            updated_address.save()

            return JsonResponse({
                'success': True,
                'address': {
                    'uuid': str(updated_address.uuid),
                    'full_name': updated_address.full_name,
                    'street': updated_address.street,
                    'city': updated_address.city,
                    'state': updated_address.state,
                    'postal_code': updated_address.postal_code,
                    'country': updated_address.country,
                    'phone': updated_address.phone,
                    'is_default': updated_address.is_default,
                }
            })
        else:
            return JsonResponse({
                'success': False,
                'errors': {field: errors[0] for field, errors in form.errors.items()}
            })

    return JsonResponse({'success': False, 'error': 'Invalid request'})





@login_required
@never_cache
def apply_coupon(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'})
    
    try:
        data = json.loads(request.body)
        code = data.get('code', '').strip()
    except:
        code = request.POST.get('code', '').strip()
        
    if not code:
        return JsonResponse({'success': False, 'error': 'Please enter a coupon code'})
        
    cart, _ = Cart.objects.get_or_create(user=request.user)
    items = cart.items.all()
    if not items.exists():
        return JsonResponse({'success': False, 'error': 'Your cart is empty'})
        
    subtotal = sum(item.total_price for item in items)
    
    try:
        coupon = Coupon.objects.get(code__iexact=code)
    except Coupon.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Invalid coupon code'})
        
    # Check user-specific validity
    is_valid, error_message = coupon.is_valid_for_user(request.user)
    if not is_valid:
        return JsonResponse({'success': False, 'error': error_message})
        
    if subtotal < coupon.min_purchase_amount:
        return JsonResponse({'success': False, 'error': f'Minimum purchase of ₹{coupon.min_purchase_amount} required'})
        
    # Apply coupon to cart
    cart.coupon = coupon
    cart.save()
    
    # Recalculate to return new totals
    if subtotal == 0:
        shipping = Decimal('0.00')
    elif subtotal >= Decimal('5000.00'):
        shipping = Decimal('0.00')
    else:
        shipping = Decimal('49.00')
    
    discount = Decimal('0')
    if coupon.discount_type == 'percentage':
        discount = (subtotal * coupon.discount_value) / Decimal('100')
        if coupon.max_discount_amount:
            discount = min(discount, coupon.max_discount_amount)
    else:
        discount = coupon.discount_value
        
    taxable = max(Decimal('0'), subtotal - discount)
    tax = round(taxable * TAX_RATE, 2)
    total = taxable + tax + shipping
    
    return JsonResponse({
        'success': True,
        'message': f'Coupon {coupon.code} applied successfully!',
        'subtotal': str(subtotal),
        'discount': str(discount),
        'tax': str(tax),
        'shipping': str(shipping),
        'total': str(total)
    })

@login_required
@never_cache
def remove_coupon(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'})
        
    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart.coupon = None
    cart.save()
    
    # Recalculate
    items = cart.items.all()
    subtotal = sum(item.total_price for item in items) if items.exists() else Decimal('0')
    
    if subtotal == 0:
        shipping = Decimal('0.00')
    elif subtotal >= Decimal('5000.00'):
        shipping = Decimal('0.00')
    else:
        shipping = Decimal('49.00')
    
    tax = round(subtotal * TAX_RATE, 2)
    total = subtotal + tax + shipping
    
    return JsonResponse({
        'success': True,
        'message': 'Coupon removed successfully',
        'subtotal': str(subtotal),
        'discount': '0.00',
        'tax': str(tax),
        'shipping': str(shipping),
        'total': str(total)
    })
@login_required
@never_cache
def available_coupons(request):
    """View to list all available active coupons."""
    now = timezone.now()
    coupons = Coupon.objects.filter(
        is_active=True, 
        valid_from__lte=now, 
        valid_to__gte=now
    ).order_by('-discount_value')
    
    # Filter based on user-specific targeting rules
    valid_coupons = []
    for c in coupons:
        is_valid, _ = c.is_valid_for_user(request.user)
        if is_valid:
            valid_coupons.append(c)
    
    return render(request, 'available_coupons.html', {
        'active_coupons': valid_coupons
    })
