from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from user_apps.core.models import Order, Product, ProductVariant
import json
from django.http import JsonResponse


@login_required
def order_list(request):
    orders = Order.objects.select_related('user').order_by('-created_at')

    # Search
    query = request.GET.get('q', '').strip()
    if query:
        orders = orders.filter(
            Q(id__icontains=query) |
            Q(user__email__icontains=query) |
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query)
        )

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
        address = json.loads(order.address_snapshot)
    except Exception:
        address = {}

    # Handle status update from the detail page
    if request.method == 'POST':
        new_status = request.POST.get('status')
        valid_statuses = [s[0] for s in Order.STATUS_CHOICES]
        if new_status in valid_statuses:
            order.status = new_status
            order.save()
            messages.success(request, f'Order #{order.id} status updated to {new_status}.')
        else:
            messages.error(request, 'Invalid status.')
        return redirect('order_detail', order_id=order.id)

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
    return render(request, 'order_manage/order_detail.html', context)


@login_required
@require_POST
def update_order_status(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    new_status = request.POST.get('status')
    valid_statuses = [s[0] for s in Order.STATUS_CHOICES]
    if new_status in valid_statuses:
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
def inventory_list(request):
    search_query = request.GET.get('search', '').strip()
    
    products = Product.objects.all().order_by('-created_at')
    if search_query:
        products = products.filter(name__icontains=search_query)

    inventory_items = []
    total_low = 0
    total_out = 0

    for product in products:
        variants = product.variants.all()
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
    }
    return render(request, 'order_manage/stocks.html', context)


@login_required
@require_POST
def inventory_update(request):
    try:
        data = json.loads(request.body)
        item_type = data.get('type')
        item_id = data.get('id')
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
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})
