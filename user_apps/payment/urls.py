from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('list/', views.payment_list, name='payment_list'),
    path('start/<int:order_id>/', views.start_payment, name='start_payment'),
    path('verify/', views.verify_payment, name='verify_payment'),
    path('success/', views.payment_success, name='success'),
    path('failed/', views.payment_failed, name='failed'),
    path('callback/', views.razorpay_callback, name='razorpay_callback'),
    path('wallet/add/', views.add_wallet_fund, name='add_wallet_fund'),
    path('wallet/verify/', views.verify_wallet_fund, name='verify_wallet_fund'),
]
