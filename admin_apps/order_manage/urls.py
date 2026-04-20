from django.urls import path
from . import views

urlpatterns = [
    path('orders/', views.order_list, name='admin_order_list'),
    path('orders/<int:order_id>/', views.order_detail, name='admin_order_detail'),
    path('orders/<int:order_id>/status/', views.update_order_status, name='update_order_status'),
    path('inventory/', views.inventory_list, name='admin_inventory_list'),
    path('inventory/update/', views.inventory_update, name='admin_inventory_update'),
    path('items/<int:item_id>/cancel/', views.cancel_order_item, name='cancel_order_item'),
    path('user-requests/', views.user_requests, name='admin_user_requests'),
    path('user-reschedule/', views.user_reschedule, name='admin_user_reschedule'),
    path('user-reschedule/<int:order_id>/process/', views.process_reschedule, name='process_reschedule'),
    path('sales-report/', views.sales_report, name='sales_report'),
]
