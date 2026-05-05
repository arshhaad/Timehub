from django.urls import path
from . import views

urlpatterns = [
    path('profiles/', views.seller_profiles, name='admin_seller_profiles'),
    path('products/', views.seller_products, name='admin_seller_products'),
    path('products/<int:product_id>/', views.seller_product_details, name='admin_seller_product_details'),
    path('action/<int:seller_id>/', views.seller_action, name='admin_seller_action'),
]
