"""Core Data Models."""

import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings




class Collection(models.Model):
    """Product collection or category grouping."""
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='children'
    )
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def get_all_descendant_ids(self):
        """Find all sub-collection IDs recursively."""
        descendants = [self.id]
        for child in self.children.all():
            descendants.extend(child.get_all_descendant_ids())
        return descendants


class Color(models.Model):
    """Color tokens for display and filtering."""
    name = models.CharField(max_length=50, unique=True)
    hex_code = models.CharField(max_length=7) 

    def __str__(self):
        return self.name




class Product(models.Model):
    """Main product entity for watches."""
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    # Choice sets for standardized filtering
    GENDER_CHOICES = (('Men', 'Men'), ('Women', 'Women'), ('Unisex', 'Unisex'))
    OCCASION_CHOICES = (('Casual', 'Casual'), ('Formal', 'Formal'), ('Sport', 'Sport'), ('Luxury', 'Luxury'))
    FUNCTION_CHOICES = (('Analog', 'Analog'), ('Digital', 'Digital'), ('Chronograph', 'Chronograph'), ('Automatic', 'Automatic'))
    BADGE_CHOICES = (
        ('Sale', 'Sale'), ('Limited Edition', 'Limited Edition'), ('New Arrival', 'New Arrival'),
        ('Exclusive', 'Exclusive'), ('Luxury', 'Luxury'), ('Premium', 'Premium'),
        ('Signature Series', 'Signature Series'), ('Best Seller', 'Best Seller')
    )

    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name='products')
    name = models.CharField(max_length=200)
    brand = models.CharField(max_length=100, default="TimeHub")
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, default='Unisex')
    occasion = models.CharField(max_length=50, choices=OCCASION_CHOICES, default='Casual')
    strap_material = models.CharField(max_length=100, blank=True)
    strap_color = models.CharField(max_length=100, blank=True)
    function = models.CharField(max_length=50, choices=FUNCTION_CHOICES, default='Analog')
    
    colors = models.ManyToManyField(Color, related_name='products', blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to='products/', null=True, blank=True)
    description = models.TextField(blank=True)
    rating = models.FloatField(default=0.0)
    features = models.TextField(blank=True, help_text="Comma-separated key features")
    badge = models.CharField(max_length=50, choices=BADGE_CHOICES, blank=True, null=True)
    
    # Ownership & Status
    seller = models.ForeignKey('seller.Seller', on_delete=models.CASCADE, related_name='products', null=True, blank=True)
    approval_status = models.CharField(
        max_length=20, choices=[('Pending', 'Pending'), ('Approved', 'Approved'), ('Rejected', 'Rejected')], 
        default='Pending'
    )
    admin_note = models.TextField(blank=True, null=True, help_text="Curator's feedback")
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def get_best_discounted_price(self):
        """Calculate actual selling price with offers."""
        from django.utils import timezone
        now = timezone.now()
        
        # 1. Check Product-specific Offers
        p_offer = self.product_offers.filter(is_active=True, valid_from__lte=now, valid_to__gte=now).order_by('-discount_percentage').first()
        # 2. Check Category-wide Offers
        c_offer = self.collection.category_offers.filter(is_active=True, valid_from__lte=now, valid_to__gte=now).order_by('-discount_percentage').first() if self.collection else None
        
        p_disc = p_offer.discount_percentage if p_offer else 0
        c_disc = c_offer.discount_percentage if c_offer else 0
        
        best_perc = max(p_disc, c_disc)
        
        if best_perc > 0:
            savings = (self.price * Decimal(best_perc)) / Decimal(100)
            return (self.price - savings).quantize(Decimal('0.00'))
        
        # Fallback to manual discount_price if set, else full price
        return self.discount_price if self.discount_price else self.price
        
    @property
    def display_price(self):
        """Frontend-ready price reflecting current discounts."""
        return self.get_best_discounted_price()

    @property
    def has_offer(self):
        """Check if product has an active offer discount."""
        return self.get_best_discounted_price() < self.price

    @property
    def active_product_offer(self):
        """Returns the best currently active product-specific offer."""
        from django.utils import timezone
        now = timezone.now()
        return self.product_offers.filter(is_active=True, valid_from__lte=now, valid_to__gte=now).order_by('-discount_percentage').first()

    @property
    def active_category_offer(self):
        """Returns the best currently active category-wide offer."""
        from django.utils import timezone
        now = timezone.now()
        return self.collection.category_offers.filter(is_active=True, valid_from__lte=now, valid_to__gte=now).order_by('-discount_percentage').first() if self.collection else None

    def get_active_offer(self):
        """Get best current offer for the product."""
        p_offer = self.active_product_offer
        c_offer = self.active_category_offer
        
        if not p_offer and not c_offer: return None
        return p_offer if (p_offer.discount_percentage if p_offer else 0) >= (c_offer.discount_percentage if c_offer else 0) else c_offer


class ProductVariant(models.Model):
    """Specific product variation entity."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    image = models.ImageField(upload_to='variant_images/', null=True, blank=True)
    strap_material = models.CharField(max_length=100, blank=True)
    strap_color = models.CharField(max_length=100, blank=True)
    dial_color = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    sku = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def effective_price(self):
        """Get variant price or parent product price."""
        return self.price if self.price else self.product.price

    def get_best_discounted_price(self):
        """Calculate discounted price for the variant."""
        base = self.effective_price
        from django.utils import timezone
        now = timezone.now()
        p_off = self.product.product_offers.filter(is_active=True, valid_from__lte=now, valid_to__gte=now).order_by('-discount_percentage').first()
        c_off = self.product.collection.category_offers.filter(is_active=True, valid_from__lte=now, valid_to__gte=now).order_by('-discount_percentage').first() if self.product.collection else None
        
        best = max(p_off.discount_percentage if p_off else 0, c_off.discount_percentage if c_off else 0)
        if best > 0:
            return (base - (base * Decimal(best) / Decimal(100))).quantize(Decimal('0.00'))
        return self.discount_price if self.discount_price else base

    @property
    def display_price(self):
        return self.get_best_discounted_price()

    def __str__(self):
        parts = [self.product.name]
        if self.strap_color: parts.append(f"Strap: {self.strap_color}")
        if self.dial_color: parts.append(f"Dial: {self.dial_color}")
        return ' — '.join(parts)

    def get_all_images(self):
        """Aggregate all unique image URLs for the variant."""
        urls = []
        if self.image: urls.append(self.image.url)
        for vi in self.images.all(): urls.append(vi.image.url)
        for pi in self.product_images.all(): urls.append(pi.image.url)
        # Deduplicate while preserving order
        seen = set()
        return [u for u in urls if not (u in seen or seen.add(u))]




class ProductImage(models.Model):
    """Gallery images for a product or variant."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True, related_name='product_images')
    image = models.ImageField(upload_to='product_images/')
    is_main = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class VariantImage(models.Model):
    """Images strictly belonging to a variant."""
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='variant_images/')
    is_main = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)




class Order(models.Model):
    """Customer purchase and tracking record."""
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    STATUS_CHOICES = (
        ('Pending', 'Pending'), ('Confirmed', 'Confirmed'), ('Processing', 'Processing'),
        ('Shipped', 'Shipped'), ('Out for Delivery', 'Out for Delivery'), ('Delivered', 'Delivered'),
        ('Cancelled', 'Cancelled'), ('Returned', 'Returned'), ('Return Requested', 'Return Requested'),
    )
    PAYMENT_CHOICES = (('cod', 'Cash on Delivery'), ('razorpay', 'Razorpay'), ('wallet', 'Wallet'))
    RETURN_CHOICES = (('None', 'None'), ('Requested', 'Requested'), ('Processing', 'Processing'), 
                      ('Pickup Scheduled', 'Pickup Scheduled'), ('Returned', 'Returned'), ('Rejected', 'Rejected'))

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    address_snapshot = models.TextField(blank=True, help_text='JSON snapshot of address at time of purchase')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='cod')
    
    # Financials
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    offer_discount = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Total savings from Product/Category offers")
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Savings from Coupons/Referrals")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Statuses
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    return_status = models.CharField(max_length=20, choices=RETURN_CHOICES, default='None')
    is_paid = models.BooleanField(default=False)
    
    # Reasons & Requests
    cancel_reason = models.TextField(blank=True, null=True)
    return_reason = models.TextField(blank=True, null=True)
    reschedule_reason = models.TextField(blank=True, null=True)
    requested_reschedule_date = models.DateField(blank=True, null=True)
    requested_reschedule_time = models.TimeField(blank=True, null=True)
    
    # External Tracking
    coupon_code = models.CharField(max_length=50, blank=True, null=True)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    
    # Internal Logistics
    reschedule_status = models.CharField(
        max_length=20, choices=[('None', 'None'), ('Pending', 'Pending'), ('Approved', 'Approved'), ('Rejected', 'Rejected')], 
        default='None'
    )
    reschedule_count = models.PositiveIntegerField(default=0)
    scheduled_delivery_date = models.DateField(blank=True, null=True)
    scheduled_delivery_time = models.TimeField(blank=True, null=True)
    
    refund_processed_at = models.DateTimeField(blank=True, null=True)
    refund_method = models.CharField(max_length=50, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order #{self.id} — {self.user.email}"

    def update_totals(self):
        """Recalculate financial breakdown for active items."""
        # Exclude cancelled items and items that have been successfully returned
        if self.return_status == 'Returned':
            active = self.items.filter(is_cancelled=False, is_returned=False)
        else:
            active = self.items.filter(is_cancelled=False)
            
        self.subtotal = sum(i.price * i.quantity for i in active)
        
        # Free shipping logic
        if self.subtotal == 0 or self.subtotal >= Decimal('5000.00'):
            self.shipping_charge = Decimal('0.00')
        else:
            self.shipping_charge = Decimal('49.00')

        # Tax calculation (3% on net price)
        taxable = max(Decimal('0'), self.subtotal - self.discount)
        self.tax = round(taxable * Decimal('0.03'), 2)
        
        # Final Total
        self.total_amount = taxable + self.tax + self.shipping_charge
        self.save()


class OrderItem(models.Model):
    """Product/variant entry within an order."""
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_cancelled = models.BooleanField(default=False)
    cancel_reason = models.TextField(blank=True, null=True)
    is_returned = models.BooleanField(default=False)
    return_reason = models.TextField(blank=True, null=True)

    @property
    def total_price(self):
        return self.price * self.quantity

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"




class Cart(models.Model):
    """Shopping basket for a user."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cart')
    coupon = models.ForeignKey('offers.Coupon', on_delete=models.SET_NULL, null=True, blank=True, related_name='carts')
    created_at = models.DateTimeField(auto_now_add=True)


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    
    @property
    def total_price(self):
        price = self.variant.display_price if self.variant else self.product.display_price
        return price * self.quantity


class Wishlist(models.Model):
    """User collection of saved products."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlist')
    created_at = models.DateTimeField(auto_now_add=True)


class WishlistItem(models.Model):
    """Product saved in a wishlist."""
    wishlist = models.ForeignKey(Wishlist, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = ('wishlist', 'product')


class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class WalletTransaction(models.Model):
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=(('Credit', 'Credit'), ('Debit', 'Debit')))
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-timestamp']


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField(default=5)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class ComparisonHistory(models.Model):
    """Log of products compared by a user."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comparison_history')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('user', 'product')
