from django.urls import path
from . import views

urlpatterns = [
    path('', views.coupon_list, name='coupon_list'),
    path('create/', views.coupon_create, name='coupon_create'),
    path('edit/<int:coupon_id>/', views.coupon_edit, name='coupon_edit'),
    path('delete/<int:coupon_id>/', views.coupon_delete, name='coupon_delete'),
    path('toggle/<int:coupon_id>/', views.coupon_toggle, name='coupon_toggle'),
]
