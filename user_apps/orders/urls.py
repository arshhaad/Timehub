from django.urls import path
from . import views

urlpatterns = [
    path('', views.checkout_page, name='checkout_page'),
    path('success/<uuid:order_uuid>/', views.order_success, name='order_success'),
    path('address/add/', views.add_address, name='checkout_add_address'),
    path('address/edit/<uuid:address_uuid>/', views.edit_address, name='checkout_edit_address'),

    # Order 
    path('history/', views.order_history, name='order_history'),
    path('detail/<uuid:order_uuid>/', views.order_detail, name='order_detail'),
    path('track/<uuid:order_uuid>/', views.track_order, name='track_order'),
    path('cancel/<uuid:order_uuid>/', views.cancel_order, name='cancel_order'),
    path('cancel-item/<uuid:item_uuid>/', views.cancel_order_item, name='cancel_order_item'),
    path('return/<uuid:order_uuid>/', views.return_order, name='return_order'),
    path('invoice/<uuid:order_uuid>/', views.download_invoice, name='download_invoice'),
    path('reschedule/<uuid:order_uuid>/', views.reschedule_order, name='reschedule_order'),



    # Coupons
    path('coupon/apply/', views.apply_coupon, name='apply_coupon'),
    path('coupon/remove/', views.remove_coupon, name='remove_coupon'),
    path('coupons/', views.available_coupons, name='available_coupons'),
    path('submit-review/', views.submit_review, name='submit_review'),
]
