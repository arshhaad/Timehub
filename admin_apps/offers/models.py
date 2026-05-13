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
    usage_limit_per_user = models.PositiveIntegerField(default=1, help_text="How many times a single user can use this coupon")
    max_items_count = models.PositiveIntegerField(null=True, blank=True, help_text="Maximum number of items in a cart this coupon can apply to")
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
        from user_apps.core.models import Order
        
        now = timezone.now()
        if not self.is_active:
            return False, "This coupon is no longer active."
        if self.valid_from > now:
            return False, "This coupon is not yet active."
        if self.valid_to < now:
            return False, "This coupon has expired."
        if self.usage_limit is not None and self.used_count >= self.usage_limit:
            return False, "This coupon has reached its total usage limit."
            
        if user and user.is_authenticated:
            # Check per-user usage limit
            user_usage_count = Order.objects.filter(user=user, coupon_code=self.code).exclude(status='Cancelled').count()
            if user_usage_count >= self.usage_limit_per_user:
                return False, f"You have already used this coupon {user_usage_count} times."

            # First order check (any non-cancelled order counts)
            if self.is_first_order_only:
                if Order.objects.filter(user=user).exclude(status='Cancelled').exists():
                    return False, "This coupon is only for your first order."
            
            # Referral check
            if self.is_referral_only:
                if not getattr(user, 'referred_by', None):
                    return False, "This coupon is only for users joined via referral."
            
                    
            # Collection restriction check
            if self.applicable_collection:
                from user_apps.core.models import Cart
                cart = Cart.objects.filter(user=user).first()
                if cart:
                    collection_ids = self.applicable_collection.get_all_descendant_ids()
                    has_matching_item = cart.items.filter(product__collection__id__in=collection_ids).exists()
                    if not has_matching_item:
                        return False, f"This coupon is only valid for items in the '{self.applicable_collection.name}' category."
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

class ProductOffer(models.Model):
    product = models.ForeignKey('core.Product', on_delete=models.CASCADE, related_name='product_offers')
    discount_percentage = models.PositiveIntegerField(help_text="Discount in percentage (e.g. 20 for 20%)")
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.discount_percentage}% off on {self.product.name}"

class CategoryOffer(models.Model):
    category = models.ForeignKey('core.Collection', on_delete=models.CASCADE, related_name='category_offers')
    discount_percentage = models.PositiveIntegerField(help_text="Discount in percentage (e.g. 15 for 15%)")
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.discount_percentage}% off on {self.category.name} collection"

class ReferralOffer(models.Model):
    referrer_reward = models.DecimalField(max_digits=10, decimal_places=2, help_text="Amount credited to referrer after referee's first order")
    referee_signup_reward = models.DecimalField(max_digits=10, decimal_places=2, help_text="Amount credited to referee immediately on signup")
    referee_order_reward = models.DecimalField(max_digits=10, decimal_places=2, help_text="Amount credited to referee after their first order")
    referee_discount_percent = models.PositiveIntegerField(default=50, help_text="Discount percentage for referee's first order")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Referral: Referrer ₹{self.referrer_reward} | Referee ₹{self.referee_signup_reward}+{self.referee_order_reward}"
