from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .models import Address
from .forms import AddressForm, UserEditForm
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from django.http import JsonResponse
import json
from decimal import Decimal
from user_apps.core.models import Cart, CartItem, Product, WishlistItem, Wishlist, Order


@login_required
@never_cache
def dashboard(request):
    user = request.user
    
    # Fetch actual stats
    total_orders = user.orders.count()
    wishlist, _ = Wishlist.objects.get_or_create(user=user)
    saved_items = wishlist.items.count()
    
    stats = {
        'total_orders': total_orders,
        'saved_items': saved_items,
        'reward_points': 0, # Model not existing yet
    }
    
    recent_orders = user.orders.order_by('-created_at')[:5]
    
    context = {
        'user': user,
        'stats': stats,
        'recent_orders': recent_orders,
        'referral_code': 'TIMEHUB-JS2024', # Mock value
    }
    
    return render(request, 'user_dashboard.html', context)


@login_required
@never_cache
def address_list(request):
    addresses = Address.objects.filter(user=request.user)
    return render(request, 'address.html', {'addresses': addresses})


@login_required
@never_cache
def add_address(request):
    if request.method == 'POST':
        form = AddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user

            # ✅ Handle default address
            if address.is_default:
                Address.objects.filter(user=request.user).update(is_default=False)

            address.save()
            return redirect('address_list')
    else:
        form = AddressForm()

    return render(request, 'address_form.html', {'form': form})



@login_required
@never_cache
def edit_address(request, id):
    address = get_object_or_404(Address, id=id, user=request.user)

    if request.method == 'POST':
        form = AddressForm(request.POST, instance=address)
        if form.is_valid():
            address = form.save(commit=False)

            if address.is_default:
                Address.objects.filter(user=request.user).exclude(id=id).update(is_default=False)

            address.save()
            return redirect('address_list')
    else:
        form = AddressForm(instance=address)

    return render(request, 'address_form.html', {'form': form})

@login_required
@never_cache
def delete_address(request, id):
    address = get_object_or_404(Address, id=id, user=request.user)
    address.delete()
    return redirect('address_list')

@login_required
@never_cache
def toggle_default_address(request, id):
    address = get_object_or_404(Address, id=id, user=request.user)
    
    if not address.is_default:
        # Unset others and set this one
        Address.objects.filter(user=request.user, is_default=True).update(is_default=False)
        address.is_default = True
        address.save()
    else:
        # Toggle off
        address.is_default = False
        address.save()
        
    return redirect('address_list')


@login_required
@never_cache
def edit_profile(request):
    if request.method == 'POST':
        form = UserEditForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect('user_dashboard')
    else:
        form = UserEditForm(instance=request.user)

    return render(request, 'edit_profile.html', {'form': form})


@login_required
@never_cache
def account_edit(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Important!
            messages.success(request, 'Your password was successfully updated!')
            return redirect('user_dashboard')
        else:
            messages.error(request, 'Please correct the error below.')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'account_edit.html', {
        'form': form
    })

@login_required
@never_cache
def cart_view(request):
    cart, created = Cart.objects.get_or_create(user=request.user)
    items = cart.items.select_related('product').all()
    subtotal = sum(item.total_price for item in items)
    tax = subtotal * Decimal('0.05') # assuming 5% tax
    total = subtotal + tax
    
    has_stock_issues = False
    for item in items:
        if item.product.stock == 0 or not item.product.is_active or item.product.is_deleted or item.product.collection.is_deleted:
            has_stock_issues = True
            break
        elif item.quantity > item.product.stock:
            has_stock_issues = True
            break
            
    return render(request, 'cart.html', {
        'cart': cart,
        'items': items,
        'subtotal': subtotal,
        'tax': tax,
        'total': total,
        'has_stock_issues': has_stock_issues
    })

@login_required
def add_to_cart(request, product_id):
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        
        # Prevent adding blocked/unlisted products
        if not product.is_active or product.is_deleted or product.collection.is_deleted:
            return JsonResponse({'success': False, 'error': 'Product is currently unavailable'})
            
        if product.stock <= 0:
            return JsonResponse({'success': False, 'error': 'Product is out of stock'})
            
        cart, created = Cart.objects.get_or_create(user=request.user)
        
        # Check if item exists in cart
        cart_item, item_created = CartItem.objects.get_or_create(
            cart=cart, 
            product=product,
            defaults={'quantity': 1}
        )
        
        # Max quantity limit of 10 items
        MAX_QTY = 10
        
        if not item_created:
            if cart_item.quantity < min(product.stock, MAX_QTY):
                cart_item.quantity += 1
                cart_item.save()
            elif cart_item.quantity >= MAX_QTY:
                return JsonResponse({'success': False, 'error': f'Maximum quantity per item is {MAX_QTY}'})
            else:
                return JsonResponse({'success': False, 'error': f'Only {product.stock} items available in stock. You already have {cart_item.quantity} in your cart.'})
                
        # Remove from wishlist when added to cart
        if hasattr(request.user, 'wishlist'):
            WishlistItem.objects.filter(wishlist=request.user.wishlist, product=product).delete()
                
        # Total cart items count
        cart_count = sum(item.quantity for item in cart.items.all())
                
        return JsonResponse({'success': True, 'message': 'Added to cart', 'cart_count': cart_count})
        
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def update_cart(request, item_id):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            action = data.get('action')
            cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
            product = cart_item.product
            
            MAX_QTY = 10
            
            if action == 'increase':
                if not product.is_active or product.is_deleted or product.collection.is_deleted:
                     return JsonResponse({'success': False, 'error': 'Product is currently unavailable'})
                
                if cart_item.quantity < min(product.stock, MAX_QTY):
                    cart_item.quantity += 1
                    cart_item.save()
                elif cart_item.quantity >= MAX_QTY:
                    return JsonResponse({'success': False, 'error': 'Maximum quantity limit reached'})
                else:
                    return JsonResponse({'success': False, 'error': 'Not enough stock'})
            
            elif action == 'decrease':
                if cart_item.quantity > 1:
                    cart_item.quantity -= 1
                    cart_item.save()
                else:
                    return JsonResponse({'success': False, 'error': 'Minimum quantity is 1. Use remove instead.'})
            else:
                return JsonResponse({'success': False, 'error': 'Invalid action'})
                
            # Recalculate totals
            cart = cart_item.cart
            items = cart.items.select_related('product').all()
            subtotal = sum(item.total_price for item in items)
            tax = subtotal * Decimal('0.08')
            total = subtotal + tax
            cart_count = sum(item.quantity for item in items)
            
            return JsonResponse({
                'success': True,
                'cart_count': cart_count,
                'item_total': str(cart_item.total_price),
                'item_quantity': cart_item.quantity,
                'subtotal': str(subtotal),
                'tax': str(round(tax, 2)),
                'total': str(round(total, 2))
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
            
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def remove_from_cart(request, item_id):
    # Ensure the item belongs to the user's cart
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    cart_item.delete()
    messages.success(request, 'Item removed from cart.')
    return redirect('cart_view')

@login_required
@never_cache
def wishlist_view(request):
    wishlist, created = Wishlist.objects.get_or_create(user=request.user)
    items = wishlist.items.select_related('product').all()
    return render(request, 'wishlist.html', {
        'items': items
    })

def toggle_wishlist(request, product_id):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Please login to modify your wishlist.'})
        
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        wishlist, created = Wishlist.objects.get_or_create(user=request.user)
        
        wishlist_item = WishlistItem.objects.filter(wishlist=wishlist, product=product).first()
        
        if wishlist_item:
            wishlist_item.delete()
            action = 'removed'
        else:
            # Only check availability when ADDING (stock is okay for wishlist)
            if not product.is_active or product.is_deleted or product.collection.is_deleted:
                return JsonResponse({'success': False, 'error': 'Product is currently unavailable'})
                
            WishlistItem.objects.create(wishlist=wishlist, product=product)
            action = 'added'
            
        wishlist_count = wishlist.items.count()
        return JsonResponse({'success': True, 'action': action, 'wishlist_count': wishlist_count})
        
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def remove_wishlist_item(request, item_id):
    if request.method == 'POST':
        wishlist_item = get_object_or_404(WishlistItem, id=item_id, wishlist__user=request.user)
        wishlist_item.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def save_for_later(request, item_id):
    if request.method == 'POST':
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        product = cart_item.product
        
        # Add to wishlist
        wishlist, created = Wishlist.objects.get_or_create(user=request.user)
        WishlistItem.objects.get_or_create(wishlist=wishlist, product=product)
        
        # Delete from cart
        cart_item.delete()
        
        # Recalculate totals
        cart = request.user.cart
        items = cart.items.select_related('product').all()
        subtotal = sum(item.total_price for item in items)
        tax = subtotal * Decimal('0.08')
        total = subtotal + tax
        cart_count = sum(item.quantity for item in items)
        
        return JsonResponse({
            'success': True,
            'cart_count': cart_count,
            'subtotal': str(subtotal),
            'tax': str(round(tax, 2)),
            'total': str(round(total, 2))
        })
    return JsonResponse({'success': False, 'error': 'Invalid request'})
