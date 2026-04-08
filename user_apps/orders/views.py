import json
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.http import JsonResponse
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from user_apps.core.models import Cart, CartItem, Order, OrderItem, Product
from user_apps.edit.models import Address


SHIPPING_CHARGE = Decimal('99.00')
TAX_RATE = Decimal('0.05')  # 5% GST


@login_required
@never_cache
def checkout_page(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    items = cart.items.select_related('product').all()

    if not items.exists():
        messages.warning(request, 'Your cart is empty. Add items before checking out.')
        return redirect('cart_view')

    subtotal = sum(item.total_price for item in items)
    tax = round(subtotal * TAX_RATE, 2)
    shipping = SHIPPING_CHARGE if subtotal < Decimal('5000') else Decimal('0')
    total = subtotal + tax + shipping

    addresses = Address.objects.filter(user=request.user)
    default_address = addresses.filter(is_default=True).first() or addresses.first()

    if request.method == 'POST':
        address_id = request.POST.get('address_id')
        payment_method = request.POST.get('payment_method', 'cod')

        if not address_id:
            messages.error(request, 'Please select a delivery address.')
            return render(request, 'checkout_page.html', {
                'items': items, 'subtotal': subtotal, 'tax': tax,
                'shipping': shipping, 'total': total,
                'addresses': addresses, 'default_address': default_address,
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
            order = Order.objects.create(
                user=request.user,
                address_snapshot=json.dumps(address_data),
                payment_method=payment_method,
                subtotal=subtotal,
                tax=tax,
                shipping_charge=shipping,
                discount=Decimal('0'),
                total_amount=total,
                status='Pending',
            )

            for item in items:
                # Check stock before creating order item
                if item.product.stock < item.quantity:
                    messages.error(request, f"Sorry, only {item.product.stock} units of {item.product.name} are available.")
                    raise Exception("Insufficient stock")

                price_at_purchase = item.product.discount_price if item.product.discount_price else item.product.price
                OrderItem.objects.create(
                    order=order,
                    product=item.product,
                    quantity=item.quantity,
                    price=price_at_purchase,
                )
                
                # Decrement Stock
                item.product.stock -= item.quantity
                item.product.save()

        # Clear cart
        cart.items.all().delete()

        return redirect('order_success', order_id=order.id)

    return render(request, 'checkout_page.html', {
        'items': items,
        'subtotal': subtotal,
        'tax': tax,
        'shipping': shipping,
        'total': total,
        'addresses': addresses,
        'default_address': default_address,
    })


@login_required
@never_cache
def order_success(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
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
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    items = order.items.select_related('product').all()
    try:
        address = json.loads(order.address_snapshot)
    except:
        address = {}
    
    from datetime import datetime
    return render(request, 'order_detail.html', {
        'order': order,
        'items': items,
        'address': address,
        'today': datetime.now()
    })


@login_required
def cancel_order(request, order_id):
    if request.method != 'POST':
        return redirect('order_history')
        
    order = get_object_or_404(Order, id=order_id, user=request.user)
    
    if order.status in ['Pending', 'Processing']:
        reason = request.POST.get('reason', 'User cancelled')
        with transaction.atomic():
            order.status = 'Cancelled'
            order.cancel_reason = reason
            order.save()
            
            # Increment Stock
            for item in order.items.filter(is_cancelled=False):
                product = item.product
                product.stock += item.quantity
                product.save()
                item.is_cancelled = True
                item.cancel_reason = 'Order cancelled'
                item.save()
                
        messages.success(request, f'Order #{order.id} has been cancelled.')
    else:
        messages.error(request, 'This order cannot be cancelled.')
        
    return redirect('order_history')


@login_required
def cancel_order_item(request, item_id):
    if request.method != 'POST':
        return redirect('order_history')
        
    item = get_object_or_404(OrderItem, id=item_id, order__user=request.user)
    order = item.order
    
    if order.status in ['Pending', 'Processing'] and not item.is_cancelled:
        reason = request.POST.get('reason', 'User cancelled')
        with transaction.atomic():
            item.is_cancelled = True
            item.cancel_reason = reason
            item.save()
            
            # Increment Stock
            product = item.product
            product.stock += item.quantity
            product.save()
            
            # If all items are cancelled, cancel the order
            if not order.items.filter(is_cancelled=False).exists():
                order.status = 'Cancelled'
                order.cancel_reason = 'All items cancelled'
                order.save()
                
        messages.success(request, f'Item "{item.product.name}" has been cancelled.')
    else:
        messages.error(request, 'This item cannot be cancelled.')
        
    return redirect('order_detail', order_id=order.id)


@login_required
def return_order(request, order_id):
    if request.method != 'POST':
        return redirect('order_history')
        
    order = get_object_or_404(Order, id=order_id, user=request.user)
    
    if order.status == 'Delivered':
        reason = request.POST.get('reason')
        if not reason:
            messages.error(request, 'Please provide a reason for the return.')
            return redirect('order_detail', order_id=order.id)
            
        order.status = 'Return Requested'
        order.return_reason = reason
        order.save()
        messages.success(request, 'Return request submitted successfully.')
    else:
        messages.error(request, 'This order is not eligible for return.')
        
    return redirect('order_history')


@login_required
def download_invoice(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    items = order.items.filter(is_cancelled=False)
    try:
        address = json.loads(order.address_snapshot)
    except:
        address = {}
        
    return render(request, 'invoice.html', {
        'order': order,
        'items': items,
        'address': address
    })

@login_required
def reschedule_order(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id, user=request.user)
        
        # Only allow rescheduling if Pending or Processing
        if order.status not in ['Pending', 'Processing']:
            messages.error(request, f"Order cannot be rescheduled as it is currently {order.status}.")
            return redirect('order_detail', order_id=order.id)
            
        new_date = request.POST.get('scheduled_date')
        if new_date:
            from datetime import datetime
            try:
                date_obj = datetime.strptime(new_date, '%Y-%m-%d').date()
                if date_obj < datetime.now().date():
                    messages.error(request, "Delivery date cannot be in the past.")
                else:
                    order.scheduled_delivery_date = date_obj
                    order.save()
                    messages.success(request, f"Delivery rescheduled to {date_obj.strftime('%B %d, %Y')}.")
            except ValueError:
                messages.error(request, "Invalid date format.")
        
        return redirect('order_detail', order_id=order.id)
    return redirect('order_history')


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
                    'id': address.id,
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
def edit_address(request, id):
    """AJAX endpoint to edit an address from checkout page."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = request.POST
            
        address = get_object_or_404(Address, id=id, user=request.user)

        from user_apps.edit.forms import AddressForm
        form = AddressForm(data, instance=address)
        
        if form.is_valid():
            updated_address = form.save(commit=False)
            # Default keeps its old value because the form doesn't handle is_default 
            updated_address.save()

            return JsonResponse({
                'success': True,
                'address': {
                    'id': updated_address.id,
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
