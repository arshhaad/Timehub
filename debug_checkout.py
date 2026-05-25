import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Timehub.settings")
django.setup()

from django.test import RequestFactory
from user_apps.orders.views import checkout_page
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware

User = get_user_model()
user = User.objects.first()

factory = RequestFactory()
request = factory.get('/checkout/?buy_now_id=5')
request.user = user

middleware = SessionMiddleware(lambda r: None)
middleware.process_request(request)
request.session.save()

msg_middleware = MessageMiddleware(lambda r: None)
msg_middleware.process_request(request)

try:
    response = checkout_page(request)
    print("STATUS:", response.status_code)
except Exception as e:
    import traceback
    traceback.print_exc()
