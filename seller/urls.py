from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.seller_signup, name='seller_signup'),
    path('login/', views.seller_login, name='seller_login'),
    path('logout/', views.seller_logout, name='seller_logout'),
    path('verify-otp/', views.seller_verify_otp, name='seller_verify_otp'),
    path('become-seller/', views.become_seller, name='become_seller'),
    
    path('dashboard/', views.seller_dashboard, name='seller_dashboard'),
    path('products/', views.seller_product_sell_list, name='seller_product_sell_list'),
    path('products/add/', views.seller_product_add, name='seller_product_add'),
    path('products/edit/<int:product_id>/', views.seller_product_edit, name='seller_product_edit'),
    path('products/status/', views.seller_product_status, name='seller_product_status'),
    path('wallet/', views.seller_wallet, name='seller_wallet'),
    path('settings/', views.seller_settings, name='seller_settings'),
]
