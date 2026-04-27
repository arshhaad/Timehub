from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import Wallet
import random
import string

def generate_referral_code(length=8):
    """Generate a random alphanumeric referral code."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def user_setup(sender, instance, created, **kwargs):
    if created:
        # Create wallet
        Wallet.objects.get_or_create(user=instance)
        
        # Generate unique referral code
        if not instance.referral_code:
            code = f"TH-{generate_referral_code()}"
            # Check for uniqueness
            while sender.objects.filter(referral_code=code).exists():
                code = f"TH-{generate_referral_code()}"
            instance.referral_code = code
            instance.save(update_fields=['referral_code'])
