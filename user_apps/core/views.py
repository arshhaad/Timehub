from collections import Counter

from django.contrib import messages
from django.core.cache import cache
from django.db.models import Sum
from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache

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


# home page after login
@never_cache
def home_view(request):
    best_seller_products = Product.objects.filter(
        is_active=True,
        is_deleted=False,
    ).order_by('-created_at')[:4]

    best_seller_ids = list(best_seller_products.values_list('id', flat=True))

    context = {
        'products': best_seller_products,
    }

    if request.user.is_authenticated:
        from user_apps.core.models import WishlistItem, CartItem, Notification

        # unread notifications
        unread_notifications = Notification.objects.filter(
            user=request.user,
            is_read=False
        )

        for notification in unread_notifications:
            messages.success(request, notification.message)
            notification.is_read = True
            notification.save(update_fields=["is_read"])

        # wishlist ids
        wishlisted_ids = list(
            WishlistItem.objects.filter(
                wishlist__user=request.user
            ).values_list('product_id', flat=True)
        )

        context['wishlist_product_ids'] = wishlisted_ids

        # cart count
        cart_count = (
            CartItem.objects.filter(cart__user=request.user)
            .aggregate(Sum('quantity'))['quantity__sum'] or 0
        )

        context['cart_count'] = cart_count

        # recommendations cache
        cache_key = f'home_recommendations_user_{request.user.id}'
        recommended_data = cache.get(cache_key)

        if recommended_data is None:
            purchased_products = list(
                Product.objects.filter(
                    orderitem__order__user=request.user,
                    orderitem__order__status='Delivered',
                    is_active=True,
                    is_deleted=False,
                ).distinct()
            )

            wishlisted_products = list(
                Product.objects.filter(
                    id__in=wishlisted_ids,
                    is_active=True,
                    is_deleted=False,
                )
            )

            # weighted taste profile
            taste_profile_products = (purchased_products * 2) + wishlisted_products

            if taste_profile_products:
                brand_counter = Counter(
                    p.brand for p in taste_profile_products if p.brand
                )
                gender_counter = Counter(
                    p.gender for p in taste_profile_products if p.gender
                )
                occasion_counter = Counter(
                    p.occasion for p in taste_profile_products if p.occasion
                )
                material_counter = Counter(
                    p.strap_material for p in taste_profile_products if p.strap_material
                )
                function_counter = Counter(
                    p.function for p in taste_profile_products if p.function
                )
                collection_counter = Counter(
                    p.collection_id for p in taste_profile_products if p.collection_id
                )

                already_seen_ids = (
                    set(p.id for p in taste_profile_products) |
                    set(best_seller_ids)
                )

                candidates = Product.objects.filter(
                    is_active=True,
                    is_deleted=False
                ).exclude(id__in=already_seen_ids)

                scored = []

                for candidate in candidates:
                    score = 0

                    if candidate.brand and brand_counter:
                        score += (
                            brand_counter.get(candidate.brand, 0) /
                            max(brand_counter.values())
                        ) * 3

                    if candidate.gender and gender_counter:
                        score += (
                            gender_counter.get(candidate.gender, 0) /
                            max(gender_counter.values())
                        ) * 2

                    if candidate.occasion and occasion_counter:
                        score += (
                            occasion_counter.get(candidate.occasion, 0) /
                            max(occasion_counter.values())
                        ) * 1

                    if candidate.strap_material and material_counter:
                        score += (
                            material_counter.get(candidate.strap_material, 0) /
                            max(material_counter.values())
                        ) * 1

                    if candidate.function and function_counter:
                        score += (
                            function_counter.get(candidate.function, 0) /
                            max(function_counter.values())
                        ) * 1

                    if candidate.collection_id and collection_counter:
                        score += (
                            collection_counter.get(candidate.collection_id, 0) /
                            max(collection_counter.values())
                        ) * 2

                    scored.append((score, candidate.rating or 0, candidate))

                scored.sort(
                    key=lambda x: (x[0], x[1]),
                    reverse=True
                )

                recommended_watches = [item[2] for item in scored[:4]]
                label = "Picked For You"

            else:
                recommended_watches = list(
                    Product.objects.filter(
                        is_active=True,
                        is_deleted=False
                    )
                    .exclude(id__in=best_seller_ids)
                    .order_by('-rating')[:4]
                )

                label = "You Might Like"

            recommended_data = {
                'ids': [w.id for w in recommended_watches],
                'label': label,
            }

            cache.set(cache_key, recommended_data, 21600)

        watch_lookup = {
            w.id: w
            for w in Product.objects.filter(id__in=recommended_data['ids'])
        }

        recommended_watches = [
            watch_lookup[wid]
            for wid in recommended_data['ids']
            if wid in watch_lookup
        ]

        context['recommended_products'] = recommended_watches
        context['recommendation_label'] = recommended_data.get(
            'label',
            'Picked For You'
        )

    else:
        cache_key = 'home_recommendations_guest'
        guest_ids = cache.get(cache_key)

        if guest_ids is None:
            guest_watches = list(
                Product.objects.filter(
                    is_active=True,
                    is_deleted=False
                )
                .exclude(id__in=best_seller_ids)
                .order_by('-rating')[:4]
            )

            guest_ids = [w.id for w in guest_watches]
            cache.set(cache_key, guest_ids, 21600)

        watch_lookup = {
            w.id: w
            for w in Product.objects.filter(id__in=guest_ids)
        }

        guest_watches = [
            watch_lookup[wid]
            for wid in guest_ids
            if wid in watch_lookup
        ]

        context['recommended_products'] = guest_watches
        context['recommendation_label'] = "Trending Now"

    return render(request, 'core/home.html', context)


# about page
@never_cache
def about_view(request):
    return render(request, 'core/about.html')