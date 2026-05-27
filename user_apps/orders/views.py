"""Order and checkout views."""

import json
import random
from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie

from admin_apps.offers.models import Coupon
from admin_apps.offers.services import get_referral_first_order_discount
from user_apps.core.models import (
    Cart, CartItem, Order, OrderItem, Product,
    Review, Wallet, WalletTransaction,
)
from user_apps.edit.models import Address

try:
    import razorpay
    RAZORPAY_CLIENT = razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )
except ImportError:
    RAZORPAY_CLIENT = None


SHIPPING_CHARGE = Decimal('49.00')
TAX_RATE = Decimal('0.03')  # 3% GST




def get_cart_totals(cart):
    """Calculate total cost components for a shopping cart."""
    items = cart.items.select_related('product', 'variant').all()
    subtotal = sum(item.total_price for item in items)

    # Free shipping on orders ≥ ₹5,000; flat ₹49 otherwise
    if subtotal == 0:
        shipping = Decimal('0.00')
    elif subtotal >= Decimal('5000.00'):
        shipping = Decimal('0.00')
    else:
        shipping = Decimal('49.00')

    discount = Decimal('0')

    # Apply coupon if one is attached and still valid
    if cart.coupon and cart.coupon.is_valid_for_user(cart.user)[0]:
        coupon = cart.coupon

        # Narrow down which items the coupon applies to
        if coupon.applicable_collection:
            collection_ids = coupon.applicable_collection.get_all_descendant_ids()
            applicable_items = [
                item for item in items
                if item.product.collection_id in collection_ids
            ]
        else:
            applicable_items = list(items)

        # Sort most expensive items first so the discount cap hits the right items
        applicable_items.sort(
            key=lambda x: (
                x.variant.display_price if x.variant else x.product.display_price
            ),
            reverse=True,
        )

        # Honour the per-coupon item count limit if one is set
        if coupon.max_items_count:
            discounted_subtotal = Decimal('0')
            remaining_limit = coupon.max_items_count
            for item in applicable_items:
                if remaining_limit <= 0:
                    break
                item_price = (
                    item.variant.display_price if item.variant
                    else item.product.display_price
                )
                take_qty = min(item.quantity, remaining_limit)
                discounted_subtotal += item_price * take_qty
                remaining_limit -= take_qty
            applicable_subtotal = discounted_subtotal
        else:
            applicable_subtotal = sum(item.total_price for item in applicable_items)

        if applicable_subtotal >= coupon.min_purchase_amount:
            if coupon.discount_type == 'percentage':
                discount = (applicable_subtotal * coupon.discount_value) / Decimal('100')
                if coupon.max_discount_amount:
                    discount = min(discount, coupon.max_discount_amount)
            else:
                discount = min(coupon.discount_value, applicable_subtotal)

    # Stack the referral first-order discount on top of any coupon saving
    referral_discount = get_referral_first_order_discount(cart.user, items=items)
    discount += referral_discount
    # Tax is 3% of the subtotal (after item-level offers)
    tax = round(subtotal * TAX_RATE, 2)
    total = subtotal - discount + tax + shipping

    return {
        'items': items,
        'subtotal': subtotal,
        'shipping': shipping,
        'tax': tax,
        'discount': discount,
        'total': total,
    }


def _build_coupon_discount(coupon, items, subtotal):
    """Calculate coupon discount for the current basket."""
    if coupon.applicable_collection:
        collection_ids = coupon.applicable_collection.get_all_descendant_ids()
        applicable_items = [
            item for item in items
            if item.product.collection_id in collection_ids
        ]
        if coupon.max_items_count:
            applicable_items.sort(
                key=lambda x: (
                    x.variant.display_price if x.variant else x.product.display_price
                ),
                reverse=True,
            )
            discounted_subtotal = Decimal('0')
            remaining_limit = coupon.max_items_count
            for item in applicable_items:
                if remaining_limit <= 0:
                    break
                item_price = (
                    item.variant.display_price if item.variant
                    else item.product.display_price
                )
                take_qty = min(item.quantity, remaining_limit)
                discounted_subtotal += item_price * take_qty
                remaining_limit -= take_qty
            applicable_subtotal = discounted_subtotal
        else:
            applicable_subtotal = sum(i.total_price for i in applicable_items)
    else:
        applicable_subtotal = subtotal

    if applicable_subtotal < coupon.min_purchase_amount:
        return Decimal('0'), applicable_subtotal

    if coupon.discount_type == 'percentage':
        coupon_discount = (applicable_subtotal * coupon.discount_value) / Decimal('100')
        if coupon.max_discount_amount:
            coupon_discount = min(coupon_discount, coupon.max_discount_amount)
    else:
        coupon_discount = min(coupon.discount_value, applicable_subtotal)

    return coupon_discount, applicable_subtotal




@never_cache
@ensure_csrf_cookie
def checkout_page(request):
    """Render checkout page and process order placement."""
    if not request.user.is_authenticated:
        return redirect('account_login')

    cart, _ = Cart.objects.get_or_create(user=request.user)

    # --- Resolve Buy Now session ---
    buy_now_id = request.GET.get('buy_now_id')
    if buy_now_id and buy_now_id.isdigit():
        request.session['buy_now_id'] = buy_now_id
    elif buy_now_id == 'undefined':
        # Defensive: explicitly clear if frontend sends "undefined"
        if 'buy_now_id' in request.session:
            del request.session['buy_now_id']
    elif 'buy_now_id' in request.session and not request.GET:
        # User arrived from the cart page — clear any lingering Buy Now state
        del request.session['buy_now_id']

    current_buy_now_id = request.session.get('buy_now_id')

    if current_buy_now_id and str(current_buy_now_id).isdigit():
        items = cart.items.filter(id=current_buy_now_id).select_related('product', 'variant')
        if not items.exists():
            if 'buy_now_id' in request.session:
                del request.session['buy_now_id']
            return redirect('cart_view')
    else:
        # Fallback for invalid or missing buy_now_id
        if 'buy_now_id' in request.session:
            del request.session['buy_now_id']
        items = cart.items.select_related('product', 'variant').all()

    if not items.exists():
        messages.warning(request, 'Your cart is empty. Add items before checking out.')
        return redirect('cart_view')

    # --- Availability check before showing the page ---
    for item in items:
        if not item.product.is_active:
            messages.error(request, f"Sorry, '{item.product.name}' is no longer available.")
            return redirect('cart_view')
        if item.variant and not item.variant.is_active:
            messages.error(
                request,
                f"Sorry, the selected variant for '{item.product.name}' is no longer available.",
            )
            return redirect('cart_view')
        
        available_stock = item.variant.stock if item.variant else item.product.stock
        if available_stock < item.quantity:
            messages.error(
                request,
                f"Sorry, only {available_stock} units of '{item.product.name}' are available."
            )
            return redirect('cart_view')

    # --- Price calculations ---
    # display_price already reflects any active product/category offers
    subtotal = sum(item.total_price for item in items)
    total_quantity = sum(item.quantity for item in items)



    # How much the customer saved from product-specific offers (display only)
    from django.utils import timezone as _tz
    _now = _tz.now()

    product_offer_savings = Decimal('0')
    category_offer_savings = Decimal('0')

    for item in items:
        base_price = (
            item.variant.effective_price
            if item.variant and item.variant.effective_price
            else item.product.price
        )

        discounted = (
            item.variant.display_price
            if item.variant and item.variant.display_price
            else item.product.display_price
        )
        saving_per_unit = max(Decimal('0'), base_price - discounted)
        if saving_per_unit > 0:
            # Determine whether the best offer is product-level or category-level
            p_off = item.product.product_offers.filter(
                is_active=True, valid_from__lte=_now, valid_to__gte=_now
            ).order_by('-discount_percentage').first()
            c_off = item.product.collection.category_offers.filter(
                is_active=True, valid_from__lte=_now, valid_to__gte=_now
            ).order_by('-discount_percentage').first() if item.product.collection else None
            p_disc = p_off.discount_percentage if p_off else 0
            c_disc = c_off.discount_percentage if c_off else 0
            if p_disc >= c_disc:
                product_offer_savings += saving_per_unit * item.quantity
            else:
                category_offer_savings += saving_per_unit * item.quantity

    offer_savings = product_offer_savings + category_offer_savings

    if subtotal == 0:
        shipping = Decimal('0.00')
    elif subtotal >= Decimal('5000.00'):
        shipping = Decimal('0.00')
    else:
        shipping = Decimal('49.00')

    # Validate and compute coupon discount
    coupon_discount = Decimal('0')
    if cart.coupon:
        is_valid, _ = cart.coupon.is_valid_for_user(request.user)
        if is_valid:
            coupon_discount, _ = _build_coupon_discount(cart.coupon, items, subtotal)
            if coupon_discount == 0:
                # Coupon no longer meets minimum — detach it
                cart.coupon = None
                cart.save()
        else:
            cart.coupon = None
            cart.save()

    referral_discount = get_referral_first_order_discount(request.user, items=items)
    discount = coupon_discount + referral_discount

    # Tax is calculated on subtotal (after item offers)
    tax = round(subtotal * TAX_RATE, 2)
    total = subtotal - discount + tax + shipping

    addresses = Address.objects.filter(user=request.user)
    default_address = addresses.filter(is_default=True).first() or addresses.first()

    # Shared context for both GET render and error re-renders on POST
    total_saved = offer_savings + coupon_discount + referral_discount
    render_ctx = {
        'items': items,
        'subtotal': subtotal,
        'tax': tax,
        'shipping': shipping,
        'discount': discount,
        'total': total,
        'coupon_discount': coupon_discount,
        'referral_discount': referral_discount,
        'offer_savings': offer_savings,
        'product_offer_savings': product_offer_savings,
        'category_offer_savings': category_offer_savings,
        'total_saved': total_saved,
        'cart': cart,
        'addresses': addresses,
        'default_address': default_address,
        'total_quantity': total_quantity,
    }

    # ------------------------------------------------------------------
    # POST — place the order
    # ------------------------------------------------------------------
    if request.method == 'POST':
        address_id = request.POST.get('address_id')
        payment_method = request.POST.get('payment_method', 'cod')
        # Validate COD for high subtotal
        if payment_method == 'cod' and subtotal > 30000:
            messages.error(request, "Sorry, COD payment is not allowed for orders exceeding ₹20,000.")
            return render(request, 'checkout_page.html', render_ctx)

        if payment_method not in ['cod', 'wallet', 'razorpay']:
            messages.error(request, 'Invalid payment method selected.')
            return render(request, 'checkout_page.html', render_ctx)

        if not address_id:
            messages.error(request, 'Please select a delivery address.')
            return render(request, 'checkout_page.html', render_ctx)

        address = get_object_or_404(Address, id=address_id, user=request.user)

        # Snapshot the address at order time so future edits don't affect it
        address_data = {
            'full_name': address.full_name,
            'street': address.street,
            'city': address.city,
            'state': address.state,
            'postal_code': address.postal_code,
            'country': address.country,
            'phone': address.phone,
        }

        try:
            with transaction.atomic():
                estimated_delivery_date = (
                    timezone.now() + timedelta(days=random.randint(3, 7))
                ).date()

                # Deduct wallet balance upfront; roll back on any later failure
                if payment_method == 'wallet':
                    wallet, _ = Wallet.objects.get_or_create(user=request.user)
                    if wallet.balance < total:
                        raise Exception('Insufficient wallet balance.')
                    wallet.balance -= total
                    wallet.save()

                order = Order.objects.create(
                    user=request.user,
                    address_snapshot=json.dumps(address_data),
                    payment_method=payment_method,
                    subtotal=subtotal,
                    tax=tax,
                    shipping_charge=shipping,
                    offer_discount=offer_savings,
                    discount=discount,
                    total_amount=total,
                    status='Pending',
                    is_paid=(payment_method == 'wallet'),
                    scheduled_delivery_date=estimated_delivery_date,
                    coupon_code=cart.coupon.code if cart.coupon else None,
                )

                if payment_method == 'wallet':
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        transaction_type='Debit',
                        amount=total,
                        description=f'Payment for Order #{order.id}',
                    )

                if cart.coupon:
                    cart.coupon.used_count += 1
                    cart.coupon.save()

                # Create order items and decrement stock
                for item in items:
                    if not item.product.is_active or (
                        item.variant and not item.variant.is_active
                    ):
                        raise Exception(f"'{item.product.name}' is not available now ")

                    available_stock = (
                        item.variant.stock if item.variant else item.product.stock
                    )
                    if available_stock < item.quantity:
                        raise Exception(
                            f"Sorry, only {available_stock} units of "
                            f"{item.product.name} are available."
                        )

                    price_at_purchase = (
                        item.variant.display_price if item.variant
                        else item.product.display_price
                    )

                    OrderItem.objects.create(
                        order=order,
                        product=item.product,
                        variant=item.variant,
                        quantity=item.quantity,
                        price=price_at_purchase,
                    )

                    if item.variant:
                        item.variant.stock -= item.quantity
                        item.variant.save()
                    else:
                        item.product.stock -= item.quantity
                        item.product.save()

                # Remove ordered items from the cart only for non-Razorpay payments
                # Razorpay items are cleared in verify_payment after success
                if payment_method != 'razorpay':
                    items.delete()
                if current_buy_now_id:
                    del request.session['buy_now_id']

            if payment_method == 'razorpay':
                return redirect('payments:start_payment', order_id=order.id)

            return redirect('order_success', order_uuid=order.uuid)

        except Exception as e:
            messages.error(request, str(e))
            return render(request, 'checkout_page.html', render_ctx)

    # ------------------------------------------------------------------
    # GET — render the checkout page
    # ------------------------------------------------------------------
    estimated_delivery = timezone.now() + timedelta(days=random.randint(1, 7))

    now = timezone.now()
    active_coupons = Coupon.objects.filter(
        is_active=True, valid_from__lte=now, valid_to__gte=now
    )
    active_coupons = [c for c in active_coupons if c.is_valid]

    return render(request, 'checkout_page.html', {
        **render_ctx,
        'estimated_delivery': estimated_delivery,
        'active_coupons': active_coupons,
        'is_buy_now': bool(current_buy_now_id),
    })




@login_required
@never_cache
def order_success(request, order_uuid):
    """Show post-checkout confirmation screen."""
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
    """List all orders for the current user."""
    orders = (
        Order.objects.filter(user=request.user)
        .prefetch_related('items__product')
        .order_by('-created_at')
    )

    query = request.GET.get('q', '').strip()
    if query:
        orders = orders.filter(
            Q(id__icontains=query) | Q(items__product__name__icontains=query)
        ).distinct()

    return render(request, 'order_history.html', {'orders': orders, 'query': query})


@login_required
def order_detail(request, order_uuid):
    """Show full details of a single order."""
    if request.user.is_staff or request.user.is_superuser:
        order = get_object_or_404(Order, uuid=order_uuid)
    else:
        order = get_object_or_404(Order, uuid=order_uuid, user=request.user)

    items = order.items.select_related('product').all()

    address = {}
    try:
        address = json.loads(order.address_snapshot)
    except Exception:
        pass

    # Keep totals accurate for in-flight orders
    if order.status in ['Pending', 'Processing', 'Shipped']:
        order.update_totals()

    reviewed_product_ids = set()
    if request.user.is_authenticated:
        reviewed_product_ids = set(
            Review.objects.filter(
                user=request.user,
                product__in=[item.product for item in items],
            ).values_list('product_id', flat=True)
        )

    from datetime import datetime
    from decimal import Decimal

    # Pre-calculate online payment discount for COD unpaid orders
    online_discount = Decimal('0')
    online_payment_total = order.total_amount
    if order.payment_method == 'cod' and not order.is_paid and order.status in ['Pending', 'Confirmed', 'Processing']:
        online_discount = round(order.total_amount * Decimal('0.05'), 2)
        online_payment_total = max(Decimal('0'), order.total_amount - online_discount)

    return render(request, 'order_detail.html', {
        'order': order,
        'items': items,
        'address': address,
        'reviewed_product_ids': reviewed_product_ids,
        'today': datetime.now(),
        'online_discount': online_discount,
        'online_payment_total': online_payment_total,
    })




@login_required
def cancel_order(request, order_uuid):
    """Cancel an entire order and restore stock."""
    order = get_object_or_404(Order, uuid=order_uuid, user=request.user)

    if request.method == 'GET':
        if order.status not in ['Pending', 'Processing']:
            messages.error(request, 'This order cannot be cancelled')
            return redirect('order_detail', order_uuid=order.uuid)
        return render(request, 'cancel.html', {'order': order})

    if request.method == 'POST' and order.status in ['Pending', 'Confirmed', 'Processing']:
        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, 'Please provide a reason for cancellation.')
            return redirect('order_detail', order_uuid=order.uuid)

        with transaction.atomic():
            original_total = order.total_amount

            order.status = 'Cancelled'
            order.cancel_reason = reason
            order.save()

            # Restore stock for every non-cancelled item
            for item in order.items.filter(is_cancelled=False):
                if item.variant:
                    item.variant.stock += item.quantity
                    item.variant.save()
                    # Sync product-level stock aggregate
                    p = item.variant.product
                    p.stock = p.variants.filter(is_active=True).aggregate(Sum('stock'))['stock__sum'] or 0
                    p.save(update_fields=['stock'])
                else:
                    product = item.product
                    product.stock += item.quantity
                    product.save()
                item.is_cancelled = True
                item.cancel_reason = 'Order cancelled'
                item.save()

            order.update_totals()

            # Refund to wallet for pre-paid orders
            if order.is_paid:
                wallet, _ = Wallet.objects.get_or_create(user=request.user)
                wallet.balance += original_total
                wallet.save()
                WalletTransaction.objects.create(
                    wallet=wallet,
                    transaction_type='Credit',
                    amount=original_total,
                    description=f'Refund for cancelled Order #{order.id}',
                )

        messages.success(request, f'Order #{order.id} has been cancelled.')
    else:
        messages.error(request, 'This order cannot be cancelled.')

    return redirect('order_detail', order_uuid=order.uuid)


@login_required
def cancel_order_item(request, item_uuid):
    """Cancel a single item within an order."""
    if request.method != 'POST':
        return redirect('order_history')

    item = get_object_or_404(OrderItem, uuid=item_uuid, order__user=request.user)
    order = item.order

    if order.status in ['Pending', 'Confirmed', 'Processing'] and not item.is_cancelled:
        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, 'Please provide a reason for cancellation.')
            return redirect('order_detail', order_uuid=order.uuid)

        with transaction.atomic():
            # Capture values before any mutation for refund calculation
            item_subtotal = item.price * item.quantity
            original_order_subtotal = order.subtotal

            item.is_cancelled = True
            item.cancel_reason = reason
            item.save()

            if item.variant:
                item.variant.stock += item.quantity
                item.variant.save()
                # Sync product-level stock aggregate
                p = item.variant.product
                p.stock = p.variants.filter(is_active=True).aggregate(Sum('stock'))['stock__sum'] or 0
                p.save(update_fields=['stock'])
            else:
                product = item.product
                product.stock += item.quantity
                product.save()

            order.update_totals()

            # Refund: prorate discount to avoid zero-refund when coupon absorbs full subtotal
            if order.is_paid:
                if original_order_subtotal > 0:
                    item_discount_share = (item_subtotal / original_order_subtotal) * order.discount
                else:
                    item_discount_share = Decimal('0')
                item_taxable = max(Decimal('0'), item_subtotal - item_discount_share)
                item_tax = (item_taxable * Decimal('0.03')).quantize(Decimal('0.01'))
                refund_amount = item_taxable + item_tax
                if refund_amount > 0:
                    wallet, _ = Wallet.objects.get_or_create(user=request.user)
                    wallet.balance += refund_amount
                    wallet.save()
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        transaction_type='Credit',
                        amount=refund_amount,
                        description=f'Refund for cancelled item in Order #{order.id}',
                    )

        messages.success(request, f'Item "{item.product.name}" has been cancelled.')
    else:
        messages.error(request, 'This item cannot be cancelled.')

    return redirect('order_detail', order_uuid=order.uuid)




@login_required
def return_order(request, order_uuid):
    """Submit a return request for order items."""
    if request.method != 'POST':
        return redirect('order_history')

    order = get_object_or_404(Order, uuid=order_uuid, user=request.user)

    if order.status != 'Delivered':
        messages.error(request, 'This order is not eligible for return.')
        return redirect('order_detail', order_uuid=order.uuid)

    item_ids = request.POST.getlist('item_ids')
    reason = request.POST.get('reason')

    if not reason:
        messages.error(request, 'Please provide a reason for the return.')
        return redirect('order_detail', order_uuid=order.uuid)

    if not item_ids:
        messages.error(request, 'Please select at least one item to return.')
        return redirect('order_detail', order_uuid=order.uuid)

    with transaction.atomic():
        items_to_return = order.items.filter(
            id__in=item_ids, is_returned=False, is_cancelled=False
        )
        if not items_to_return.exists():
            messages.error(request, 'Selected items are not eligible for return.')
            return redirect('order_detail', order_uuid=order.uuid)

        for item in items_to_return:
            item.is_returned = True
            item.return_reason = reason
            item.save()

        remaining = order.items.filter(is_cancelled=False, is_returned=False)
        if not remaining.exists():
            # All items are being returned — full return request
            order.status = 'Return Requested'
            order.return_status = 'Requested'
            order.return_reason = reason
            order.save()
        else:
            # Partial return
            order.return_status = 'Requested'
            if not order.return_reason:
                order.return_reason = f"Partial Return: {reason}"
            order.save()

    messages.success(request, 'Return request for selected items submitted successfully.')
    return redirect('order_detail', order_uuid=order.uuid)




@login_required
def download_invoice(request, order_uuid):
    """Render a printable invoice for an order."""
    order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
    
    # Filter out cancelled and returned items (if return is completed)
    if order.return_status == 'Returned':
        items = order.items.filter(is_cancelled=False, is_returned=False)
    else:
        items = order.items.filter(is_cancelled=False)

    address = {}
    try:
        address = json.loads(order.address_snapshot)
    except Exception:
        pass

    # Update totals to reflect current state (especially if returned)
    if order.status in ['Pending', 'Processing', 'Shipped', 'Returned']:
        order.update_totals()

    return render(request, 'invoice.html', {
        'order': order,
        'items': items,
        'address': address,
    })




@login_required
def reschedule_order(request, order_uuid):
    """Request a delivery date or time change."""
    order = get_object_or_404(Order, uuid=order_uuid, user=request.user)

    if order.status not in ['Pending', 'Processing']:
        messages.error(
            request,
            f"Order cannot be rescheduled as it is currently {order.status}.",
        )
        return redirect('order_detail', order_uuid=order.uuid)

    if order.reschedule_count >= 1:
        messages.error(
            request,
            "This order has already been successfully rescheduled once and cannot be changed again.",
        )
        return redirect('order_detail', order_uuid=order.uuid)

    if order.reschedule_status == 'Pending':
        messages.error(request, "A reschedule request is already pending for this order.")
        return redirect('order_detail', order_uuid=order.uuid)

    if order.reschedule_status == 'Rejected':
        messages.error(
            request,
            "Your previous reschedule request was declined and cannot be resubmitted for this order.",
        )
        return redirect('order_detail', order_uuid=order.uuid)

    if request.method == 'GET':
        from datetime import datetime
        return render(request, 'Rq_reschedule.html', {
            'order': order,
            'today': datetime.now(),
        })

    if request.method == 'POST':
        new_date = request.POST.get('scheduled_date')
        new_time = request.POST.get('scheduled_time')
        reason = request.POST.get('reschedule_reason', '').strip()

        if not (reason and len(reason) >= 8):
            messages.error(request, "A valid and detailed reason is required to reschedule.")
            return redirect('order_detail', order_uuid=order.uuid)

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
            messages.success(
                request,
                f"Reschedule request for "
                f"{display_date.strftime('%B %d, %Y') if display_date else 'delivery'} submitted.",
            )
        except ValueError:
            messages.error(request, "Invalid date or time format.")

        return redirect('order_detail', order_uuid=order.uuid)

    return redirect('order_history')




@login_required
def track_order(request, order_uuid):
    """Display live tracking view for an order."""
    from django.shortcuts import get_object_or_404

    if request.user.is_staff or request.user.is_superuser:
        order = get_object_or_404(Order, uuid=order_uuid)
    else:
        order = get_object_or_404(Order, uuid=order_uuid, user=request.user)

    items = order.items.select_related('product').all()

    address = {}
    try:
        address = json.loads(order.address_snapshot)
    except Exception:
        pass

    return render(request, 'track_order.html', {
        'order': order,
        'items': items,
        'address': address,
    })




@login_required
def add_address(request):
    """Create a new address from checkout."""
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
                },
            })
        else:
            return JsonResponse({
                'success': False,
                'errors': {field: errors[0] for field, errors in form.errors.items()},
            })

    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required
def edit_address(request, address_uuid):
    """Update an existing address from checkout."""
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
                },
            })
        else:
            return JsonResponse({
                'success': False,
                'errors': {field: errors[0] for field, errors in form.errors.items()},
            })

    return JsonResponse({'success': False, 'error': 'Invalid request'})




@login_required
@never_cache
def apply_coupon(request):
    """Validate and apply a coupon to the cart."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'})

    try:
        data = json.loads(request.body)
        code = data.get('code', '').strip()
    except Exception:
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

    is_valid, error_message = coupon.is_valid_for_user(request.user)
    if not is_valid:
        return JsonResponse({'success': False, 'error': error_message})

    # Determine applicable items and their total
    if coupon.applicable_collection:
        collection_ids = coupon.applicable_collection.get_all_descendant_ids()
        applicable_items_list = [
            item for item in items
            if item.product.collection_id in collection_ids
        ]
    else:
        applicable_items_list = list(items)

    applicable_items_list.sort(
        key=lambda x: (
            x.variant.display_price if x.variant else x.product.display_price
        ),
        reverse=True,
    )

    if coupon.max_items_count:
        applicable_subtotal = Decimal('0')
        remaining_limit = coupon.max_items_count
        for item in applicable_items_list:
            if remaining_limit <= 0:
                break
            item_price = (
                item.variant.display_price if item.variant
                else item.product.display_price
            )
            take_qty = min(item.quantity, remaining_limit)
            applicable_subtotal += item_price * take_qty
            remaining_limit -= take_qty
    else:
        applicable_subtotal = sum(item.total_price for item in applicable_items_list)

    if applicable_subtotal < coupon.min_purchase_amount:
        return JsonResponse({
            'success': False,
            'error': f'Minimum purchase of ₹{coupon.min_purchase_amount} required for matching items',
        })

    cart.coupon = coupon
    cart.save()

    # Shipping
    if subtotal == 0:
        shipping = Decimal('0.00')
    elif subtotal >= Decimal('5000.00'):
        shipping = Decimal('0.00')
    else:
        shipping = Decimal('49.00')

    # 1. Coupon Discount
    if coupon.discount_type == 'percentage':
        coupon_discount = (applicable_subtotal * coupon.discount_value) / Decimal('100')
        if coupon.max_discount_amount:
            coupon_discount = min(coupon_discount, coupon.max_discount_amount)
    else:
        coupon_discount = min(coupon.discount_value, applicable_subtotal)

    # 2. Referral Discount (Must stack)
    referral_discount = get_referral_first_order_discount(request.user, items=items)
    
    total_discount = coupon_discount + referral_discount

    # Tax is calculated on subtotal (after item offers)
    tax = round(subtotal * TAX_RATE, 2)
    total = subtotal - total_discount + tax + shipping

    # Calculate offer savings for AJAX response
    offer_savings = Decimal('0')
    for item in items:
        base = item.variant.effective_price if item.variant else item.product.price
        disc = item.variant.display_price if item.variant else item.product.display_price
        offer_savings += max(Decimal('0'), base - disc) * item.quantity

    return JsonResponse({
        'success': True,
        'message': f'Coupon {coupon.code} applied successfully!',
        'subtotal': str(subtotal),
        'discount': str(coupon_discount),
        'referral_discount': str(referral_discount),
        'offer_savings': str(offer_savings),
        'tax': str(tax),
        'shipping': str(shipping),
        'total': str(total),
    })


@login_required
@never_cache
def remove_coupon(request):
    """Remove coupon from the active cart."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'})

    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart.coupon = None
    cart.save()

    items = cart.items.all()
    subtotal = sum(item.total_price for item in items) if items.exists() else Decimal('0')

    if subtotal == 0:
        shipping = Decimal('0.00')
    elif subtotal >= Decimal('5000.00'):
        shipping = Decimal('0.00')
    else:
        shipping = Decimal('49.00')

    # Referral Discount remains even if coupon is removed
    referral_discount = get_referral_first_order_discount(request.user, items=items)

    # Tax is calculated on subtotal (after item offers)
    tax = round(subtotal * TAX_RATE, 2)
    total = subtotal - referral_discount + tax + shipping

    # Calculate offer savings for AJAX response
    offer_savings = Decimal('0')
    for item in items:
        base = item.variant.effective_price if item.variant else item.product.price
        disc = item.variant.display_price if item.variant else item.product.display_price
        offer_savings += max(Decimal('0'), base - disc) * item.quantity

    return JsonResponse({
        'success': True,
        'message': 'Coupon removed successfully',
        'subtotal': str(subtotal),
        'discount': '0.00',
        'referral_discount': str(referral_discount),
        'offer_savings': str(offer_savings),
        'tax': str(tax),
        'shipping': str(shipping),
        'total': str(total),
    })




@login_required
def submit_review(request):
    """Submit a product rating and review."""
    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        order_id = request.POST.get('order_id')
        rating = request.POST.get('rating', 5)
        comment = request.POST.get('comment', '').strip()

        product = get_object_or_404(Product, id=product_id)

        has_purchased = OrderItem.objects.filter(
            order__user=request.user,
            order__status='Delivered',
            product=product,
        ).exists()

        if not has_purchased:
            messages.error(
                request,
                "You can only review products you have purchased and received.",
            )
            return redirect('order_history')

        if Review.objects.filter(user=request.user, product=product).exists():
            messages.error(request, "A user can submit only one review and rating per product.")
        else:
            Review.objects.create(
                product=product,
                user=request.user,
                rating=int(rating),
                comment=comment,
            )
            messages.success(request, f"Thank you for reviewing {product.name}!")

        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
        elif order_id:
            order = Order.objects.filter(id=order_id).first()
            if order:
                return redirect('order_detail', order_uuid=order.uuid)

    return redirect('order_history')




@login_required
@never_cache
def available_coupons(request):
    """List eligible active coupons."""
    now = timezone.now()
    coupons = Coupon.objects.filter(
        is_active=True,
        valid_from__lte=now,
        valid_to__gte=now,
    ).order_by('-discount_value')

    valid_coupons = [c for c in coupons if c.is_valid_for_user(request.user)[0]]

    return render(request, 'available_coupons.html', {'active_coupons': valid_coupons})
