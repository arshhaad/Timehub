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
    return render(request, "core/landing.html", {'products': products})

# authenticated home dashboard
@never_cache
def home_view(request):
    products = Product.objects.filter(is_active=True, is_deleted=False)[:4]
    return render(request, 'core/home.html', {'products': products})
