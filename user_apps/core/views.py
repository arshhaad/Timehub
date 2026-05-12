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

    # add wishlist and cart details if user logged in
    if request.user.is_authenticated:
        from user_apps.core.models import WishlistItem, CartItem
        from django.db.models import Sum

        wishlist_product_ids = WishlistItem.objects.filter(
            wishlist__user=request.user
        ).values_list('product_id', flat=True)

        context['wishlist_product_ids'] = list(wishlist_product_ids)

        # calculate total cart quantity
        cart_count = CartItem.objects.filter(
            cart__user=request.user
        ).aggregate(Sum('quantity'))['quantity__sum'] or 0

        context['cart_count'] = cart_count

    return render(request, "core/landing.html", context)


# home page after login
@never_cache
def home_view(request):
    products = Product.objects.filter(
        is_active=True,
        is_deleted=False
    )[:4]

    context = {
        'products': products
    }

    # add wishlist and cart details
    if request.user.is_authenticated:
        from user_apps.core.models import WishlistItem, CartItem, Notification
        from django.db.models import Sum
        from django.contrib import messages

        # --- Referral/Cashback Messages Integration ---
        # Fetch unread notifications for the user and show them as flash messages
        unread_notifications = Notification.objects.filter(user=request.user, is_read=False)
        for notification in unread_notifications:
            messages.success(request, notification.message)
            notification.is_read = True
            notification.save()

        wishlist_product_ids = WishlistItem.objects.filter(
            wishlist__user=request.user
        ).values_list('product_id', flat=True)

        context['wishlist_product_ids'] = list(wishlist_product_ids)

        # calculate cart item count
        cart_count = CartItem.objects.filter(
            cart__user=request.user
        ).aggregate(Sum('quantity'))['quantity__sum'] or 0

        context['cart_count'] = cart_count

    return render(request, 'core/home.html', context)


# about page
@never_cache
def about_view(request):
    return render(request, 'core/about.html')