from django.shortcuts import render
from django.core.paginator import Paginator
from django.db.models import Q
from user_apps.core.models import Product, Collection

def product_list(request):
    # Base queryset: Active and not deleted
    products = Product.objects.filter(is_active=True, is_deleted=False)
    
    # Search functionality
    query = request.GET.get('q', '')
    if query:
        products = products.filter(
            Q(name__icontains=query) | 
            Q(description__icontains=query)
        )
    
    # Filter by Category (Collection)
    category_id = request.GET.get('category')
    if category_id:
        products = products.filter(collection_id=category_id)
    
    # Filter by Price Range
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    if min_price:
        products = products.filter(price__gte=min_price)
    if max_price:
        products = products.filter(price__lte=max_price)
    
    # Sorting
    sort = request.GET.get('sort', 'newest')
    if sort == 'price_low':
        products = products.order_by('price')
    elif sort == 'price_high':
        products = products.order_by('-price')
    elif sort == 'name_az':
        products = products.order_by('name')
    elif sort == 'name_za':
        products = products.order_by('-name')
    else:
        products = products.order_by('-created_at')
        
    # Pagination
    paginator = Paginator(products, 12) # 12 products per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get all categories and annotate with product count (only active/not deleted)
    from django.db.models import Count
    categories = Collection.objects.filter(is_deleted=False).annotate(
        product_count=Count('products', filter=Q(products__is_active=True, products__is_deleted=False))
    )
    
    # Total count for "All Watches"
    total_products = Product.objects.filter(is_active=True, is_deleted=False).count()
    
    # Get Max Price for the slider
    from django.db.models import Max
    max_price_db = Product.objects.filter(is_active=True, is_deleted=False).aggregate(Max('price'))['price__max'] or 1000
    
    context = {
        'products': page_obj,
        'categories': categories,
        'total_products': total_products,
        'query': query,
        'sort': sort,
        'selected_category': category_id,
        'min_price': min_price or 0,
        'max_price': max_price or float(max_price_db),
        'max_price_limit': float(max_price_db),
    }
    
    return render(request, 'product_listing.html', context)
