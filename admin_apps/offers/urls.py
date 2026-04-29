from django.urls import path
from . import views

urlpatterns = [
    # General Offers (Product & Category)
    path('', views.offers_list, name='admin_offers_list'),
    path('product/add/', views.add_product_offer, name='add_product_offer'),
    path('category/add/', views.add_category_offer, name='add_category_offer'),
    path('<str:offer_type>/<int:offer_id>/edit/', views.edit_offer, name='edit_offer'),
    path('<str:offer_type>/<int:offer_id>/delete/', views.delete_offer, name='delete_offer'),
    
    # Referral Settings
    path('referral/update/', views.update_referral_offer, name='update_referral_offer'),
    
    # Coupon Management
    path('coupons/', views.coupon_manage, name='coupon_manage'),
    path('coupons/add/', views.add_coupon, name='add_coupon'),
    path('coupons/<int:coupon_id>/edit/', views.edit_coupon, name='edit_coupon'),
    path('coupons/<int:coupon_id>/delete/', views.delete_coupon, name='delete_coupon'),
]
