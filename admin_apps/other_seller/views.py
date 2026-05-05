from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from seller.models import Seller, SellerEarnings
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
def seller_earnings(request):
    from django.db.models import Sum, Q
    seller_id = request.GET.get('seller_id')
    status = request.GET.get('status', 'All')
    
    earnings = SellerEarnings.objects.all().select_related('seller', 'order_item', 'order_item__product').order_by('-created_at')
    
    if seller_id:
        earnings = earnings.filter(seller_id=seller_id)
    if status != 'All':
        earnings = earnings.filter(status=status)
        
    # Annotate sellers with their total approved earnings
    sellers = Seller.objects.annotate(
        total_paid=Sum('earnings__amount', filter=Q(earnings__status='Approved'))
    ).order_by('-created_at')
    
    return render(request, 'seller_earnings.html', {
        'earnings': earnings,
        'sellers': sellers,
        'selected_seller_id': int(seller_id) if seller_id else None,
        'selected_status': status,
        'active_menu': 'seller_earnings'
    })

@user_passes_test(is_admin)
def process_earning(request, earning_id):
    earning = get_object_or_404(SellerEarnings, id=earning_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        new_amount = request.POST.get('amount')
        admin_note = request.POST.get('admin_note', '').strip()
        
        if new_amount:
            try:
                from decimal import Decimal
                earning.amount = Decimal(new_amount)
            except:
                messages.error(request, "Invalid amount format.")
                return redirect('admin_seller_earnings')
            
        earning.admin_note = admin_note
        
        if action == 'approve':
            with transaction.atomic():
                earning.status = 'Approved'
                earning.save()
                
                # Credit to seller's wallet
                wallet, _ = Wallet.objects.get_or_create(user=earning.seller.user)
                wallet.balance += earning.amount
                wallet.save()
                
                WalletTransaction.objects.create(
                    wallet=wallet,
                    transaction_type='Credit',
                    amount=earning.amount,
                    description=f"Earnings from Order Item #{earning.order_item.id} ({earning.order_item.product.name})"
                )
                
                Notification.objects.create(
                    user=earning.seller.user,
                    message=f"Your earnings of ₹{earning.amount} for '{earning.order_item.product.name}' have been approved and credited to your wallet."
                )
                
                messages.success(request, f"Earning approved and ₹{earning.amount} credited to {earning.seller.store_name}.")
                
        elif action == 'reject':
            earning.status = 'Rejected'
            earning.save()
            
            Notification.objects.create(
                user=earning.seller.user,
                message=f"Your earnings for '{earning.order_item.product.name}' were rejected. Note: {admin_note}"
            )
            messages.warning(request, "Earning rejected.")
            
        elif action == 'update':
            earning.save()
            messages.info(request, "Earning updated successfully.")
            
    return redirect('admin_seller_earnings')

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
