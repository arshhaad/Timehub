from django.urls import path
from .views import auth, otp_verify

urlpatterns = [
    path('signup/', auth.signup_view, name='signup'),
    path('login/', auth.login_view, name='login'),
    path('login-phone/', auth.login_phone_view, name='login-phone'),
    path('logout/', auth.logout_view, name='logout'),
    path('verify-otp/', otp_verify.verify_otp, name='verify-otp'),
    path('resend-otp/', otp_verify.resend_otp, name='resend-otp'),
    path('verify-phone-otp/', otp_verify.verify_phone_otp, name='verify-phone-otp'),
    path('resend-phone-otp/', otp_verify.resend_phone_otp, name='resend-phone-otp'),
    path('forgot-password/', auth.forgot_password, name='forgot-password'),
    path('verify-otp-reset/', otp_verify.verify_otp_reset, name='verify-otp-reset'),
    path('reset-password/', auth.reset_password, name='reset-password'),
    # Referral token URL — shareable link e.g. /accounts/ref/TH-ABC12345/
    path('ref/<str:referral_code>/', auth.referral_redirect, name='referral_redirect'),
]

