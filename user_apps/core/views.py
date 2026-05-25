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
    best_seller_products = Product.objects.filter(
        is_active=True,
        is_deleted=False
    ).order_by('-created_at')[:4]

    context = {
        'products': best_seller_products,
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