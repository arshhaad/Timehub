from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
from user_apps.core.models import Product

# Create your views here.

# landing page
@never_cache
def landing_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    products = Product.objects.filter(is_active=True, is_deleted=False)[:4]
    
    context = {'products': products}
    if request.user.is_authenticated:
        from user_apps.core.models import WishlistItem, CartItem
        from django.db.models import Sum
        wishlist_product_ids = WishlistItem.objects.filter(wishlist__user=request.user).values_list('product_id', flat=True)
        context['wishlist_product_ids'] = list(wishlist_product_ids)
        
        # Add cart count
        cart_count = CartItem.objects.filter(cart__user=request.user).aggregate(Sum('quantity'))['quantity__sum'] or 0
        context['cart_count'] = cart_count
        
    return render(request, "core/landing.html", context)


# authenticated home dashboard
@never_cache
def home_view(request):
    products = Product.objects.filter(is_active=True, is_deleted=False)[:4]
    
    context = {'products': products}
    if request.user.is_authenticated:
        from user_apps.core.models import WishlistItem, CartItem
        from django.db.models import Sum
        wishlist_product_ids = WishlistItem.objects.filter(wishlist__user=request.user).values_list('product_id', flat=True)
        context['wishlist_product_ids'] = list(wishlist_product_ids)
        
        # Add cart count
        cart_count = CartItem.objects.filter(cart__user=request.user).aggregate(Sum('quantity'))['quantity__sum'] or 0
        context['cart_count'] = cart_count
        
    return render(request, 'core/home.html', context)
