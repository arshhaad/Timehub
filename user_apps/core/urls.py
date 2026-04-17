from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing_view, name='landing_view'),
    path('home/', views.home_view, name='home'),
    path('about/', views.about_view, name='about'),
]