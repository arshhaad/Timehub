from django.urls import path
from . import views

urlpatterns = [
    path('categories/', views.category_list, name='category_list'),
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.add_product, name='add_product'),
    path('products/<int:product_id>/detail/', views.product_detail_api, name='product_detail_api'),
    path('products/image/<int:image_id>/delete/', views.delete_product_image, name='delete_product_image'),
]