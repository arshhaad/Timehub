from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from user_apps.core.models import Order, Product, ProductVariant, OrderItem, WishlistItem, Collection, Wallet, WalletTransaction
import json
from django.http import JsonResponse
from django.db.models import Sum, Count, Avg, F
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncYear
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model

User = get_user_model()


@login_required
def order_list(request):
    orders = Order.objects.select_related('user').order_by('-created_at')

    # Search
    query = request.GET.get('q', '').strip()
    if query:
        search_filter = Q(user__email__icontains=query) | \
                        Q(user__first_name__icontains=query) | \
                        Q(user__last_name__icontains=query)
        if query.isdigit():
            search_filter |= Q(id=query)
        orders = orders.filter(search_filter)

    # Status filter
    status_filter = request.GET.get('status', 'all')
    if status_filter and status_filter != 'all':
        orders = orders.filter(status=status_filter)

    # Sort
    sort = request.GET.get('sort', 'newest')
    if sort == 'oldest':
        orders = orders.order_by('created_at')
    elif sort == 'amount_high':
        orders = orders.order_by('-total_amount')
    elif sort == 'amount_low':
        orders = orders.order_by('total_amount')
    else:
        orders = orders.order_by('-created_at')

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
    order = get_object_or_404(
        Order.objects.select_related('user').prefetch_related('items__product'),
        id=order_id
    )

    # Parse address snapshot
    import json
    address = {}
    try:
        # Address stored as JSON snapshot at time of order
        address = json.loads(order.address_snapshot)
    except Exception:
        address = {}
        
    # Auto-fix totals for pending/processing/shipped orders to reflect latest logic
    if order.status in ['Pending', 'Processing', 'Shipped']:
        order.update_totals()

    # Handle status update from the detail page
    if request.method == 'POST':
        new_status = request.POST.get('status')
        new_return_status = request.POST.get('return_status')
        new_date = request.POST.get('scheduled_delivery_date')
        
        valid_statuses = [s[0] for s in Order.STATUS_CHOICES]
        
        # Define allowed transitions
        ALLOWED_TRANSITIONS = {
            'Pending': ['Confirmed', 'Cancelled', 'Processing'],
            'Confirmed': ['Shipped', 'Cancelled', 'Processing'],
            'Processing': ['Shipped', 'Cancelled'],
            'Shipped': ['Out for Delivery'],
            'Out for Delivery': ['Delivered'],
            'Delivered': ['Return Requested', 'Returned'],
            'Return Requested': ['Returned', 'Delivered'], # Delivered if rejected
            'Cancelled': [],
            'Returned': [],
        }

        if new_status in valid_statuses:
            # Check if transition is allowed
            current_status = order.status
            if new_status != current_status:
                allowed_next = ALLOWED_TRANSITIONS.get(current_status, [])
                if new_status not in allowed_next:
                    messages.error(request, f"Invalid transition: Cannot change status from {current_status} to {new_status}.")
                    return redirect('admin_order_detail', order_id=order.id)

            # Traditional status logic
            if new_status == 'Returned' and order.status != 'Returned':
                # This is a legacy transition, we now prefer return_status flow but keeping for safety
                process_full_return(order, request.POST.get('refund_method'))
            
            order.status = new_status
            
            # New Return Status logic
            if new_return_status and new_return_status in [c[0] for c in Order.RETURN_STATUS_CHOICES]:
                order.return_status = new_return_status
                if new_return_status == 'Returned' and order.status != 'Returned':
                    order.status = 'Returned'
                    process_full_return(order, request.POST.get('refund_method') or 'Wallet')
                elif new_return_status == 'Rejected':
                    order.status = 'Delivered'
            
            # Update delivery date if provided
            if new_date:
                order.scheduled_delivery_date = new_date
            elif new_date == '':
                order.scheduled_delivery_date = None
                
            order.save()
            messages.success(request, f'Order #{order.id} status and delivery info updated successfully.')
        else:
            messages.error(request, 'Invalid status.')
        return redirect('admin_order_detail', order_id=order.id)

    timeline_steps = [
        ('Pending',          'Order received'),
        ('Processing',       'Being prepared'),
        ('Shipped',          'On the way'),
        ('Out for Delivery', 'Out for delivery'),
        ('Delivered',        'Delivered to customer'),
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
    allowed_statuses = [s for s in Order.STATUS_CHOICES if s[0] == order.status or s[0] in allowed_next]

    context = {
        'order': order,
        'address': address,
        'active_menu': 'orders',
        'status_choices': allowed_statuses,
        'return_status_choices': Order.RETURN_STATUS_CHOICES,
        'timeline_steps': timeline_steps,
    }
    return render(request, 'order_manage/user_order_detail.html', context)

def process_full_return(order, refund_method):
    """Helper to process refund and stock restore when a return is finalized."""
    from django.utils import timezone
    if order.status == 'Returned':
        return # already processed
        
    order.refund_processed_at = timezone.now()
    order.refund_method = refund_method
    
    if order.payment_method in ['razorpay', 'wallet']:
        wallet, _ = Wallet.objects.get_or_create(user=order.user)
        wallet.balance += order.total_amount
        wallet.save()
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type='Credit',
            amount=order.total_amount,
            description=f'Refund for returned Order #{order.id}'
        )
    
    # Increment Stock for all items in the order
    for item in order.items.filter(is_cancelled=False):
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
    order = get_object_or_404(Order, id=order_id)
    new_status = request.POST.get('status')
    valid_statuses = [s[0] for s in Order.STATUS_CHOICES]
    
    # Define allowed transitions
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
        # Check if transition is allowed
        current_status = order.status
        if new_status != current_status:
            allowed_next = ALLOWED_TRANSITIONS.get(current_status, [])
            if new_status not in allowed_next:
                messages.error(request, f"Invalid transition: Cannot change status from {current_status} to {new_status}.")
                return redirect('admin_order_list')

        if new_status == 'Returned' and order.status != 'Returned':
            from django.utils import timezone
            order.refund_processed_at = timezone.now()
            order.refund_method = request.POST.get('refund_method')
            
            if order.payment_method in ['razorpay', 'wallet']:
                wallet, _ = Wallet.objects.get_or_create(user=order.user)
                wallet.balance += order.total_amount
                wallet.save()
                WalletTransaction.objects.create(
                    wallet=wallet,
                    transaction_type='Credit',
                    amount=order.total_amount,
                    description=f'Refund for returned Order #{order.id}'
                )
            
            # Increment Stock for all items in the order
            for item in order.items.filter(is_cancelled=False):
                if item.variant:
                    item.variant.stock += item.quantity
                    item.variant.save()
                else:
                    product = item.product
                    product.stock += item.quantity
                    product.save()
                
        order.status = new_status
        order.save()
        messages.success(request, f'Order #{order.id} status updated to {new_status}.')
    else:
        messages.error(request, 'Invalid status.')

    next_url = request.POST.get('next', '')
    if next_url:
        return redirect(next_url)
    return redirect('admin_order_list')
    

@login_required
@require_POST
def cancel_order_item(request, item_id):
    item = get_object_or_404(OrderItem, id=item_id)
    order = item.order
    
    if not item.is_cancelled:
        from django.db import transaction
        with transaction.atomic():
            original_total = order.total_amount
            
            item.is_cancelled = True
            item.cancel_reason = request.POST.get('reason', 'Cancelled by Admin')
            item.save()
            
            # Restore stock
            if item.variant:
                item.variant.stock += item.quantity
                item.variant.save()
            else:
                product = item.product
                product.stock += item.quantity
                product.save()
            
            # We don't automatically cancel the order here 
            order.update_totals()
            
            if order.payment_method in ['razorpay', 'wallet']:
                refund_amount = original_total - order.total_amount
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
            
        messages.success(request, f'Item "{item.product.name}" in Order #{order.id} has been cancelled.')
    else:
        messages.error(request, 'This item is already cancelled.')
        
    return redirect('admin_order_detail', order_id=order.id)


@login_required
def inventory_list(request):
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
                    'variant_name': f"{v.strap_color} {v.dial_color}".strip() or "Standard",
                    'sku': v.sku,
                    'stock': v.stock,
                    'image': product.image.url if product.image else None,
                    'price': v.price if v.price else product.price,
                    'badge': product.badge,
                })
                if v.stock == 0:
                    total_out += 1
                elif v.stock < 10:
                    total_low += 1
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
            if product.stock == 0:
                total_out += 1
            elif product.stock < 10:
                total_low += 1

    # Pagination
    paginator = Paginator(inventory_items, 10)  # 10 items per page
    page_number = request.GET.get('page')
    inventory_page = paginator.get_page(page_number)

    context = {
        'active_menu': 'inventory',
        'inventory_items': inventory_page,
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
    try:
        data = json.loads(request.body)
        item_type = data.get('type')
        item_id = data.get('id')
        if 'stock' in data:
            new_stock = int(data.get('stock'))
            if new_stock < 0:
                return JsonResponse({'success': False, 'message': 'Stock cannot be negative.'})

            if item_type == 'variant':
                item = ProductVariant.objects.get(id=item_id)
                item.stock = new_stock
                item.save()
            elif item_type == 'product':
                item = Product.objects.get(id=item_id)
                item.stock = new_stock
                item.save()
            else:
                return JsonResponse({'success': False, 'message': 'Invalid type.'})
            return JsonResponse({'success': True, 'message': 'Stock updated successfully.', 'new_stock': item.stock})
            
        elif 'badge' in data:
            new_badge = data.get('badge')
            if not new_badge:
                new_badge = None
            if item_type == 'variant':
                item = ProductVariant.objects.get(id=item_id)
                item.product.badge = new_badge
                item.product.save()
            elif item_type == 'product':
                item = Product.objects.get(id=item_id)
                item.badge = new_badge
                item.save()
            else:
                return JsonResponse({'success': False, 'message': 'Invalid type.'})
            return JsonResponse({'success': True, 'message': 'Badge updated successfully.', 'badge': new_badge})

        elif 'delete' in data and data['delete']:
            if item_type == 'variant':
                item = ProductVariant.objects.get(id=item_id)
                item.is_active = False
                item.save()
            elif item_type == 'product':
                item = Product.objects.get(id=item_id)
                item.is_deleted = True
                item.save()
            else:
                return JsonResponse({'success': False, 'message': 'Invalid type.'})
            return JsonResponse({'success': True, 'message': 'Item deleted successfully.'})

        return JsonResponse({'success': False, 'message': 'No valid data provided.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
def user_requests(request):
    search_query = request.GET.get('q', '').strip()
    
    # We show generic return requests or orders with cancel reasons 
    orders = Order.objects.filter(
        Q(status='Return Requested') | 
        Q(cancel_reason__isnull=False, cancel_reason__gt='') |
        Q(reschedule_reason__isnull=False, reschedule_reason__gt='')
    ).order_by('-created_at')
    
    if search_query:
        orders = orders.filter(
            Q(id__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(user__first_name__icontains=search_query)
        )

    # We also show item-level cancellations if desired, but for now we focus on the order level.
    # The UI can aggregate or list them.
    
    paginator = Paginator(orders, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'orders': page_obj,
        'query': search_query,
        'active_menu': 'user_requests'
    }
    return render(request, 'order_manage/user_Request.html', context)


@login_required
def user_reschedule(request):
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'Pending')

    orders = Order.objects.filter(
        reschedule_reason__isnull=False, 
        reschedule_reason__gt=''
    ).order_by('-created_at')
    
    if status_filter != 'All':
        orders = orders.filter(reschedule_status=status_filter)

    if search_query:
        orders = orders.filter(
            Q(id__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(user__first_name__icontains=search_query)
        )

    paginator = Paginator(orders, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'orders': page_obj,
        'query': search_query,
        'status_filter': status_filter,
        'active_menu': 'reschedule'
    }
    return render(request, 'order_manage/user_reschedule_list.html', context)


@login_required
def process_reschedule(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    
    if request.method == 'GET':
        return render(request, 'order_manage/user_reschedule.html', {'order': order, 'active_menu': 'reschedule', 'today': order.requested_reschedule_date})
        
    action = request.POST.get('action') 
    
    if action == 'approve':
        new_date = request.POST.get('reschedule_date')
        new_time = request.POST.get('reschedule_time')
        new_reason = request.POST.get('reschedule_reason')
        
        order.reschedule_status = 'Approved'
        order.reschedule_count += 1
        
        if new_date and new_date.strip():
            order.scheduled_delivery_date = new_date
        else:
            order.scheduled_delivery_date = order.requested_reschedule_date
            
        if new_time and new_time.strip():
            order.scheduled_delivery_time = new_time
        else:
            order.scheduled_delivery_time = order.requested_reschedule_time

        if new_reason and new_reason.strip():
            order.reschedule_reason = new_reason
            
        order.save()
        messages.success(request, f"Reschedule request for Order #{order.id} approved.")
    elif action == 'reject':
        order.reschedule_status = 'Rejected'
        order.save()
        messages.success(request, f"Reschedule request for Order #{order.id} rejected.")
    else:
        messages.error(request, "Invalid action.")
    
    # If next is provided (e.g. from hub or order detail), go there, else go to the reschedule list.
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('admin_user_reschedule')
@login_required
def return_requests(request):
    """View to list all pending return requests."""
    search_query = request.GET.get('q', '').strip()
    
    # Show orders that have a return status set (Requested, Processing, Pickup Scheduled, Returned, Rejected)
    orders = Order.objects.exclude(return_status='None').order_by('-created_at')
    
    if search_query:
        orders = orders.filter(
            Q(id__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(user__first_name__icontains=search_query)
        )
    
    paginator = Paginator(orders, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'orders': page_obj,
        'query': search_query,
        'active_menu': 'return_requests'
    }
    return render(request, 'order_manage/return_request.html', context)


@login_required
@require_POST
def process_return(request, order_id):
    """Process a return request (Accept/Reject)."""
    order = get_object_or_404(Order, id=order_id)
    action = request.POST.get('action')
    
    if action == 'approve':
        # Default to full return for simple one-click approval from list
        order.status = 'Returned'
        order.return_status = 'Returned'
        process_full_return(order, 'Wallet')
        order.save()
        messages.success(request, f"Return request for Order #{order.id} has been approved and refunded.")
    
    elif action == 'reject':
        order.status = 'Delivered'
        order.return_status = 'Rejected'
        order.save()
        messages.info(request, f"Return request for Order #{order.id} has been rejected.")
    
    else:
        messages.error(request, "Invalid action.")
        
    return redirect('admin_return_requests')


from django.http import HttpResponse
import csv

@login_required
def sales_report(request):
    if not request.user.is_superuser:
        return redirect("dashboard")

    # --- Filtering ---
    filter_type = request.GET.get('filter_type', 'all')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    orders = Order.objects.filter(status='Delivered').select_related('user').order_by('-created_at')
    
    today = timezone.now().date()
    if filter_type == 'daily':
        orders = orders.filter(created_at__date=today)
    elif filter_type == 'weekly':
        week_ago = today - timedelta(days=7)
        orders = orders.filter(created_at__date__gte=week_ago)
    elif filter_type == 'monthly':
        month_ago = today - timedelta(days=30)
        orders = orders.filter(created_at__date__gte=month_ago)
    elif filter_type == 'yearly':
        year_ago = today - timedelta(days=365)
        orders = orders.filter(created_at__date__gte=year_ago)
    elif filter_type == 'custom' and start_date and end_date:
        orders = orders.filter(created_at__date__range=[start_date, end_date])

    # --- Calculations ---
    report_data = orders.aggregate(
        total_sales_count=Count('id'),
        total_order_amount=Sum('total_amount'),
        total_discount=Sum('discount')
    )
    
    total_sales_count = report_data['total_sales_count'] or 0
    total_order_amount = report_data['total_order_amount'] or 0
    total_discount = report_data['total_discount'] or 0

    # --- CSV Export ---
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="sales_report.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Order ID', 'Date', 'Customer', 'Total Amount', 'Discount', 'Coupon Code'])
        
        for order in orders:
            writer.writerow([
                f"ORD-{order.id}",
                order.created_at.strftime('%Y-%m-%d %H:%M'),
                order.user.email,
                order.total_amount,
                order.discount,
                order.coupon_code or 'N/A'
            ])
        
        # Add summary rows
        writer.writerow([])
        writer.writerow(['Total Sales Count', total_sales_count])
        writer.writerow(['Total Order Amount', total_order_amount])
        writer.writerow(['Total Discount', total_discount])
        
        return response

    # --- Original Dashboard Data (for the charts/KPIs) ---
    delivered_orders = Order.objects.filter(status='Delivered')
    all_time_revenue = delivered_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    all_time_orders = Order.objects.exclude(status='Cancelled').count()
    total_customers = User.objects.filter(is_superuser=False).count()
    total_products_count = Product.objects.filter(is_deleted=False).count()
    aov = delivered_orders.aggregate(Avg('total_amount'))['total_amount__avg'] or 0
    # --- Chart Data (Revenue Trends) ---
    now = timezone.now()
    # Daily (Last 7 days)
    daily_sales_data = Order.objects.filter(status='Delivered', created_at__gte=now - timedelta(days=7)) \
        .annotate(date=TruncDay('created_at')) \
        .values('date') \
        .annotate(revenue=Sum('total_amount')) \
        .order_by('date')
    
    daily_labels = [(now - timedelta(days=i)).strftime('%b %d') for i in range(6, -1, -1)]
    daily_rev_map = {s['date'].date() if hasattr(s['date'], 'date') else s['date']: float(s['revenue']) for s in daily_sales_data}
    daily_values = [daily_rev_map.get((now - timedelta(days=i)).date(), 0.0) for i in range(6, -1, -1)]

    # Monthly (Last 6 months)
    monthly_sales_data = Order.objects.filter(status='Delivered', created_at__gte=now - timedelta(days=180)) \
        .annotate(month=TruncMonth('created_at')) \
        .values('month') \
        .annotate(revenue=Sum('total_amount')) \
        .order_by('month')
    
    monthly_labels = []
    monthly_values = []
    for i in range(5, -1, -1):
        month_date = (now.replace(day=1) - timedelta(days=i*30)).replace(day=1)
        monthly_labels.append(month_date.strftime('%b %Y'))
        val = 0.0
        for s in monthly_sales_data:
            if s['month'].year == month_date.year and s['month'].month == month_date.month:
                val = float(s['revenue'])
                break
        monthly_values.append(val)
    
    # Weekly (Last 8 weeks)
    weekly_sales_data = Order.objects.filter(status='Delivered', created_at__gte=now - timedelta(days=56)) \
        .annotate(week=TruncWeek('created_at')) \
        .values('week') \
        .annotate(revenue=Sum('total_amount')) \
        .order_by('week')
    
    weekly_labels = []
    weekly_values = []
    for i in range(7, -1, -1):
        week_date = (now - timedelta(days=now.weekday(), weeks=i)).date()
        weekly_labels.append(f"Week {week_date.strftime('%W')}")
        val = 0.0
        for s in weekly_sales_data:
            if s['week'].date() == week_date:
                val = float(s['revenue'])
                break
        weekly_values.append(val)

    # Yearly (Last 5 years)
    yearly_sales_data = Order.objects.filter(status='Delivered', created_at__gte=now - timedelta(days=365*5)) \
        .annotate(year=TruncYear('created_at')) \
        .values('year') \
        .annotate(revenue=Sum('total_amount')) \
        .order_by('year')
    
    yearly_labels = [str(now.year - i) for i in range(4, -1, -1)]
    yearly_values = []
    for year_str in yearly_labels:
        val = 0.0
        for s in yearly_sales_data:
            if str(s['year'].year) == year_str:
                val = float(s['revenue'])
                break
        yearly_values.append(val)

    chart_data = {
        'daily': {'labels': daily_labels, 'values': daily_values},
        'weekly': {'labels': weekly_labels, 'values': weekly_values},
        'monthly': {'labels': monthly_labels, 'values': monthly_values},
        'yearly': {'labels': yearly_labels, 'values': yearly_values},
    }

    # Top Products
    top_products = Product.objects.filter(is_deleted=False) \
        .annotate(
            units_sold=Sum('orderitem__quantity', filter=Q(orderitem__order__status='Delivered')),
            contribution=Sum(F('orderitem__price') * F('orderitem__quantity'), filter=Q(orderitem__order__status='Delivered'))
        ).filter(units_sold__gt=0).order_by('-contribution')[:5]

    # Most Wanted
    most_wanted = Product.objects.filter(is_deleted=False) \
        .annotate(wishlist_count=Count('wishlistitem')) \
        .filter(wishlist_count__gt=0) \
        .order_by('-wishlist_count')[:5]

    context = {
        'total_revenue': all_time_revenue,
        'total_orders': all_time_orders,
        'total_customers': total_customers,
        'total_products_count': total_products_count,
        'aov': aov,
        'chart_data_json': json.dumps(chart_data),
        'top_products': top_products,
        'most_wanted': most_wanted,
        'active_menu': 'sales',
        'now': timezone.now(),
        # New context for reports
        'filtered_orders': orders,
        'total_sales_count': total_sales_count,
        'total_order_amount': total_order_amount,
        'total_discount': total_discount,
        'filter_type': filter_type,
        'start_date': start_date,
        'end_date': end_date,
    }
    return render(request, 'order_manage/sales_report.html', context)
