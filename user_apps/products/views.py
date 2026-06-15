from django.http import JsonResponse
from django.db.models import Q, Count, Max, DecimalField
from django.db.models.functions import Coalesce
from django.template.loader import render_to_string
from django.core.paginator import Paginator
from django.utils import timezone
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from decimal import Decimal
from user_apps.core.models import Product, Collection, ComparisonHistory, ProductImage, Cart
from admin_apps.offers.models import Coupon
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache


def product_list(request):
    # Base queryset: Show active products AND inactive products (to show as unavailable)
    products = Product.objects.filter(is_deleted=False).annotate(
        effective_price=Coalesce('discount_price', 'price', output_field=DecimalField())
    )
    
    # Get all categories and annotate with product count (only active/not deleted)
    categories = Collection.objects.filter(is_deleted=False).annotate(
        product_count=Count('products', filter=Q(products__is_active=True, products__is_deleted=False))
    )
    paginator = Paginator(products, 12) # 12 per page
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
    
    # Total count for "All Watches" (including inactive but not deleted)
    total_products = Product.objects.filter(is_deleted=False).count()
    
    # Get Max Price for the slider
    # Get Max Price for the slider based on effective price
    max_price_db = Product.objects.filter(is_deleted=False).annotate(
        effective_price=Coalesce('discount_price', 'price', output_field=DecimalField())
    ).aggregate(Max('effective_price'))['effective_price__max'] or 1000
    
    # Filter Options for UI
    occasions = ['Casual', 'Formal', 'Sport', 'Luxury']
    genders = ['Men', 'Women', 'Unisex']
    functions = ['Analog', 'Digital', 'Chronograph', 'Automatic', 'Smart', 'Mechanical']
    strap_materials_options = ['Leather', 'Steel', 'Silicon', 'Fabric']
    strap_colors_options = ['Black', 'Brown', 'Silver', 'Gold', 'Blue']

    
    # Pass current compare list from session to context
    compare_ids = request.session.get('compare_list', [])
    compare_products = Product.objects.filter(id__in=compare_ids, is_active=True, is_deleted=False)
    
    # Slider Percentages 
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

        'selected_function': function_type,
        'occasions': occasions,
        'genders': genders,
        'functions': functions,
        'strap_materials': strap_materials_options,
        'strap_colors': strap_colors_options,

        'current_compare_ids': [int(pid) for pid in compare_ids if str(pid).isdigit()],
        'current_compare_products': compare_products,
    }
    
    # Add wishlist items if user is authenticated
    if request.user.is_authenticated:
        from user_apps.core.models import WishlistItem
        wishlist_product_ids = WishlistItem.objects.filter(wishlist__user=request.user).values_list('product_id', flat=True)
        context['wishlist_product_ids'] = list(wishlist_product_ids)
    
    return render(request, 'product_listing.html', context)

@login_required
@never_cache
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
        return render(request, 'compare.html', {
            'products': [], 
            'history': history,
            'fill_count': 3,
            'places_to_fill': range(3)
        })
        
    # Get products, limit to 3
    products = Product.objects.filter(id__in=product_ids, is_active=True, is_deleted=False)[:3]
    
    # Save to history if logged in
    if request.user.is_authenticated and products.exists():
        for p in products:
            ComparisonHistory.objects.update_or_create(
                user=request.user, 
                product=p,
                defaults={'created_at': timezone.now()} 
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
            
    # --- Price calculations (mirrors checkout logic) ---
    # display_price already reflects any active product/category offers
    TAX_RATE = Decimal('0.03')
    
    subtotal = sum(p.display_price for p in products)
    
    # How much the customer saved from product/category offers (display only)
    offer_savings = sum(
        max(Decimal('0'), p.price - p.display_price)
        for p in products
    )
    
    # Shipping: free if no items or subtotal >= ₹5000
    if not products.exists() or subtotal == 0:
        shipping = Decimal('0.00')
    elif subtotal >= Decimal('5000.00'):
        shipping = Decimal('0.00')
    else:
        shipping = Decimal('49.00')
    
    # Tax: 3% on subtotal
    tax = round(subtotal * TAX_RATE, 2)
    
    # Grand total
    total_price = subtotal + tax + shipping
    
    fill_count = max(0, 3 - len(products))
    context = {
        'products': products,
        'history': history,
        'places_to_fill': range(fill_count),
        'fill_count': fill_count,
        'subtotal': subtotal,
        'shipping': shipping,
        'tax': tax,
        'offer_savings': offer_savings,
        'total_price': total_price,
    }
    return render(request, 'compare.html', context)

@login_required
@never_cache
def toggle_compare(request):
    product_id = request.GET.get('id')
    if not product_id:
        return JsonResponse({'success': False, 'error': 'No ID provided'})
    
    compare_list = request.session.get('compare_list', [])
    
    if str(product_id) in compare_list:
        compare_list.remove(str(product_id))
    else:
        if len(compare_list) >= 3:
            return JsonResponse({'success': False, 'error': 'Maximum 3 products allowed'})
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
@login_required
@never_cache
def clear_compare(request):
    request.session['compare_list'] = []
    request.session.modified = True
    return JsonResponse({'success': True, 'count': 0, 'products': []})

@login_required
@never_cache
def toggle_compare_mode(request):
    is_active = request.GET.get('active') == 'true'
    request.session['compare_mode_active'] = is_active
    request.session.modified = True
    return JsonResponse({'success': True, 'mode': is_active})


@never_cache
def product_details(request, product_uuid):
    product = get_object_or_404(Product, uuid=product_uuid)
    
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
        
    # --- Beginner-Friendly Content-Based Recommendation Engine with Redis Caching ---
    from django.core.cache import cache
    import logging
    logger = logging.getLogger(__name__)

    cache_key = f"product_recommendations_{product.uuid}"
    recommended_ids = None
    try:
        recommended_ids = cache.get(cache_key)
    except Exception as e:
        logger.error(f"Redis cache error on details page: {e}")

    if recommended_ids is None:
        # Step 1: Fetch candidate products (all products that are active, not deleted, and NOT the current product)
        candidates = Product.objects.filter(is_active=True, is_deleted=False).exclude(id=product.id)
        
        # Step 2: Score each candidate product based on matching features
        scored_candidates = []
        for candidate in candidates:
            score = 0
            
            # Rule A: Same collection/category is highly relevant (adds 3 points)
            if candidate.collection == product.collection:
                score += 3
                
            # Rule B: Same brand is important (adds 2 points)
            if candidate.brand == product.brand:
                score += 2
                
            # Rule C: Matching target gender is important (adds 2 points)
            if candidate.gender == product.gender:
                score += 2
                
            # Rule D: Matching occasion adds 1 point
            if candidate.occasion == product.occasion:
                score += 1
                
            # Rule E: Matching strap material adds 1 point
            if candidate.strap_material and candidate.strap_material == product.strap_material:
                score += 1
                
            # Rule F: Matching watch function/movement type adds 1 point
            if candidate.function == product.function:
                score += 1
                
            # Store the calculated score along with the candidate watch
            scored_candidates.append((score, candidate))
        
        # Step 3: Sort candidates by score (highest first). Use rating as a tie-breaker.
        scored_candidates.sort(key=lambda x: (x[0], x[1].rating), reverse=True)
        
        # Step 4: Keep only the top 4 recommended watches
        related_products = [item[1] for item in scored_candidates[:4]]
        recommended_ids = [p.id for p in related_products]
        try:
            cache.set(cache_key, recommended_ids, timeout=86400)
        except Exception as e:
            logger.error(f"Redis cache set error on details page: {e}")

    # Fetch product details for the cached IDs, preserving the sorted order
    related_products = list(Product.objects.filter(id__in=recommended_ids, is_active=True, is_deleted=False))
    preserved = {pid: pos for pos, pid in enumerate(recommended_ids)}
    related_products.sort(key=lambda p: preserved.get(p.id, 999))

    # Pad if we have less than 4 items (e.g. if some got deleted or deactivated)
    if len(related_products) < 4:
        needed = 4 - len(related_products)
        exclude_ids = [p.id for p in related_products] + [product.id]
        fallbacks = Product.objects.filter(
            is_active=True, is_deleted=False
        ).exclude(id__in=exclude_ids).order_by('-rating', '-created_at')[:needed]
        related_products.extend(list(fallbacks))

    # this is recomations side view 
    
    MAX_QTY = 10
    savings = 0
    if product.discount_price:
        savings = product.price - product.discount_price
    # Get active variants
    active_variants = product.variants.filter(is_active=True).order_by('id')
    
    # Extract unique attributes for professional selection
    strap_colors = []

    materials = []
    dial_colors = []
    
    seen_strap = set()
    seen_material = set()
    seen_dial = set()
    
    # Try to map color names to hex codes from Color model
    from user_apps.core.models import Color
    color_map = {c.name.lower(): c.hex_code for c in Color.objects.all()}
    
    for v in active_variants:
        if v.strap_color and v.strap_color.strip().lower() not in seen_strap:
            c_name = v.strap_color.strip()
            strap_colors.append({
                'name': c_name,
                'hex': color_map.get(c_name.lower(), '#888') # Default gray if not found
            })
            seen_strap.add(c_name.lower())
            

            
        if v.strap_material and v.strap_material.strip().lower() not in seen_material:
            m_name = v.strap_material.strip()
            materials.append(m_name)
            seen_material.add(m_name.lower())
            
        if v.dial_color and v.dial_color.strip().lower() not in seen_dial:
            d_name = v.dial_color.strip()
            dial_colors.append({
                'name': d_name,
                'hex': color_map.get(d_name.lower(), '#888')
            })
            seen_dial.add(d_name.lower())

    # Add reviews
    reviews = product.reviews.all().order_by('-created_at')
    
    context = {
        'product': product,
        'images': images,
        'features_list': features_list,
        'related_products': related_products,
        'MAX_QTY': MAX_QTY,
        'savings': savings,
        'active_variants': active_variants,
        'strap_colors': strap_colors,
        'dial_colors': dial_colors,
        'materials': materials,
        'reviews': reviews,
        'cart_count': 0,
        'is_in_wishlist': False,
    }

    # Add wishlist status and review permission
    if request.user.is_authenticated:
        from user_apps.core.models import WishlistItem, OrderItem, CartItem
        from admin_apps.offers.models import Coupon
        from django.db.models import Sum
        
        is_in_wishlist = WishlistItem.objects.filter(wishlist__user=request.user, product=product).exists()
        context['is_in_wishlist'] = is_in_wishlist

        # Cart count for header badge
        cart_count = (
            CartItem.objects.filter(cart__user=request.user)
            .aggregate(Sum('quantity'))['quantity__sum'] or 0
        )
        context['cart_count'] = cart_count
        
        can_review = OrderItem.objects.filter(
            order__user=request.user,
            order__status='Delivered',
            product=product
        ).exists()
        
        has_reviewed = product.reviews.filter(user=request.user).exists()
        
        context['can_review'] = can_review and not has_reviewed
        context['has_reviewed'] = has_reviewed

        
        # Get active coupons for display
        active_coupons = Coupon.objects.filter(is_active=True, valid_from__lte=timezone.now(), valid_to__gte=timezone.now())
        context['available_coupons'] = active_coupons

    # Comparison Data
    compare_ids = request.session.get('compare_list', [])
    context['current_compare_ids'] = [int(pid) for pid in compare_ids if str(pid).isdigit()]
    context['current_compare_products'] = Product.objects.filter(id__in=compare_ids, is_active=True, is_deleted=False)
    
    # Calculate savings based on display_price
    context['savings'] = product.price - product.display_price

    return render(request, 'product_details.html', context)

@login_required
@never_cache
def validate_coupon_product(request):
    """AJAX view to validate a coupon for a specific product price on the detail page."""
    import json
    from decimal import Decimal
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'})
        
    try:
        data = json.loads(request.body)
        code = data.get('code', '').strip()
        product_uuid = data.get('product_uuid')
    except:
        return JsonResponse({'success': False, 'error': 'Invalid data'})
        
    if not code:
        return JsonResponse({'success': False, 'error': 'Please enter a coupon code'})
        
    product = get_object_or_404(Product, uuid=product_uuid)
    price = product.display_price # Price after product/category offers
    
    try:
        coupon = Coupon.objects.get(code__iexact=code, is_active=True)
    except Coupon.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Invalid or expired coupon code'})
        
    # Basic validation (can't check cart subtotal yet, so we check product price)
    if price < coupon.min_purchase_amount:
        return JsonResponse({'success': False, 'error': f'Minimum purchase of ₹{coupon.min_purchase_amount} required'})
        
    if request.user.is_authenticated:
        is_valid, error_message = coupon.is_valid_for_user(request.user)
        if not is_valid:
            return JsonResponse({'success': False, 'error': error_message})
    
    # Calculate discount
    discount = Decimal('0')
    if coupon.discount_type == 'percentage':
        discount = (price * coupon.discount_value) / Decimal('100')
        if coupon.max_discount_amount:
            discount = min(discount, coupon.max_discount_amount)
    else:
        discount = coupon.discount_value
        
    final_price = max(Decimal('0'), price - discount)
    
    return JsonResponse({
        'success': True,
        'final_price': str(final_price),
        'discount_amount': str(discount),
        'message': f'Coupon {coupon.code} applied! Save an extra ₹{discount}'
    })
