"""Admin User Management Views."""

from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.contrib.auth import get_user_model
from django.db.models import Q, Count, Sum
from django.core.paginator import Paginator
from django.contrib import messages

from user_apps.edit.models import Address
from user_apps.core.models import Notification, Wallet, WalletTransaction


User = get_user_model()




def superuser_required(view_func):
    """Restrict access to superusers only."""
    @login_required(login_url="admin_login")
    def wrap(request, *args, **kwargs):
        if not request.user.is_superuser or hasattr(request.user, 'seller_profile'):
            return redirect("home")
        return view_func(request, *args, **kwargs)
    return wrap




@never_cache
@login_required(login_url="admin_login")
def user_list(request):
    """List and manage all customer accounts."""

    if not request.user.is_superuser:
        return redirect("home")


    if request.method == "POST":
        action = request.POST.get("action")
        

        if action == "add_user":
            email = request.POST.get("email")
            fname = request.POST.get("first_name")
            lname = request.POST.get("last_name")
            pwd = request.POST.get("password")
            
            if User.objects.filter(email=email).exists():
                messages.error(request, "A user with this email already exists.")
            else:
                User.objects.create_user(email=email, first_name=fname, last_name=lname, password=pwd)
                messages.success(request, f"New user {email} created.")
            return redirect("user_list")


        elif action == "toggle_status":
            uid = request.POST.get("user_id")
            target = get_object_or_404(User, id=uid)
            target.is_active = not target.is_active
            target.save()
            
            status = "unblocked" if target.is_active else "blocked"
            messages.success(request, f"Account {target.email} is now {status}.")
            return redirect("user_list")

    
    users_qs = User.objects.filter(is_superuser=False).annotate(
        order_count=Count('orders'),
        delivery_count=Count('orders__delivery_status', distinct=True),
        total_spent=Sum('orders__total_amount')
    ).order_by("-created_at")
    
    # Apply Filters (Status and Search)
    status_filter = request.GET.get("status")
    if status_filter == "active":
        users_qs = users_qs.filter(is_active=True)
    elif status_filter == "blocked":
        users_qs = users_qs.filter(is_active=False)

    search_query = request.GET.get("q")
    if search_query:
        users_qs = users_qs.filter(
            Q(first_name__icontains=search_query) | 
            Q(last_name__icontains=search_query) | 
            Q(email__icontains=search_query)
        )
    

    paginator = Paginator(users_qs, 10) 
    page_obj = paginator.get_page(request.GET.get('page'))
    
    return render(request, "user_list.html", {
        "users": page_obj, "query": search_query, 
        "status": status_filter, 'active_menu': 'users'
    })


@superuser_required
def user_profiles(request, user_id):
    """View full customer profile and history."""
    customer = get_object_or_404(User, id=user_id)
    
    
    if request.method == "POST":
        action = request.POST.get("action")
        
        # 1 Send -app notification
        if action == "send_message":
            msg_type = request.POST.get("msg_type")
            msg_map = {
                "password": "Security Alert: Please update your password to a stronger one.",
                "address": "Action Required: Your delivery address is incomplete.",
                "phone": "Action Required: Please provide a valid contact number."
            }
            text = msg_map.get(msg_type)
            if text:
                Notification.objects.create(user=customer, message=text)
                messages.success(request, f"Alert sent to {customer.first_name}.")
                return redirect("user_profiles", user_id=user_id)

        # 2 Permanent Account Deletion
        elif action == "delete_user":
            if customer.is_superuser:
                messages.error(request, "Safety Rule: Cannot delete admin accounts from here.")
            else:
                email = customer.email
                customer.delete()
                messages.success(request, f"Account {email} deleted forever.")
                return redirect("user_list")

        # 3 Status Toggle
        elif action == "toggle_status":
            customer.is_active = not customer.is_active
            customer.save()
            messages.success(request, f"User status updated.")
            return redirect("user_profiles", user_id=user_id)

   
    orders = customer.orders.all().prefetch_related('items__product').order_by('-created_at')
    spent = orders.aggregate(total=Sum('total_amount'))['total'] or 0
    wallet, _ = Wallet.objects.get_or_create(user=customer)
    recent_notifs = customer.notifications.order_by('-created_at')[:5]

    context = {
        'customer': customer,
        'orders': orders,
        'total_spent': spent,
        'addresses': Address.objects.filter(user=customer),
        'wallet': wallet,
        'notifications': recent_notifs,
        'active_menu': 'users'
    }
    return render(request, "user_profiles.html", context)




@superuser_required
def admin_user_wallet(request, user_id):
    """Manage individual user wallet balance."""
    customer = get_object_or_404(User, id=user_id)
    wallet, _ = Wallet.objects.get_or_create(user=customer)
    
    if request.method == "POST":
        amount_str = request.POST.get("amount")
        action = request.POST.get("action_type") # 'Credit' or 'Debit'
        reason = request.POST.get("description", "Admin Adjustment")
        
        try:
            val = Decimal(amount_str)
            if val <= 0:
                messages.error(request, "Amount must be positive.")
            elif action == 'Debit' and wallet.balance < val:
                messages.error(request, "Customer has insufficient funds for this debit.")
            else:
                # 1 Update Balance
                if action == 'Credit':
                    wallet.balance += val
                else:
                    wallet.balance -= val
                wallet.save()
                
                # 2 Record Transaction
                WalletTransaction.objects.create(
                    wallet=wallet, transaction_type=action, 
                    amount=val, description=reason
                )
                messages.success(request, f"Wallet updated successfully.")
                return redirect('admin_user_wallet', user_id=user_id)
        except:
            messages.error(request, "Invalid numeric value entered.")
            
    txs = wallet.transactions.all().order_by('-timestamp')
    return render(request, "user_wallet.html", {
        'customer': customer, 'wallet': wallet, 
        'transactions': txs, 'active_menu': 'wallet',
    })


@superuser_required
def wallet_list(request):
    """List all user wallets and spending stats."""
    wallets_qs = Wallet.objects.select_related('user').annotate(
        order_count=Count('user__orders'),
        total_spent=Sum('user__orders__total_amount')
    ).order_by('-user__created_at')
    
    query = request.GET.get('q', '').strip()
    if query:
        wallets_qs = wallets_qs.filter(
            Q(user__first_name__icontains=query) | 
            Q(user__last_name__icontains=query) | 
            Q(user__email__icontains=query)
        )
    
    paginator = Paginator(wallets_qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    return render(request, "wallet_list.html", {
        'wallets': page_obj, 'query': query, 'active_menu': 'wallet'
    })