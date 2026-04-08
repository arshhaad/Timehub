from django.urls import path
from . import views

urlpatterns = [
    path('orders/', views.order_list, name='admin_order_list'),
    path('orders/<int:order_id>/', views.order_detail, name='order_detail'),
    path('orders/<int:order_id>/status/', views.update_order_status, name='update_order_status'),
    path('inventory/', views.inventory_list, name='admin_inventory_list'),
    path('inventory/update/', views.inventory_update, name='admin_inventory_update'),
]
