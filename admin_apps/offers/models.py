from django.db import models
from django.utils import timezone

class Coupon(models.Model):
    DISCOUNT_TYPES = (
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount'),
    )
    code = models.CharField(max_length=50, unique=True)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPES, default='percentage')
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, help_text="Percentage value or fixed amount")
    min_purchase_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_discount_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Maximum discount limit for percentage type")
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField()
    usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Total number of times this coupon can be used by all users")
    used_count = models.PositiveIntegerField(default=0)
    is_first_order_only = models.BooleanField(default=False, help_text="Only for the user's very first order")
    is_referral_only = models.BooleanField(default=False, help_text="Only for users who joined via referral")
    applicable_collection = models.ForeignKey('core.Collection', on_delete=models.SET_NULL, null=True, blank=True, help_text="Restrict coupon to a specific product collection")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.code
    
    def is_valid_for_user(self, user):
        """Checks if the coupon is valid specifically for a given user."""
        from user_apps.orders.models import Order
        
        now = timezone.now()
        if not self.is_active:
            return False, "This coupon is no longer active."
        if self.valid_from > now:
            return False, "This coupon is not yet active."
        if self.valid_to < now:
            return False, "This coupon has expired."
        if self.usage_limit is not None and self.used_count >= self.usage_limit:
            return False, "This coupon has reached its usage limit."
            
        if user and user.is_authenticated:
            # First order check (any non-cancelled order counts)
            if self.is_first_order_only:
                if Order.objects.filter(user=user).exclude(status='Cancelled').exists():
                    return False, "This coupon is only for your first order."
            
            # Referral check
            if self.is_referral_only:
                # Check if user has a profile and was referred
                if not hasattr(user, 'profile') or not getattr(user.profile, 'referred_by', None):
                    return False, "This coupon is only for users joined via referral."
            
                    
            # Collection restriction check
            if self.applicable_collection:
                from user_apps.core.models import Cart
                cart = Cart.objects.filter(user=user).first()
                if cart:
                    has_matching_item = cart.items.filter(product__collection=self.applicable_collection).exists()
                    if not has_matching_item:
                        return False, f"This coupon is only valid for items in the '{self.applicable_collection.name}' collection."
                else:
                    return False, "Your cart is empty."
                    
        return True, "Valid"

    @property
    def is_valid(self):
        """Generic validity check (not user-specific)"""
        now = timezone.now()
        if not self.is_active:
            return False
        if self.valid_from > now or self.valid_to < now:
            return False
        if self.usage_limit is not None and self.used_count >= self.usage_limit:
            return False
        return True
