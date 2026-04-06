from django.urls import path
from . import views

urlpatterns = [
    path('', views.product_list, name='product_listing'),
    path('<int:product_id>/', views.product_details, name='product_details'),
    path('compare/', views.compare_products, name='compare_products'),
    path('compare/toggle/', views.toggle_compare, name='toggle_compare'),
    path('compare/clear/', views.clear_compare, name='clear_compare'),
    path('compare/mode/', views.toggle_compare_mode, name='toggle_compare_mode'),
]
