from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard, name='user_dashboard'),
    path('addresses/', views.address_list, name='address_list'),
    path('addresses/add/', views.add_address, name='add_address'),
    path('addresses/edit/<int:id>/', views.edit_address, name='edit_address'),
    path('addresses/delete/<int:id>/', views.delete_address, name='delete_address'),
    path('addresses/toggle-default/<int:id>/', views.toggle_default_address, name='toggle_default_address'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/verify-email/', views.verify_email_change, name='verify_email_change'),
    path('profile/resend-otp/', views.resend_email_otp, name='resend_email_otp'),
    path('account/security/', views.account_edit, name='account_edit'),
    path('notifications/', views.notifications_view, name='user_notifications'),
    
    # Cart
    path('cart/', views.cart_view, name='cart_view'),
    path('cart/add/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/update/<int:item_id>/', views.update_cart, name='update_cart'),
    path('cart/remove/<int:item_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('cart/save-later/<int:item_id>/', views.save_for_later, name='save_for_later'),
    
    # Wishlist
    path('wishlist/', views.wishlist_view, name='wishlist_view'),
    path('wishlist/toggle/<int:product_id>/', views.toggle_wishlist, name='toggle_wishlist'),
    path('wishlist/remove/<int:item_id>/', views.remove_wishlist_item, name='remove_wishlist_item'),
]