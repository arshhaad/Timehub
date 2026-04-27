from django.urls import path
from . import views

urlpatterns = [
    path('', views.checkout_page, name='checkout_page'),
    path('success/<int:order_id>/', views.order_success, name='order_success'),
    path('address/add/', views.add_address, name='checkout_add_address'),
    path('address/edit/<int:id>/', views.edit_address, name='checkout_edit_address'),

    # Order 
    path('history/', views.order_history, name='order_history'),
    path('detail/<int:order_id>/', views.order_detail, name='order_detail'),
    path('track/<int:order_id>/', views.track_order, name='track_order'),
    path('cancel/<int:order_id>/', views.cancel_order, name='cancel_order'),
    path('cancel-item/<int:item_id>/', views.cancel_order_item, name='cancel_order_item'),
    path('return/<int:order_id>/', views.return_order, name='return_order'),
    path('invoice/<int:order_id>/', views.download_invoice, name='download_invoice'),
    path('reschedule/<int:order_id>/', views.reschedule_order, name='reschedule_order'),

    # Razorpay
    path('razorpay/init/', views.initialize_razorpay_order, name='razorpay_init'),
    path('razorpay/verify/', views.verify_razorpay_payment, name='razorpay_verify'),

    # Coupons
    path('coupon/apply/', views.apply_coupon, name='apply_coupon'),
    path('coupon/remove/', views.remove_coupon, name='remove_coupon'),
    path('coupons/', views.available_coupons, name='available_coupons'),
]
