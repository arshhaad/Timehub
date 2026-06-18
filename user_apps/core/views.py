from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
from django.contrib import messages
from django.db.models import Sum
from user_apps.core.models import Product



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

    # Cache Key based on authentication
    if request.user.is_authenticated:
        cache_key = f"home_recommendations_user_{request.user.id}"
    else:
        cache_key = "home_recommendations_anon"

  # Try to get recommendations from Redis Cache
    recommended_ids = None
    try:
        recommended_ids = cache.get(cache_key)
    except Exception as e:
        logger.error(f"Redis cache error on home view: {e}")

    if recommended_ids is None:
        if request.user.is_authenticated:
            from user_apps.core.models import (
                CartItem,
                WishlistItem,
                OrderItem,
                ComparisonHistory,
        )   

        interacted_pids = set()

        sources = [
            (CartItem, {"cart__user": request.user}),
            (WishlistItem, {"wishlist__user": request.user}),
            (OrderItem, {"order__user": request.user}),
            (ComparisonHistory, {"user": request.user}),
        ]

        for model, filters in sources:
            try:
                product_ids = model.objects.filter(**filters).values_list(
                    "product_id", flat=True
                )
                interacted_pids.update(product_ids)
            except Exception:
                pass

        # Gather preferences
        pref_collections = set()
        pref_brands = set()
        pref_genders = set()
        pref_occasions = set()

        if interacted_pids:
            interacted_products = Product.objects.filter(id__in=interacted_pids)

            for product in interacted_products:
                if product.collection_id:
                    pref_collections.add(product.collection_id)

                if product.brand:
                    pref_brands.add(product.brand)

                if product.gender:
                    pref_genders.add(product.gender)

                if product.occasion:
                    pref_occasions.add(product.occasion)

            
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

            # Sort by score
            scored_candidates.sort(key=lambda x: (x[0], x[1].rating), reverse=True)
            recommended_products = [item[1] for item in scored_candidates[:4]]
            
            if len(recommended_products) < 4:
                needed = 4 - len(recommended_products)
                exclude_ids = [p.id for p in recommended_products] + list(interacted_pids)
                fallbacks = Product.objects.filter(
                    is_active=True, is_deleted=False
                ).exclude(id__in=exclude_ids).order_by('-rating', '-created_at')[:needed]
                recommended_products.extend(list(fallbacks))
        else:
            recommended_products = Product.objects.filter(
                is_active=True, is_deleted=False
            ).order_by('-rating', '-created_at')[:4]

        recommended_ids = [p.id for p in recommended_products]
        try:
            cache.set(cache_key, recommended_ids, timeout=86400)
        except Exception as e:
            logger.error(f"Redis cache set error on home view: {e}")

    products = list(Product.objects.filter(id__in=recommended_ids, is_active=True, is_deleted=False))
    preserved = {pid: pos for pos, pid in enumerate(recommended_ids)}
    products.sort(key=lambda p: preserved.get(p.id, 999))
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