from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from user_apps.core.models import Order, Product, ProductVariant, OrderItem, WishlistItem, Collection
import json
from django.http import JsonResponse
from django.db.models import Sum, Count, Avg, F
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth
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

    # Handle status update from the detail page
    if request.method == 'POST':
        new_status = request.POST.get('status')
        new_date = request.POST.get('scheduled_delivery_date')
        
        valid_statuses = [s[0] for s in Order.STATUS_CHOICES]
        if new_status in valid_statuses:
            if new_status == 'Returned' and order.status != 'Returned':
                from django.utils import timezone
                order.refund_processed_at = timezone.now()
                order.refund_method = request.POST.get('refund_method')
            
            order.status = new_status
            
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

    context = {
        'order': order,
        'address': address,
        'active_menu': 'orders',
        'status_choices': Order.STATUS_CHOICES,
        'timeline_steps': timeline_steps,
    }
    return render(request, 'order_manage/user_order_detail.html', context)


@login_required
@require_POST
def update_order_status(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    new_status = request.POST.get('status')
    valid_statuses = [s[0] for s in Order.STATUS_CHOICES]
    if new_status in valid_statuses:
        if new_status == 'Returned' and order.status != 'Returned':
            from django.utils import timezone
            order.refund_processed_at = timezone.now()
            order.refund_method = request.POST.get('refund_method')
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
            item.is_cancelled = True
            item.cancel_reason = request.POST.get('reason', 'Cancelled by Admin')
            item.save()
            
            # Restore stock
            product = item.product
            product.stock += item.quantity
            product.save()
            
            # We don't automatically cancel the order here 
            
            
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

    context = {
        'active_menu': 'inventory',
        'inventory_items': inventory_items,
        'total_items': len(inventory_items),
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
def sales_report(request):
    if not request.user.is_superuser:
        return redirect("dashboard")

    # --- KPIs ---
    delivered_orders = Order.objects.filter(status='Delivered')
    total_revenue = delivered_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_orders = Order.objects.exclude(status='Cancelled').count()
    
    today = timezone.now().date()
    today_revenue = Order.objects.filter(
        status='Delivered', 
        created_at__date=today
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    aov = delivered_orders.aggregate(Avg('total_amount'))['total_amount__avg'] or 0

    # --- Trend Data ---
    today_dt = timezone.now()
    ninety_days_ago = today_dt - timedelta(days=90)
    thirty_days_ago = today_dt - timedelta(days=30)
    
    # Daily Trend (Last 30 days)
    daily_sales = delivered_orders.filter(created_at__gte=thirty_days_ago) \
        .annotate(date=TruncDay('created_at')) \
        .values('date') \
        .annotate(revenue=Sum('total_amount'), counts=Count('id')) \
        .order_by('date')

    daily_dict = {item['date'].date() if hasattr(item['date'], 'date') else item['date']: item for item in daily_sales if item['date']}
    daily_labels, daily_revenue, daily_counts = [], [], []
    for i in range(30, -1, -1):
        day = (today_dt - timedelta(days=i)).date()
        daily_labels.append(day.strftime('%d %b'))
        if day in daily_dict:
            daily_revenue.append(float(daily_dict[day]['revenue']))
            daily_counts.append(daily_dict[day]['counts'])
        else:
            daily_revenue.append(0.0)
            daily_counts.append(0)

    daily_data = {
        "labels": daily_labels,
        "revenue": daily_revenue,
        "counts": daily_counts,
    }

    # Weekly Trend (Last 12 weeks)
    weekly_sales = delivered_orders.filter(created_at__gte=today_dt - timedelta(weeks=12)) \
        .annotate(date=TruncWeek('created_at')) \
        .values('date') \
        .annotate(revenue=Sum('total_amount'), counts=Count('id')) \
        .order_by('date')

    weekly_dict = {item['date'].date() if hasattr(item['date'], 'date') else item['date']: item for item in weekly_sales if item['date']}
    weekly_labels, weekly_revenue, weekly_counts = [], [], []
    today_week_start = today_dt.date() - timedelta(days=today_dt.date().weekday())
    for i in range(12, -1, -1):
        week_start = today_week_start - timedelta(weeks=i)
        weekly_labels.append(week_start.strftime('Week %W'))
        if week_start in weekly_dict:
            weekly_revenue.append(float(weekly_dict[week_start]['revenue']))
            weekly_counts.append(weekly_dict[week_start]['counts'])
        else:
            weekly_revenue.append(0.0)
            weekly_counts.append(0)

    weekly_data = {
        "labels": weekly_labels,
        "revenue": weekly_revenue,
        "counts": weekly_counts,
    }

    # Monthly Trend (Last 12 months)
    monthly_sales = delivered_orders.annotate(date=TruncMonth('created_at')) \
        .values('date') \
        .annotate(revenue=Sum('total_amount'), counts=Count('id')) \
        .order_by('date')

    monthly_dict = {item['date'].date() if hasattr(item['date'], 'date') else item['date']: item for item in monthly_sales if item['date']}
    monthly_labels, monthly_revenue, monthly_counts = [], [], []
    today_month_start = today_dt.date().replace(day=1)
    
    from datetime import date
    for i in range(11, -1, -1):
        target_month = today_month_start.month - i
        target_year = today_month_start.year
        while target_month <= 0:
            target_month += 12
            target_year -= 1
        month_start = date(target_year, target_month, 1)
        
        monthly_labels.append(month_start.strftime('%b %Y'))
        if month_start in monthly_dict:
            monthly_revenue.append(float(monthly_dict[month_start]['revenue']))
            monthly_counts.append(monthly_dict[month_start]['counts'])
        else:
            monthly_revenue.append(0.0)
            monthly_counts.append(0)

    monthly_data = {
        "labels": monthly_labels,
        "revenue": monthly_revenue,
        "counts": monthly_counts,
    }

    # --- Top Selling Products ---
    top_products = Product.objects.filter(is_deleted=False) \
        .annotate(
            units_sold=Sum('orderitem__quantity', filter=Q(orderitem__order__status='Delivered')),
            contribution=Sum(F('orderitem__price') * F('orderitem__quantity'), filter=Q(orderitem__order__status='Delivered'))
        ).filter(units_sold__gt=0).order_by('-contribution')[:5]

    # --- Company Metrics ---
    total_customers = User.objects.filter(is_superuser=False).count()
    total_products_count = Product.objects.filter(is_deleted=False).count()

    # --- Most Wanted (Wishlist) ---
    most_wanted = Product.objects.filter(is_deleted=False) \
        .annotate(wishlist_count=Count('wishlistitem')) \
        .filter(wishlist_count__gt=0) \
        .order_by('-wishlist_count')[:5]

    # --- Category Distribution ---
    category_sales = Collection.objects.filter(is_deleted=False) \
        .annotate(revenue=Sum(F('products__orderitem__price') * F('products__orderitem__quantity'), 
                              filter=Q(products__orderitem__order__status='Delivered'))) \
        .filter(revenue__gt=0).order_by('-revenue')
    
    category_data = {
        "labels": [c.name for c in category_sales],
        "datasets": [{
            "data": [float(c.revenue) for c in category_sales],
            "backgroundColor": ['#ff6b00', '#3b82f6', '#10b981', '#8b5cf6', '#f59e0b', '#ef4444', '#06b6d4']
        }]
    }

    # --- Status Distribution ---
    status_counts = Order.objects.values('status').annotate(count=Count('id')).order_by('-count')
    status_data = {
        "labels": [s['status'] for s in status_counts],
        "datasets": [{
            "data": [s['count'] for s in status_counts],
            "backgroundColor": ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#94a3b8', '#8b5cf6', '#ec4899']
        }]
    }

    # --- Recent Transactions ---
    recent_orders = Order.objects.select_related('user').order_by('-created_at')[:8]

    context = {
        'total_revenue': total_revenue,
        'today_revenue': today_revenue,
        'total_orders': total_orders,
        'total_customers': total_customers,
        'total_products_count': total_products_count,
        'aov': aov,
        'daily_data_json': json.dumps(daily_data),
        'weekly_data_json': json.dumps(weekly_data),
        'monthly_data_json': json.dumps(monthly_data),
        'category_data_json': json.dumps(category_data),
        'status_data_json': json.dumps(status_data),
        'recent_orders': recent_orders,
        'top_products': top_products,
        'most_wanted': most_wanted,
        'active_menu': 'sales',
        'now': timezone.now(),
    }
    return render(request, 'order_manage/sales_report.html', context)
