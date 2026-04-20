from django.urls import path
from . import views

urlpatterns = [
    path('users/', views.user_list, name='user_list'),
    path('profile/<int:user_id>/', views.user_profiles, name='user_profiles'),
    path('wallet/<int:user_id>/', views.admin_user_wallet, name='admin_user_wallet'),
    path('wallets/', views.wallet_list, name='wallet_list'),
]
