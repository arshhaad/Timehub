from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from seller.models import Seller
from user_apps.core.models import Product, Wallet, WalletTransaction, Notification
from django.db import transaction

def is_admin(user):
    return user.is_authenticated and user.is_superuser

@user_passes_test(is_admin)
def seller_profiles(request):
    sellers = Seller.objects.all().select_related('user', 'user__wallet').order_by('-created_at')
    return render(request, 'seller_profiles.html', {
        'sellers': sellers,
        'active_menu': 'seller_profiles'
    })

@user_passes_test(is_admin)
def seller_products(request):
    seller_id = request.GET.get('seller_id')
    products = Product.objects.filter(seller__isnull=False).select_related('seller').order_by('-created_at')
    
    selected_seller = None
    if seller_id:
        selected_seller = get_object_or_404(Seller, id=seller_id)
        products = products.filter(seller=selected_seller)
        
    return render(request, 'seller_product.html', {
        'products': products,
        'selected_seller': selected_seller,
        'active_menu': 'seller_products'
    })

@user_passes_test(is_admin)
def seller_product_details(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        reason = request.POST.get('reason', '').strip()
        
        if action == 'approve':
            product.approval_status = 'Approved'
            product.is_active = True
            product.admin_note = reason
            product.save()
            
            Notification.objects.create(
                user=product.seller.user,
                message=f"Your product '{product.name}' has been approved by TimeHub!"
            )
            messages.success(request, f"Product '{product.name}' approved.")
            
        elif action == 'reject':
            if not reason:
                messages.error(request, "Please provide a reason for rejection.")
                return redirect('admin_seller_product_details', product_id=product_id)
                
            product.approval_status = 'Rejected'
            product.is_active = False
            product.admin_note = reason
            product.save()
            
            Notification.objects.create(
                user=product.seller.user,
                message=f"Your product '{product.name}' was rejected. Reason: {reason}"
            )
            messages.warning(request, f"Product '{product.name}' rejected.")
            
        return redirect('admin_seller_products')
        
    return render(request, 'seller_product_details.html', {
        'product': product
    })

@user_passes_test(is_admin)
def seller_action(request, seller_id):
    seller = get_object_or_404(Seller, id=seller_id)
    action = request.POST.get('action')
    message = request.POST.get('message', '').strip()
    
    if action == 'block':
        seller.is_blocked = True
        seller.save()
        messages.success(request, f"Seller {seller.store_name} has been blocked.")
        
    elif action == 'unblock':
        seller.is_blocked = False
        seller.save()
        messages.success(request, f"Seller {seller.store_name} has been unblocked.")
        
    elif action == 'remove':
        # Soft delete or hard delete? User said "remove". 
        # Usually best to deactivate the user or mark as deleted.
        # For now, let's just deactivate the user.
        seller.user.is_active = False
        seller.user.save()
        messages.error(request, f"Seller {seller.store_name} account has been deactivated.")
        
    elif action == 'warn':
        if not message:
            messages.error(request, "Please provide a warning message.")
        else:
            Notification.objects.create(
                user=seller.user,
                message=f"ADMIN WARNING: {message}"
            )
            messages.info(request, f"Warning sent to {seller.store_name}.")
            
    return redirect('admin_seller_profiles')
