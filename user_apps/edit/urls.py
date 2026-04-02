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
    path('account/security/', views.account_edit, name='account_edit'),
]