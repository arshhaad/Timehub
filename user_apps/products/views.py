from django.http import JsonResponse
from django.db.models import Q, Count, Max, DecimalField
from django.db.models.functions import Coalesce
from django.template.loader import render_to_string
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from user_apps.core.models import Product, Collection, ComparisonHistory, ProductImage

def product_list(request):
    # Base queryset: Active and not deleted
    products = Product.objects.filter(is_active=True, is_deleted=False).annotate(
        effective_price=Coalesce('discount_price', 'price', output_field=DecimalField())
    )
    
    # Get all categories and annotate with product count (only active/not deleted)
    categories = Collection.objects.filter(is_deleted=False).annotate(
        product_count=Count('products', filter=Q(products__is_active=True, products__is_deleted=False))
    )
    paginator = Paginator(products, 10)  # 10 per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Search functionality
    query = request.GET.get('q', '')
    if query:
        products = products.filter(
            Q(name__icontains=query) | 
            Q(description__icontains=query) |
            Q(brand__icontains=query) |
            Q(collection__name__icontains=query)
        ).distinct()
    
    # Filter by Category (Collection)
    category_id = request.GET.get('category')
    if category_id:
        products = products.filter(collection_id=category_id)
    
    # Filter by Price Range
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    if min_price:
        products = products.filter(effective_price__gte=min_price)
    if max_price:
        products = products.filter(effective_price__lte=max_price)
    
    # Advanced Filters
    brand = request.GET.get('brand')
    if brand:
        products = products.filter(brand__icontains=brand)
    
    gender = request.GET.get('gender')
    if gender:
        products = products.filter(gender=gender)
        
    occasion = request.GET.get('occasion')
    if occasion:
        products = products.filter(occasion=occasion)
        
    strap_materials_list = request.GET.getlist('strap_material')
    if strap_materials_list:
        products = products.filter(strap_material__in=strap_materials_list)
        
    strap_colors_list = request.GET.getlist('strap_color')
    if strap_colors_list:
        products = products.filter(strap_color__in=strap_colors_list)
        
    dial_colors_list = request.GET.getlist('dial_color')
    if dial_colors_list:
        products = products.filter(dial_color__in=dial_colors_list)
        
    function_type = request.GET.get('function')
    if function_type:
        products = products.filter(function=function_type)
    
    # Sorting
    sort = request.GET.get('sort', 'newest')
    if sort == 'price_low':
        products = products.order_by('effective_price')
    elif sort == 'price_high':
        products = products.order_by('-effective_price')
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
    
    # Total count for "All Watches"
    total_products = Product.objects.filter(is_active=True, is_deleted=False).count()
    
    # Get Max Price for the slider
    # Get Max Price for the slider based on effective price
    max_price_db = Product.objects.filter(is_active=True, is_deleted=False).annotate(
        effective_price=Coalesce('discount_price', 'price', output_field=DecimalField())
    ).aggregate(Max('effective_price'))['effective_price__max'] or 1000
    
    # Filter Options for UI
    occasions = ['Casual', 'Formal', 'Sport', 'Luxury']
    genders = ['Men', 'Women', 'Unisex']
    functions = ['Analog', 'Digital', 'Chronograph', 'Automatic']
    strap_materials_options = ['Leather', 'Steel', 'Silicon', 'Fabric']
    strap_colors_options = ['Black', 'Brown', 'Silver', 'Gold', 'Blue']
    dial_colors_options = ['Black', 'White', 'Blue', 'Green', 'Silver']
    
    # Pass current compare list from session to context
    compare_ids = request.session.get('compare_list', [])
    compare_products = Product.objects.filter(id__in=compare_ids, is_active=True, is_deleted=False)
    
    # Slider Percentages (Python Pre-calc)
    min_price_val = float(min_price or 0)
    max_price_val = float(max_price or max_price_db)
    min_percent = (min_price_val / float(max_price_db)) * 100 if max_price_db else 0
    max_percent = (max_price_val / float(max_price_db)) * 100 if max_price_db else 100

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
        'min_percent': min_percent,
        'max_percent': max_percent,
        'selected_brand': brand,
        'selected_gender': gender,
        'selected_occasion': occasion,
        'selected_strap_material': strap_materials_list,
        'selected_strap_color': strap_colors_list,
        'selected_dial_color': dial_colors_list,
        'selected_function': function_type,
        'occasions': occasions,
        'genders': genders,
        'functions': functions,
        'strap_materials': strap_materials_options,
        'strap_colors': strap_colors_options,
        'dial_colors': dial_colors_options,
        'current_compare_ids': [int(pid) for pid in compare_ids if str(pid).isdigit()],
        'current_compare_products': compare_products,
    }
    
    # Add wishlist items if user is authenticated
    if request.user.is_authenticated:
        from user_apps.core.models import WishlistItem
        wishlist_product_ids = WishlistItem.objects.filter(wishlist__user=request.user).values_list('product_id', flat=True)
        context['wishlist_product_ids'] = list(wishlist_product_ids)
    
    return render(request, 'product_listing.html', context)

def compare_products(request):
    # Try to get IDs from session first, then GET
    product_ids = request.session.get('compare_list', [])
    if not product_ids:
        product_ids_str = request.GET.get('ids', '')
        product_ids = [pid for pid in product_ids_str.split(',') if str(pid).isdigit()]
    
    # Filter out empty strings and invalid IDs
    product_ids = [pid for pid in product_ids if str(pid).isdigit()]
    
    if not product_ids:
        # Show history if no active comparison
        history = []
        if request.user.is_authenticated:
            history = ComparisonHistory.objects.filter(user=request.user).order_by('-created_at')[:10]
        return render(request, 'compare.html', {'products': [], 'history': history})
        
    # Get products, limit to 2
    products = Product.objects.filter(id__in=product_ids, is_active=True, is_deleted=False)[:2]
    
    # Save to history if logged in
    if request.user.is_authenticated and products.exists():
        for p in products:
            ComparisonHistory.objects.update_or_create(
                user=request.user, 
                product=p,
                defaults={'created_at': None} 
            )
            
    # Process features for each product
    for product in products:
        if product.features:
            product.features_list = [f.strip() for f in product.features.split(',')]
        else:
            product.features_list = []
            
    # Get overall history
    history = []
    if request.user.is_authenticated:
        history = ComparisonHistory.objects.filter(user=request.user).order_by('-created_at')[:10]
            
    context = {
        'products': products,
        'history': history,
    }
    return render(request, 'compare.html', context)

def toggle_compare(request):
    product_id = request.GET.get('id')
    if not product_id:
        return JsonResponse({'success': False, 'error': 'No ID provided'})
    
    compare_list = request.session.get('compare_list', [])
    
    if str(product_id) in compare_list:
        compare_list.remove(str(product_id))
    else:
        if len(compare_list) >= 2:
            return JsonResponse({'success': False, 'error': 'Maximum 2 products allowed'})
        compare_list.append(str(product_id))
    
    request.session['compare_list'] = compare_list
    request.session.modified = True
    
    # Get objects for the bar
    compare_products = Product.objects.filter(id__in=compare_list, is_active=True, is_deleted=False)
    
    products_data = []
    for p in compare_products:
        products_data.append({
            'id': p.id,
            'name': p.name,
            'image': p.image.url if p.image else None
        })
    
    return JsonResponse({
        'success': True, 
        'count': len(products_data),
        'products': products_data
    })

def clear_compare(request):
    request.session['compare_list'] = []
    request.session.modified = True
    return JsonResponse({'success': True, 'count': 0, 'products': []})

def toggle_compare_mode(request):
    is_active = request.GET.get('active') == 'true'
    request.session['compare_mode_active'] = is_active
    request.session.modified = True
    return JsonResponse({'success': True, 'mode': is_active})

def product_details(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    
    # Check if the product is active or if its collection/itself is deleted
    if not product.is_active or product.is_deleted or (product.collection and product.collection.is_deleted):
        messages.error(request, "This product is currently unavailable or has been removed.")
        return redirect('product_listing')
        
    # Get additional images
    images = product.images.all()
    
    # Process features for the specifications tab
    features_list = []
    if product.features:
        features_list = [f.strip() for f in product.features.split(',')]
        
    # Get related products (same collection or same brand, active and not deleted, max 4)
    related_products = Product.objects.filter(
        Q(collection=product.collection) | Q(brand=product.brand),
        is_active=True, is_deleted=False
    ).exclude(id=product.id).distinct()[:4]
    
    MAX_QTY = 10
    savings = 0
    if product.discount_price:
        savings = product.price - product.discount_price
    
    context = {
        'product': product,
        'images': images,
        'features_list': features_list,
        'related_products': related_products,
        'MAX_QTY': MAX_QTY,
        'savings': savings,
    }

    # Add wishlist status
    if request.user.is_authenticated:
        from user_apps.core.models import WishlistItem
        is_in_wishlist = WishlistItem.objects.filter(wishlist__user=request.user, product=product).exists()
        context['is_in_wishlist'] = is_in_wishlist

    return render(request, 'product_details.html', context)
