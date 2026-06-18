"""Admin Seller Management Views."""

from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages

from seller.models import Seller, SellerEarnings
from user_apps.core.models import Product, Wallet, WalletTransaction, Notification




def is_admin(user):
    """Simple check to ensure the user is an authenticated superuser."""
    return user.is_authenticated and user.is_superuser




@user_passes_test(is_admin)
def seller_profiles(request):
    """Lists all registered sellers with their store names and linked user accounts."""
    sellers = Seller.objects.all().select_related('user', 'user__wallet').order_by('-created_at')
    return render(request, 'seller_profiles.html', {
        'sellers': sellers,
        'active_menu': 'seller_profiles'
    })


@user_passes_test(is_admin)
def seller_action(request, seller_id):
    """Perform bulk actions on a seller account."""
    seller = get_object_or_404(Seller, id=seller_id)
    action = request.POST.get('action')
    msg = request.POST.get('message', '').strip()
    
    if action == 'block':
        seller.is_blocked = True
        seller.save()
        messages.success(request, f"Seller '{seller.store_name}' blocked.")
        
    elif action == 'unblock':
        seller.is_blocked = False
        seller.save()
        messages.success(request, f"Seller '{seller.store_name}' unblocked.")
        
    elif action == 'remove':
        # Safety: Deactivate user rather than deleting data
        seller.user.is_active = False
        seller.user.save()
        messages.error(request, f"Account for '{seller.store_name}' deactivated.")
        
    elif action == 'warn':
        if not msg:
            messages.error(request, "Please enter a message for the warning.")
        else:
            Notification.objects.create(user=seller.user, message=f"ADMIN WARNING: {msg}")
            messages.info(request, f"Warning sent to {seller.store_name}.")
            
    return redirect('admin_seller_profiles')




@user_passes_test(is_admin)
def seller_products(request):
    """List all products uploaded by partner sellers."""
    s_id = request.GET.get('seller_id')
    prods = Product.objects.filter(seller__isnull=False).select_related('seller').order_by('-created_at')
    
    selected_seller = None
    if s_id:
        selected_seller = get_object_or_404(Seller, id=s_id)
        prods = prods.filter(seller=selected_seller)
        
    return render(request, 'seller_product.html', {
        'products': prods,
        'selected_seller': selected_seller,
        'active_menu': 'seller_products'
    })


@user_passes_test(is_admin)
def seller_product_details(request, product_id):
    """Review and approve/reject seller product submissions."""
    p = get_object_or_404(Product, id=product_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        note = request.POST.get('reason', '').strip()
        
        # 1. Approval Logic
        if action == 'approve':
            p.approval_status = 'Approved'
            p.is_active = True
            p.admin_note = note
            p.save()
            
            Notification.objects.create(
                user=p.seller.user, 
                message=f"Success: Your product '{p.name}' is now live on TimeHub!"
            )
            messages.success(request, f"'{p.name}' approved.")
            
        # 2. Rejection Logic
        elif action == 'reject':
            if not note:
                messages.error(request, "A reason is required for rejection.")
                return redirect('admin_seller_product_details', product_id=product_id)
                
            p.approval_status = 'Rejected'
            p.is_active = False
            p.admin_note = note
            p.save()
            
            Notification.objects.create(
                user=p.seller.user, 
                message=f"Action Required: Your product '{p.name}' was rejected. Reason: {note}"
            )
            messages.warning(request, f"'{p.name}' rejected.")
            
        return redirect('admin_seller_products')
        
    return render(request, 'seller_product_details.html', {'product': p})




@user_passes_test(is_admin)
def seller_earnings(request):
    """Monitor and process partner seller payouts."""
    s_id = request.GET.get('seller_id')
    status = request.GET.get('status', 'All')
    
    earnings = SellerEarnings.objects.all().select_related('seller', 'order_item__product').order_by('-created_at')
    
    if s_id:
        earnings = earnings.filter(seller_id=s_id)
    if status != 'All':
        earnings = earnings.filter(status=status)
        

    sellers_with_stats = Seller.objects.annotate(
        total_paid=Sum('earnings__amount', filter=Q(earnings__status='Approved'))
    ).order_by('-created_at')
    
    return render(request, 'seller_earnings.html', {
        'earnings': earnings,
        'sellers': sellers_with_stats,
        'selected_seller_id': int(s_id) if s_id else None,
        'selected_status': status,
        'active_menu': 'seller_earnings'
    })


@user_passes_test(is_admin)
def process_earning(request, earning_id):
    """Approve or reject individual seller earning records."""
    earn = get_object_or_404(SellerEarnings, id=earning_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        amt_str = request.POST.get('amount')
        note = request.POST.get('admin_note', '').strip()
        

        if amt_str:
            try:
                earn.amount = Decimal(amt_str)
            except:
                messages.error(request, "Invalid numeric format for amount.")
                return redirect('admin_seller_earnings')
            
        earn.admin_note = note
        
        # 2. Status Actions
        if action == 'approve':
            with transaction.atomic():
                earn.status = 'Approved'
                earn.save()
                

                wallet, _ = Wallet.objects.get_or_create(user=earn.seller.user)
                wallet.balance += earn.amount
                wallet.save()
                

                WalletTransaction.objects.create(
                    wallet=wallet, transaction_type='Credit', amount=earn.amount,
                    description=f"Earnings: {earn.order_item.product.name} (ID: {earn.order_item.id})"
                )
                

                Notification.objects.create(
                    user=earn.seller.user,
                    message=f"Payout Approved: ₹{earn.amount} credited for '{earn.order_item.product.name}'."
                )
                
                messages.success(request, f"Payout of ₹{earn.amount} credited to {earn.seller.store_name}.")
                
        elif action == 'reject':
            earn.status = 'Rejected'
            earn.save()
            Notification.objects.create(
                user=earn.seller.user, 
                message=f"Payout Rejected: Commission for '{earn.order_item.product.name}' was declined. Note: {note}"
            )
            messages.warning(request, "Payout rejected.")
            
        elif action == 'update':
            earn.save()
            messages.info(request, "Earning record updated.")
            
    return redirect('admin_seller_earnings')
