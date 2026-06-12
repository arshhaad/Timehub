from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
from django.contrib import messages
from django.db.models import Sum
from user_apps.core.models import Product


# landing page for non logged users
def landing_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    products = Product.objects.filter(
        is_active=True,
        is_deleted=False
    )[:4]

    context = {
        'products': products
    }

    return render(request, "core/landing.html", context)


@never_cache
def home_view(request):
    from django.core.cache import cache
    import logging
    logger = logging.getLogger(__name__)

    # 1. Determine Cache Key based on authentication
    if request.user.is_authenticated:
        cache_key = f"home_recommendations_user_{request.user.id}"
    else:
        cache_key = "home_recommendations_anon"

    # 2. Try to get recommendations from Redis Cache
    recommended_ids = None
    try:
        recommended_ids = cache.get(cache_key)
    except Exception as e:
        logger.error(f"Redis cache error on home view: {e}")

    # 3. If cache miss, compute recommendations
    if recommended_ids is None:
        if request.user.is_authenticated:
            # Personalization logic: get user interaction profiles
            from user_apps.core.models import CartItem, WishlistItem, OrderItem, ComparisonHistory
            
            interacted_pids = set()
            try:
                cart_items = CartItem.objects.filter(cart__user=request.user).values_list('product_id', flat=True)
                interacted_pids.update(cart_items)
            except Exception:
                pass
            try:
                wish_items = WishlistItem.objects.filter(wishlist__user=request.user).values_list('product_id', flat=True)
                interacted_pids.update(wish_items)
            except Exception:
                pass
            try:
                order_items = OrderItem.objects.filter(order__user=request.user).values_list('product_id', flat=True)
                interacted_pids.update(order_items)
            except Exception:
                pass
            try:
                comp_items = ComparisonHistory.objects.filter(user=request.user).values_list('product_id', flat=True)
                interacted_pids.update(comp_items)
            except Exception:
                pass

            # Gather preferences
            pref_collections = set()
            pref_brands = set()
            pref_genders = set()
            pref_occasions = set()
            
            if interacted_pids:
                interacted_products = Product.objects.filter(id__in=interacted_pids)
                for p in interacted_products:
                    if p.collection_id:
                        pref_collections.add(p.collection_id)
                    if p.brand:
                        pref_brands.add(p.brand)
                    if p.gender:
                        pref_genders.add(p.gender)
                    if p.occasion:
                        pref_occasions.add(p.occasion)

            # Retrieve active candidate products not already in interacted set
            candidates = Product.objects.filter(is_active=True, is_deleted=False).exclude(id__in=interacted_pids)
            
            scored_candidates = []
            for candidate in candidates:
                score = 0
                if candidate.collection_id in pref_collections:
                    score += 3
                if candidate.brand in pref_brands:
                    score += 2
                if candidate.gender in pref_genders:
                    score += 2
                if candidate.occasion in pref_occasions:
                    score += 1
                scored_candidates.append((score, candidate))

            # Sort by score, then by rating as tie breaker
            scored_candidates.sort(key=lambda x: (x[0], x[1].rating), reverse=True)
            recommended_products = [item[1] for item in scored_candidates[:4]]
            
            # Fill with fallbacks if less than 4 recommendations found
            if len(recommended_products) < 4:
                needed = 4 - len(recommended_products)
                exclude_ids = [p.id for p in recommended_products] + list(interacted_pids)
                fallbacks = Product.objects.filter(
                    is_active=True, is_deleted=False
                ).exclude(id__in=exclude_ids).order_by('-rating', '-created_at')[:needed]
                recommended_products.extend(list(fallbacks))
        else:
            # Anonymous users: Top rated/popular products
            recommended_products = Product.objects.filter(
                is_active=True, is_deleted=False
            ).order_by('-rating', '-created_at')[:4]

        recommended_ids = [p.id for p in recommended_products]
        try:
            cache.set(cache_key, recommended_ids, timeout=86400)
        except Exception as e:
            logger.error(f"Redis cache set error on home view: {e}")

    # 4. Fetch the products keeping order and safety checks
    products = list(Product.objects.filter(id__in=recommended_ids, is_active=True, is_deleted=False))
    preserved = {pid: pos for pos, pid in enumerate(recommended_ids)}
    products.sort(key=lambda p: preserved.get(p.id, 999))
    #Sort the product based on the recomenProduct 
    # Pad if we have less than 4 items (e.g. if some got deleted/deactivated after caching)
    if len(products) < 4:
        needed = 4 - len(products)
        exclude_ids = [p.id for p in products]
        fallbacks = Product.objects.filter(
            is_active=True, is_deleted=False
        ).exclude(id__in=exclude_ids).order_by('-rating', '-created_at')[:needed]
        products.extend(list(fallbacks))

    context = {
        'products': products,
        'wishlist_product_ids': [],
        'cart_count': 0,
    }

    if request.user.is_authenticated:
        from user_apps.core.models import WishlistItem, CartItem, Notification

        unread_notifications = Notification.objects.filter(
            user=request.user,
            is_read=False
        )

        for notification in unread_notifications:
            messages.success(request, notification.message)
            notification.is_read = True
            notification.save(update_fields=["is_read"])

        wishlist_ids = list(
            WishlistItem.objects.filter(
                wishlist__user=request.user
            ).values_list('product_id', flat=True)
        )

        context['wishlist_product_ids'] = wishlist_ids

        cart_count = (
            CartItem.objects.filter(cart__user=request.user)
            .aggregate(Sum('quantity'))['quantity__sum'] or 0
        )

        context['cart_count'] = cart_count

    return render(request, 'core/home.html', context)
# about page
@never_cache
def about_view(request):
    return render(request, 'core/about.html')