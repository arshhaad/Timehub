from django.urls import path
from . import views

urlpatterns = [
    path('', views.product_list, name='product_listing'),
    path('compare/', views.compare_products, name='compare_products'),
    path('compare/toggle/', views.toggle_compare_ajax, name='toggle_compare_ajax'),
    path('compare/clear/', views.clear_compare_ajax, name='clear_compare_ajax'),
    path('compare/mode/', views.toggle_compare_mode_ajax, name='toggle_compare_mode_ajax'),
]
