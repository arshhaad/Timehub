from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Coupon
from .forms import CouponForm

def superuser_required(view_func):
    @login_required(login_url="admin_login")
    def wrap(request, *args, **kwargs):
        if not request.user.is_superuser:
            return redirect("home")
        return view_func(request, *args, **kwargs)
    return wrap

@superuser_required
def coupon_list(request):
    coupons = Coupon.objects.all().order_by('-created_at')
    return render(request, 'coupons.html', {
        'coupons': coupons,
    })

@superuser_required
def coupon_create(request):
    if request.method == 'POST':
        form = CouponForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Coupon created successfully!')
            return redirect('coupon_list')
    else:
        form = CouponForm()
    
    return render(request, 'create_coupon.html', {
        'form': form,
        'title': 'Create New Coupon'
    })

@superuser_required
def coupon_edit(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    if request.method == 'POST':
        form = CouponForm(request.POST, instance=coupon)
        if form.is_valid():
            form.save()
            messages.success(request, 'Coupon updated successfully!')
            return redirect('coupon_list')
    else:
        form = CouponForm(instance=coupon)
    
    return render(request, 'create_coupon.html', {
        'form': form,
        'coupon': coupon,
        'title': f'Edit Coupon: {coupon.code}'
    })

@superuser_required
def coupon_delete(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    coupon.delete()
    messages.success(request, 'Coupon deleted successfully!')
    return redirect('coupon_list')

@superuser_required
def coupon_toggle(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    coupon.is_active = not coupon.is_active
    coupon.save()
    status = "activated" if coupon.is_active else "deactivated"
    messages.info(request, f'Coupon {coupon.code} {status}.')
    return redirect('coupon_list')
