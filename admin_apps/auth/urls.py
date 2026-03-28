from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.admin_login, name="admin_login"),
    path("logout/", views.admin_logout, name="admin_logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("forgot-password/", views.admin_forgot_password, name="admin_forgot_password"),
    path("verify-otp/", views.admin_verify_otp, name="admin_verify_otp"),
    path("resend-otp/", views.admin_resend_otp, name="admin_resend_otp"),
    path("reset-password/", views.admin_reset_password, name="admin_reset_password"),
    path("profile/", views.admin_profile, name="admin_profile"),
]

