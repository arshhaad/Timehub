from django.apps import AppConfig


class AuthConfig(AppConfig):
    name = 'admin_apps.auth'
    default_auto_field = 'django.db.models.BigAutoField'
    label = 'admin_auth'
    