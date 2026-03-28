from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.contrib.auth import get_user_model
from django.db.models import Q, Count, Sum
from django.core.paginator import Paginator
from django.contrib import messages
from .forms import UserForm
from user_apps.edit.models import Address
from user_apps.core.models import Notification

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
        action = request.POST.get("action", "")
        if action == "edit":
            user_ids = request.POST.getlist("user_ids")
            if user_ids:
                return redirect("user_edit", user_id=user_ids[0])
            else:
                # Smart fallback: If no check boxes selected, edit the FIRST user in current view
                query = request.GET.get("q")
                temp_list = User.objects.filter(is_superuser=False).order_by("-created_at")
                if query:
                    temp_list = temp_list.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(email__icontains=query))
                
                first_user = temp_list.first()
                if first_user:
                    return redirect("user_edit", user_id=first_user.id)
                else:
                    messages.warning(request, "No users found to edit.")
                    return redirect("user_list")
        
        elif action.startswith("delete_"):
            user_id = action.replace("delete_", "")
            user_to_delete = get_object_or_404(User, pk=user_id)
            user_to_delete.delete()
            messages.success(request, f"User {user_to_delete.email} updated successfully!")
            return redirect("user_list")

    users_list = User.objects.filter(is_superuser=False).annotate(
        order_count=Count('orders'),
        total_spent=Sum('orders__total_amount')
    ).order_by("-created_at")
    
    query = request.GET.get("q")
    if query:
        users_list = users_list.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(email__icontains=query))
    
    # Pagination
    paginator = Paginator(users_list, 10) # 10 users per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, "user_list.html", {"users": page_obj, "query": query, 'active_menu': 'users'})


@never_cache
@login_required(login_url="admin_login")
def user_add(request):
    if not request.user.is_superuser:
        return redirect("home")
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.save()
            messages.success(request, "User created.")
            return redirect("user_list")
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = UserForm()

    return render(request, "user_add.html", {"form": form})


@never_cache
@login_required(login_url="admin_login")
def user_edit(request, user_id):
    if not request.user.is_superuser:
        return redirect("home")
    user = get_object_or_404(User, pk=user_id)

    if request.method == "POST":
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            # commit=False to handle password properly
            user_obj = form.save(commit=False)

            pwd = form.cleaned_data.get("password")
            if pwd:
                user_obj.set_password(pwd)

            user_obj.save()
            messages.success(request, "User updated successfully ✅")
            return redirect("user_list")
        else:
            messages.error(request, "Please fix the errors below ✋")
    else:
        form = UserForm(instance=user)

    return render(request, "user_edit.html", {"form": form, "user": user})


@never_cache
@login_required(login_url="admin_login")
def user_delete(request, pk):
    if not request.user.is_superuser:
        return redirect("home")
    user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        user.delete()
        messages.success(request, "User deleted")
        return redirect("user_list")
    return render(request, "user_delete.html", {"user": user})


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

    # Prefetch orders and their items for efficiency
    orders = customer.orders.all().prefetch_related('items__product').order_by('-created_at')
    total_spent = orders.aggregate(total=Sum('total_amount'))['total'] or 0
    addresses = Address.objects.filter(user=customer)
    
    # Notifications sent by admin
    notifications = customer.notifications.order_by('-created_at')[:5]

    context = {
        'customer': customer,
        'orders': orders,
        'total_spent': total_spent,
        'addresses': addresses,
        'wishlist': [],
        'notifications': notifications,
        'active_menu': 'users'
    }
    return render(request, "user_profiles.html", context)