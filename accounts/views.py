from django.shortcuts import render, redirect
from django.contrib import messages
from .forms import SignupForm


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('landing_view')

    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Account created successfully! Please log in.')
            return redirect('login')
        # form with errors re-renders
    else:
        form = SignupForm()

    return render(request, 'accounts/signup.html', {'form': form})
