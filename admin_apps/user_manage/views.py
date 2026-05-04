from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.contrib.auth import get_user_model
from django.db.models import Q, Count, Sum
from django.core.paginator import Paginator
from django.contrib import messages
from user_apps.edit.models import Address
from user_apps.core.models import Notification, Collection, Product, Wallet, WalletTransaction
from decimal import Decimal

User = get_user_model()


def superuser_required(view_func):
    @login_required(login_url="admin_login")
    def wrap(request, *args, **kwargs):
        if not request.user.is_superuser:
            return redirect("home")
        return view_func(request, *args, **kwargs)
    return wrap


@never_cache
@login_required(login_url="admin_login")
def user_list(request):
    if not request.user.is_superuser:
        return redirect("home")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_user":
            email = request.POST.get("email")
            first_name = request.POST.get("first_name")
            last_name = request.POST.get("last_name")
            password = request.POST.get("password")
            if User.objects.filter(email=email).exists():
                messages.error(request, "Email already exists.")
            else:
                User.objects.create_user(email=email, first_name=first_name, last_name=last_name, password=password)
                messages.success(request, f"User {email} created successfully.")
            return redirect("user_list")

        elif action == "toggle_status":
            user_id = request.POST.get("user_id")
            user_to_toggle = get_object_or_404(User, id=user_id)
            user_to_toggle.is_active = not user_to_toggle.is_active
            user_to_toggle.save()
            status_text = "unblocked" if user_to_toggle.is_active else "blocked"
            messages.success(request, f"User {user_to_toggle.email} has been {status_text}.")
            return redirect("user_list")

    users_list = User.objects.filter(is_superuser=False).annotate(
        order_count=Count('orders'),
        total_spent=Sum('orders__total_amount')
    ).order_by("-created_at")
    
    status = request.GET.get("status")
    if status == "active":
        users_list = users_list.filter(is_active=True)
    elif status == "blocked":
        users_list = users_list.filter(is_active=False)

    query = request.GET.get("q")
    if query:
        users_list = users_list.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(email__icontains=query))
    
    # Pagination
    paginator = Paginator(users_list, 10) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, "user_list.html", {"users": page_obj, "query": query, "status": status, 'active_menu': 'users'})



@superuser_required
def user_profiles(request, user_id):
    customer = get_object_or_404(User, id=user_id)
    
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "send_message":
            msg_type = request.POST.get("msg_type")
            msg_text = ""
            if msg_type == "password":
                msg_text = "Please update your password and ensure it is strong and secure."
            elif msg_type == "address":
                msg_text = "The provided address is invalid or incomplete. Please update it to continue."
            elif msg_type == "phone":
                msg_text = "Please enter a valid phone number."
            
            if msg_text:
                # Create  notification for the user
                Notification.objects.create(user=customer, message=msg_text)
                
                messages.success(request, f"Notification sent to {customer.first_name}: \"{msg_text}\"")
                return redirect("user_profiles", user_id=user_id)

        elif action == "delete_user":
            if customer.is_superuser:
                messages.error(request, "Cannot delete a superuser account.")
                return redirect("user_profiles", user_id=user_id)
            email = customer.email
            customer.delete()
            messages.success(request, f"User {email} has been permanently deleted.")
            return redirect("user_list")

        elif action == "toggle_status":
            customer.is_active = not customer.is_active
            customer.save()
            status_text = "unblocked" if customer.is_active else "blocked"
            messages.success(request, f"User {customer.email} has been {status_text}.")
            return redirect("user_profiles", user_id=user_id)

    # Prefetch orders and their items for efficiency
    orders = customer.orders.all().prefetch_related('items__product').order_by('-created_at')
    total_spent = orders.aggregate(total=Sum('total_amount'))['total'] or 0
    addresses = Address.objects.filter(user=customer)
    # Wallet fetching
    wallet, _ = Wallet.objects.get_or_create(user=customer)
    
    # Notifications sent by admin
    notifications = customer.notifications.order_by('-created_at')[:5]

    context = {
        'customer': customer,
        'orders': orders,
        'total_spent': total_spent,
        'addresses': addresses,
        'wallet': wallet,
        'wishlist': [],
        'notifications': notifications,
        'active_menu': 'users'
    }
    return render(request, "user_profiles.html", context)

@superuser_required
def admin_user_wallet(request, user_id):
    customer = get_object_or_404(User, id=user_id)
    wallet, created = Wallet.objects.get_or_create(user=customer)
    
    if request.method == "POST":
        amount = request.POST.get("amount")
        action_type = request.POST.get("action_type") # 'Credit' or 'Debit'
        description = request.POST.get("description", "Admin Adjustment")
        
        try:
            amount_dec = Decimal(amount)
            if amount_dec <= 0:
                messages.error(request, "Amount must be greater than zero.")
            else:
                if action_type == 'Debit' and wallet.balance < amount_dec:
                    messages.error(request, "Insufficient balance for this debit.")
                else:
                    # Update balance
                    if action_type == 'Credit':
                        wallet.balance += amount_dec
                    else:
                        wallet.balance -= amount_dec
                    wallet.save()
                    
                    # Create transaction record
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        transaction_type=action_type,
                        amount=amount_dec,
                        description=description
                    )
                    messages.success(request, f"Successfully {action_type.lower()}ed ₹{amount_dec} to {customer.email}'s wallet.")
                    return redirect('admin_user_wallet', user_id=user_id)
        except (ValueError, Decimal.InvalidOperation):
            messages.error(request, "Invalid amount entered.")
            
    transactions = wallet.transactions.all().order_by('-timestamp')
    
    context = {
        'customer': customer,
        'wallet': wallet,
        'transactions': transactions,
        'active_menu': 'wallet',
    }
    return render(request, "user_wallet.html", context)

@superuser_required
def wallet_list(request):
    wallets = Wallet.objects.select_related('user').annotate(
        order_count=Count('user__orders'),
        total_spent=Sum('user__orders__total_amount')
    ).order_by('-user__created_at')
    
    context = {
        'wallets': wallets,
        'active_menu': 'wallet',
    }
    return render(request, "wallet_list.html", context)