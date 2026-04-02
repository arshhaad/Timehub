from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache

# Create your views here.

# landing page
@never_cache
def landing_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    return render(request, "core/landing.html")

# authenticated home dashboard
@never_cache
def home_view(request):
    return render(request, 'core/home.html')
