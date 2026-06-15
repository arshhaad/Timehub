"""Admin Order Management Views."""

import json
import csv
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, Avg, F
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncYear
from django.http import JsonResponse, HttpResponse
from django.contrib.auth import get_user_model

from user_apps.core.models import (
    Order, Product, ProductVariant, OrderItem,
    Collection, Wallet, WalletTransaction
)
from seller.models import Seller, SellerEarnings
from admin_apps.offers.services import process_referrer_reward

# Standard Django User model
User = get_user_model()




@login_required
def order_list(request):
    """List all orders with filtering and sorting."""
    orders = Order.objects.select_related('user').order_by('-created_at')

    # Search
    query = request.GET.get('q', '').strip()
    if query:
        search_filter = (
            Q(user__email__icontains=query) |
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query)
        )
        # Search by order ID if search query is numeric
        if query.isdigit():
            search_filter |= Q(id=query)
        orders = orders.filter(search_filter)

    # Status filter
    status_filter = request.GET.get('status', 'all')
    if status_filter and status_filter != 'all':
        orders = orders.filter(status=status_filter)

    # Sorting
    sort = request.GET.get('sort', 'newest')
    sort_map = {
        'oldest': 'created_at',
        'amount_high': '-total_amount',
        'amount_low': 'total_amount',
        'newest': '-created_at'
    }
    orders = orders.order_by(sort_map.get(sort, '-created_at'))

    # Pagination
    paginator = Paginator(orders, 10)
    page_number = request.GET.get('page', 1)
    orders_page = paginator.get_page(page_number)

    context = {
        'orders': orders_page,
        'query': query,
        'status_filter': status_filter,
        'sort': sort,
        'active_menu': 'orders',
        'status_choices': Order.STATUS_CHOICES,
    }
    return render(request, 'order_manage/order_list.html', context)


@login_required
def order_detail(request, order_id):
    """View order details and manage status transitions."""
    order = get_object_or_404(
        Order.objects.select_related('user').prefetch_related('items__product'),
        id=order_id
    )

    address = {}
    try:
        address = json.loads(order.address_snapshot)
    except Exception:
        address = {}
        
    # Recalculate totals for active orders
    if order.status in ['Pending', 'Processing', 'Shipped']:
        order.update_totals()

    if request.method == 'POST':
        new_status = request.POST.get('status')
        new_return_status = request.POST.get('return_status')
        new_date = request.POST.get('scheduled_delivery_date')
        
        valid_statuses = [s[0] for s in Order.STATUS_CHOICES]
        
        # Allowed transitions map
        ALLOWED_TRANSITIONS = {
            'Pending': ['Confirmed', 'Cancelled', 'Processing'],
            'Confirmed': ['Processing', 'Shipped', 'Cancelled'],
            'Processing': ['Confirmed', 'Shipped', 'Cancelled'],
            'Shipped': ['Processing', 'Out for Delivery', 'Cancelled'],
            'Out for Delivery': ['Shipped', 'Delivered', 'Cancelled'],
            'Delivered': ['Return Requested', 'Returned'],
            'Return Requested': ['Returned', 'Delivered'],
            'Cancelled': [],
            'Returned': [],
        }

        if new_status in valid_statuses:
            # Validate transition
            current_status = order.status
            if new_status != current_status:
                allowed_next = ALLOWED_TRANSITIONS.get(current_status, [])
                if new_status not in allowed_next:
                    messages.error(request, f"Invalid transition: Cannot move from {current_status} to {new_status}.")
                    return redirect('admin_order_detail', order_id=order.id)
                
                # Check if return request was actually made
                if new_status in ['Returned', 'Return Requested'] and order.return_status == 'None':
                    messages.error(request, f"Cannot change status to {new_status}: No return request has been submitted for this order.")
                    return redirect('admin_order_detail', order_id=order.id)

            # 2. Legacy Return Logic (Fallback)
            if new_status == 'Returned' and order.status != 'Returned':
                if order.return_status == 'None':
                    messages.error(request, "Cannot mark order as Returned: No return request has been submitted for this order.")
                    return redirect('admin_order_detail', order_id=order.id)
                process_full_return(order, request.POST.get('refund_method'))
            
            # Update status
            order.status = new_status
            
            # Seller earnings on delivery
            if new_status == 'Delivered':
                for item in order.items.filter(is_cancelled=False, product__seller__isnull=False):
                    SellerEarnings.objects.get_or_create(
                        seller=item.product.seller,
                        order_item=item,
                        defaults={'amount': item.price * item.quantity}
                    )
            
            # Detailed return flow management
            if new_return_status and new_return_status in [c[0] for c in Order.RETURN_CHOICES]:
                current_return_status = order.return_status
                
                # Stages for return flow
                RETURN_FLOW = {
                    'None': [],
                    'Requested': ['Processing'],
                    'Processing': ['Pickup Scheduled', 'Rejected'],
                    'Pickup Scheduled': ['Returned', 'Rejected'],
                    'Returned': [],
                    'Rejected': [],
                }
                
                if new_return_status != current_return_status:
                    allowed_next_stages = RETURN_FLOW.get(current_return_status, [])
                    if new_return_status not in allowed_next_stages:
                        messages.error(request, f"Invalid stage: Cannot move return from {current_return_status} to {new_return_status}.")
                        return redirect('admin_order_detail', order_id=order.id)
                    
                    # Sync return stage with order status
                    if new_return_status == 'Rejected':
                        order.status = 'Delivered'
                        order.return_status = 'Rejected'
                    elif new_return_status == 'Returned':
                        if order.status != 'Returned':
                            order.status = 'Returned'
                            process_full_return(order, request.POST.get('refund_method') or 'Wallet')
                        order.return_status = 'Returned'
                    else:
                        order.return_status = new_return_status
                        if order.status == 'Delivered':
                            order.status = 'Return Requested'
            
            # Update delivery date
            if new_date:
                order.scheduled_delivery_date = new_date
            elif new_date == '':
                order.scheduled_delivery_date = None
                
            order.save()
            messages.success(request, f'Order #{order.id} updated successfully.')
        else:
            messages.error(request, 'Invalid status selection.')
        return redirect('admin_order_detail', order_id=order.id)

    timeline_steps = [
        ('Pending', 'Order received'),
        ('Processing', 'Being prepared'),
        ('Shipped', 'On the way'),
        ('Out for Delivery', 'Out for delivery'),
        ('Delivered', 'Delivered to customer'),
    ]

    ALLOWED_TRANSITIONS = {
        'Pending': ['Confirmed', 'Cancelled', 'Processing'],
        'Confirmed': ['Shipped', 'Cancelled', 'Processing'],
        'Processing': ['Shipped', 'Cancelled'],
        'Shipped': ['Out for Delivery'],
        'Out for Delivery': ['Delivered'],
        'Delivered': ['Return Requested', 'Returned'],
        'Return Requested': ['Returned', 'Delivered'],
        'Cancelled': [],
        'Returned': [],
    }
    
    allowed_next = ALLOWED_TRANSITIONS.get(order.status, [])
    if order.return_status == 'None':
        allowed_next = [s for s in allowed_next if s not in ['Returned', 'Return Requested']]
    
    allowed_statuses = [s for s in Order.STATUS_CHOICES if s[0] == order.status or s[0] in allowed_next]

    context = {
        'order': order,
        'address': address,
        'active_menu': 'orders',
        'status_choices': allowed_statuses,
        'return_status_choices': Order.RETURN_CHOICES,
        'timeline_steps': timeline_steps,
    }
    return render(request, 'order_manage/user_order_detail.html', context)




def process_full_return(order, refund_method):
    if order.refund_processed_at:
        return
        
    original_total = order.total_amount
    
    if order.status == 'Returned' or order.return_status == 'Returned':
        if order.status == 'Returned':
            order.return_status = 'Returned'
        
        if not order.items.filter(is_returned=True).exists():
            order.items.filter(is_cancelled=False).update(is_returned=True)

    order.update_totals()
    refund_amount = original_total - order.total_amount
    
    if refund_amount > 0:
        order.is_paid = True
        wallet, _ = Wallet.objects.get_or_create(user=order.user)
        wallet.balance += refund_amount
        wallet.save()
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type='Credit',
            amount=refund_amount,
            description=f'Refund for returned items in Order {order.id}'
        )
    
    order.refund_processed_at = timezone.now()
    order.refund_method = refund_method
    order.save()
    
    # Restore stock
    for item in order.items.filter(is_cancelled=False, is_returned=True):
        if item.variant:
            item.variant.stock += item.quantity
            item.variant.save()
        else:
            product = item.product
            product.stock += item.quantity
            product.save()




@login_required
@require_POST
def update_order_status(request, order_id):
    """Quick update for order status."""
    order = get_object_or_404(Order, id=order_id)
    new_status = request.POST.get('status')
    valid_statuses = [s[0] for s in Order.STATUS_CHOICES]
    
    ALLOWED_TRANSITIONS = {
        'Pending': ['Confirmed', 'Cancelled', 'Processing'],
        'Confirmed': ['Shipped', 'Cancelled', 'Processing'],
        'Processing': ['Shipped', 'Cancelled'],
        'Shipped': ['Out for Delivery'],
        'Out for Delivery': ['Delivered'],
        'Delivered': ['Return Requested', 'Returned'],
        'Return Requested': ['Returned', 'Delivered'],
        'Cancelled': [],
        'Returned': [],
    }

    if new_status in valid_statuses:
        current_status = order.status
        if new_status != current_status:
            allowed_next = ALLOWED_TRANSITIONS.get(current_status, [])
            if new_status not in allowed_next:
                messages.error(request, f"Invalid transition: {current_status} → {new_status}")
                return redirect('admin_order_list')

        if new_status == 'Returned' and order.status != 'Returned':
            process_full_return(order, request.POST.get('refund_method', 'Wallet'))
                
        order.status = new_status
        
        if new_status == 'Delivered':
            if not order.is_paid:
                order.is_paid = True
                process_referrer_reward(order.user, order=order)

            for item in order.items.filter(is_cancelled=False, product__seller__isnull=False):
                SellerEarnings.objects.get_or_create(
                    seller=item.product.seller,
                    order_item=item,
                    defaults={'amount': item.price * item.quantity}
                )
        
        order.save()
        messages.success(request, f'Order #{order.id} moved to {new_status}.')
    else:
        messages.error(request, 'Invalid status selection.')

    # Redirect back to where the request came from
    return redirect(request.POST.get('next', 'admin_order_list'))


@login_required
@require_POST
def cancel_order_item(request, item_id):
    item = get_object_or_404(OrderItem, id=item_id)
    order = item.order
    
    if not item.is_cancelled:
        with transaction.atomic():
            item_subtotal = item.price * item.quantity
            original_order_subtotal = order.subtotal

            item.is_cancelled = True
            item.cancel_reason = request.POST.get('reason', 'Cancelled by Admin')
            item.save()

            # Restore stock
            if item.variant:
                item.variant.stock += item.quantity
                item.variant.save()
                p = item.variant.product
                p.stock = p.variants.filter(is_active=True).aggregate(Sum('stock'))['stock__sum'] or 0
                p.save(update_fields=['stock'])
            else:
                product = item.product
                product.stock += item.quantity
                product.save()

            order.update_totals()

            # Partial Refund
            if order.is_paid and order.payment_method in ['razorpay', 'wallet']:
                if original_order_subtotal > 0:
                    item_discount_share = (item_subtotal / original_order_subtotal) * order.discount
                else:
                    item_discount_share = Decimal('0')
                item_taxable = max(Decimal('0'), item_subtotal - item_discount_share)
                item_tax = (item_taxable * Decimal('0.03')).quantize(Decimal('0.01'))
                refund_amount = item_taxable + item_tax
                if refund_amount > 0:
                    wallet, _ = Wallet.objects.get_or_create(user=order.user)
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
        messages.error(request, 'This item is already cancelled.')
        
    return redirect('admin_order_detail', order_id=order.id)




@login_required
def inventory_list(request):
    """List products and variants to track stock levels."""
    search_query = request.GET.get('search', '').strip()
    products = Product.objects.filter(is_deleted=False).order_by('-created_at')
    
    if search_query:
        products = products.filter(name__icontains=search_query)

    inventory_items = []
    total_low = 0
    total_out = 0

    for product in products:
        variants = product.variants.filter(is_active=True)
        if variants.exists():
            for v in variants:
                inventory_items.append({
                    'type': 'variant',
                    'id': v.id,
                    'name': product.name,
                    'variant_name': f"{v.strap_color}".strip() or "Standard",
                    'sku': v.sku,
                    'stock': v.stock,
                    'image': product.image.url if product.image else None,
                    'price': v.price if v.price else product.price,
                    'badge': product.badge,
                })
                if v.stock == 0: total_out += 1
                elif v.stock < 10: total_low += 1
        else:
            inventory_items.append({
                'type': 'product',
                'id': product.id,
                'name': product.name,
                'variant_name': 'Base Product',
                'sku': f"PRD-{product.id}",
                'stock': product.stock,
                'image': product.image.url if product.image else None,
                'price': product.price,
                'badge': product.badge,
            })
            if product.stock == 0: total_out += 1
            elif product.stock < 10: total_low += 1
    paginator = Paginator(inventory_items, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'active_menu': 'inventory',
        'inventory_items': page_obj,
        'total_items': paginator.count,
        'total_low': total_low,
        'total_out': total_out,
        'search_query': search_query,
        'badge_choices': Product._meta.get_field('badge').choices,
    }
    return render(request, 'order_manage/stocks.html', context)


@login_required
@require_POST
def inventory_update(request):
    """Update stock, badges, or delete items via AJAX."""
    try:
        data = json.loads(request.body)
        item_type = data.get('type')
        item_id = data.get('id')

        # Update stock level
        if 'stock' in data:
            new_stock = int(data.get('stock'))
            if new_stock < 0:
                return JsonResponse({'success': False, 'message': 'Stock cannot be negative.'})

            if item_type == 'variant':
                item = ProductVariant.objects.get(id=item_id)
            else:
                item = Product.objects.get(id=item_id)
            
            item.stock = new_stock
            item.save()
            return JsonResponse({'success': True, 'new_stock': item.stock})
            
        # Update badge
        elif 'badge' in data:
            badge = data.get('badge') or None
            if item_type == 'variant':
                item = ProductVariant.objects.get(id=item_id).product
            else:
                item = Product.objects.get(id=item_id)
            
            item.badge = badge
            item.save()
            return JsonResponse({'success': True, 'badge': badge})

        # Soft delete
        elif data.get('delete'):
            if item_type == 'variant':
                item = ProductVariant.objects.get(id=item_id)
                item.is_active = False
            else:
                item = Product.objects.get(id=item_id)
                item.is_deleted = True
            item.save()
            return JsonResponse({'success': True})

        return JsonResponse({'success': False, 'message': 'No valid action.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})




@login_required
def user_requests(request):
    """Monitor active return and cancellation requests."""
    search_query = request.GET.get('q', '').strip()
    
    orders = Order.objects.filter(
        Q(status='Return Requested') | 
        Q(cancel_reason__isnull=False, cancel_reason__gt='') |
        Q(reschedule_reason__isnull=False, reschedule_reason__gt='')
    ).order_by('-created_at')
    
    if search_query:
        orders = orders.filter(
            Q(id__icontains=search_query) |
            Q(user__email__icontains=search_query)
        )

    paginator = Paginator(orders, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    return render(request, 'order_manage/user_Request.html', {
        'orders': page_obj,
        'query': search_query,
        'active_menu': 'user_requests'
    })


@login_required
def user_reschedule(request):
    """List orders with pending reschedule requests."""
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'Pending')

    orders = Order.objects.filter(
        reschedule_reason__isnull=False, 
        reschedule_reason__gt=''
    ).order_by('-created_at')
    
    if status_filter != 'All':
        orders = orders.filter(reschedule_status=status_filter)

    if search_query:
        orders = orders.filter(Q(id__icontains=search_query) | Q(user__email__icontains=search_query))

    paginator = Paginator(orders, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    return render(request, 'order_manage/user_reschedule_list.html', {
        'orders': page_obj,
        'query': search_query,
        'status_filter': status_filter,
        'active_menu': 'reschedule'
    })


@login_required
def process_reschedule(request, order_id):
    """Approve or reject a reschedule request."""
    order = get_object_or_404(Order, id=order_id)
    
    if request.method == 'GET':
        return render(request, 'order_manage/user_reschedule.html', {
            'order': order, 
            'active_menu': 'reschedule',
            'today': order.requested_reschedule_date
        })
        
    action = request.POST.get('action') 
    if action == 'approve':
        new_date = request.POST.get('reschedule_date') or order.requested_reschedule_date
        new_time = request.POST.get('reschedule_time') or order.requested_reschedule_time
        
        order.reschedule_status = 'Approved'
        order.reschedule_count += 1
        order.scheduled_delivery_date = new_date
        order.scheduled_delivery_time = new_time
        
        if request.POST.get('reschedule_reason'):
            order.reschedule_reason = request.POST.get('reschedule_reason')
            
        order.save()
        messages.success(request, f"Order #{order.id} rescheduled.")
    elif action == 'reject':
        order.reschedule_status = 'Rejected'
        order.save()
        messages.success(request, f"Reschedule request for Order #{order.id} rejected.")
    
    return redirect(request.POST.get('next') or 'admin_user_reschedule')


@login_required
def return_requests(request):
    """Monitor all formal return process requests."""
    search_query = request.GET.get('q', '').strip()
    orders = Order.objects.exclude(return_status='None').order_by('-created_at')
    
    if search_query:
        orders = orders.filter(Q(id__icontains=search_query) | Q(user__email__icontains=search_query))
    
    paginator = Paginator(orders, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    return render(request, 'order_manage/return_request.html', {
        'orders': page_obj,
        'query': search_query,
        'active_menu': 'return_requests'
    })


@login_required
@require_POST
def process_return(request, order_id):
    """Approve or reject a return request."""
    order = get_object_or_404(Order, id=order_id)
    action = request.POST.get('action')
    
    if action == 'approve':
        order.status = 'Returned'
        order.return_status = 'Returned'
        process_full_return(order, 'Wallet')
        order.save()
        messages.success(request, f"Return approved for Order #{order.id}.")
    elif action == 'reject':
        order.status = 'Delivered'
        order.return_status = 'Rejected'
        order.save()
        messages.info(request, f"Return rejected for Order #{order.id}.")
        
    return redirect('admin_return_requests')




@login_required
def sales_report(request):
    """Generate sales reports and analytics."""
    if not request.user.is_superuser:
        return redirect("dashboard")

    # Filter by date
    filter_type = request.GET.get('filter_type', 'all')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    orders = Order.objects.filter(status='Delivered').select_related('user').order_by('-created_at')
    today = timezone.now().date()

    if filter_type == 'daily':
        orders = orders.filter(created_at__date=today)
    elif filter_type == 'weekly':
        orders = orders.filter(created_at__date__gte=today - timedelta(days=7))
    elif filter_type == 'monthly':
        orders = orders.filter(created_at__date__gte=today - timedelta(days=30))
    elif filter_type == 'yearly':
        orders = orders.filter(created_at__date__gte=today - timedelta(days=365))
    elif filter_type == 'custom' and start_date and end_date:
        orders = orders.filter(created_at__date__range=[start_date, end_date])

    # Calculate statistics
    stats = orders.aggregate(
        count=Count('id'),
        revenue=Sum('total_amount'),
        discount=Sum('discount')
    )
    
    total_sales_count = stats['count'] or 0
    total_order_amount = stats['revenue'] or 0
    total_discount = stats['discount'] or 0

    # CSV Export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="timehub_sales_report.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Order ID', 'Date', 'Customer', 'Total Amount', 'Discount', 'Coupon'])
        
        for o in orders:
            writer.writerow([
                f"ORD-{o.id}", o.created_at.strftime('%Y-%m-%d'), 
                o.user.email, o.total_amount, o.discount, o.coupon_code or 'None'
            ])
        
        writer.writerow([])
        writer.writerow(['TOTALS', '', '', total_order_amount, total_discount, f'Count: {total_sales_count}'])
        return response

    # Chart trends
    now = timezone.now()

    def get_revenue_data(queryset, period='day', limit=7):
        trunc_fn = {
            'day': TruncDay, 'week': TruncWeek, 'month': TruncMonth, 'year': TruncYear
        }.get(period, TruncDay)
        
        data = queryset.annotate(p=trunc_fn('created_at')).values('p').annotate(r=Sum('total_amount')).order_by('p')
        return {s['p'].date() if hasattr(s['p'], 'date') else s['p']: float(s['r']) for s in data}

    delivered = Order.objects.filter(status='Delivered')
    
    total_revenue = orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_orders = orders.count()

    # Daily trend
    daily_map = get_revenue_data(delivered.filter(created_at__gte=now - timedelta(days=7)), 'day')
    daily_labels = [(now - timedelta(days=i)).strftime('%b %d') for i in range(6, -1, -1)]
    daily_values = [daily_map.get((now - timedelta(days=i)).date(), 0.0) for i in range(6, -1, -1)]

    # Monthly trend
    monthly_map = get_revenue_data(delivered.filter(created_at__gte=now - timedelta(days=180)), 'month')
    monthly_labels = []
    monthly_values = []
    for i in range(5, -1, -1):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        m_date = now.replace(year=y, month=m, day=1).date()
        monthly_labels.append(m_date.strftime('%b %Y'))
        val = 0.0
        for k, v in monthly_map.items():
            if k.year == m_date.year and k.month == m_date.month:
                val = v; break
        monthly_values.append(val)

    # Weekly trend
    weekly_map = get_revenue_data(delivered.filter(created_at__gte=now - timedelta(days=56)), 'week')
    weekly_labels = []
    weekly_values = []
    for i in range(7, -1, -1):
        w_date = (now - timedelta(days=now.weekday(), weeks=i)).date()
        weekly_labels.append(f"Week {w_date.strftime('%W')}")
        weekly_values.append(weekly_map.get(w_date, 0.0))

    # Yearly trend
    yearly_map = get_revenue_data(delivered.filter(created_at__gte=now - timedelta(days=365*5)), 'year')
    yearly_labels = [str(now.year - i) for i in range(4, -1, -1)]
    yearly_values = []
    for y in yearly_labels:
        val = 0.0
        for k, v in yearly_map.items():
            if str(k.year) == y:
                val = v; break
        yearly_values.append(val)

    # Serialize
    chart_data = {
        'daily': {
            'labels': daily_labels,
            'values': daily_values,
        },
        'weekly': {
            'labels': weekly_labels,
            'values': weekly_values,
        },
        'monthly': {
            'labels': monthly_labels,
            'values': monthly_values,
        },
        'yearly': {
            'labels': yearly_labels,
            'values': yearly_values,
        }
    }
    chart_data_json = json.dumps(chart_data)

    # Top metrics
    most_wanted = Product.objects.filter(
        is_deleted=False
    ).annotate(
        wishlist_count=Count('wishlistitem')
    ).filter(
        wishlist_count__gt=0
    ).order_by('-wishlist_count')[:10]

    top_products = Product.objects.filter(
        is_deleted=False,
        orderitem__order__status='Delivered',
        orderitem__is_cancelled=False,
        orderitem__is_returned=False
    ).annotate(
        contribution=Sum(F('orderitem__price') * F('orderitem__quantity')),
        units_sold=Sum('orderitem__quantity')
    ).filter(
        contribution__gt=0
    ).order_by('-contribution')[:10]

    recent_returned = Order.objects.filter(
        status='Returned'
    ).select_related('user').prefetch_related('items__product').order_by('-updated_at')[:10]

    recent_cancelled = Order.objects.filter(
        status='Cancelled'
    ).select_related('user').prefetch_related('items__product').order_by('-updated_at')[:10]

    low_stock = Product.objects.filter(
        is_deleted=False, stock__gt=0, stock__lt=10
    ).order_by('stock')[:15]

    context = {
        'orders': orders,
        'filtered_orders': orders,
        'total_sales_count': total_sales_count,
        'total_order_amount': total_order_amount,
        'total_discount': total_discount,
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'filter_type': filter_type,
        'start_date': start_date,
        'end_date': end_date,
        'active_menu': 'sales',
        'chart_data_json': chart_data_json,
        'most_wanted': most_wanted,
        'top_products': top_products,
        'recent_returned': recent_returned,
        'recent_cancelled': recent_cancelled,
        'low_stock': low_stock,
        'aov': orders.aggregate(Avg('total_amount'))['total_amount__avg'] or 0,
        'total_customers': User.objects.filter(is_superuser=False).count(),
        'total_products_count': Product.objects.filter(is_deleted=False).count(),
    }
    return render(request, 'order_manage/sales_report.html', context)
