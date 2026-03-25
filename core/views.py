from django.shortcuts import render

# Create your views here.

# landing page
def landing_view(request):
    # if request.user.is_authenticated:
    #     return redirect("home")
    return render(request, "core/landing.html")
