from django.urls import path
from . import views

urlpatterns = [
    path('users/', views.user_list, name='user_list'),
    path('profile/<int:user_id>/', views.user_profiles, name='user_profiles'),
]
