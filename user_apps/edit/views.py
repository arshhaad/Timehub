from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .models import Address
from .forms import AddressForm, UserEditForm
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache


@login_required
@never_cache
def dashboard(request):
    user = request.user
    
    # Placeholder data for stats (to be replaced with real models later)
    stats = {
        'total_orders': 12,  # Mock value
        'saved_items': 0,    # Mock value
        'reward_points': '2,450', # Mock value
    }
    
    recent_orders = [
        {'id': 'ORD-2023-8942', 'date': 'Oct 12, 2023', 'items': 1, 'amount': '5,400', 'status': 'Delivered'},
        {'id': 'ORD-2023-7511', 'date': 'Sep 04, 2023', 'items': 2, 'amount': '1,250', 'status': 'Processing'},
    ]
    
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
def edit_profile(request):
    if request.method == 'POST':
        form = UserEditForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect('dashboard')
    else:
        form = UserEditForm(instance=request.user)

    return render(request, 'edit_profile.html', {'form': form})