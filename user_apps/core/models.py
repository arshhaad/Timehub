from django.db import models
from django.conf import settings
from decimal import Decimal

class Collection(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Color(models.Model):
    name = models.CharField(max_length=50, unique=True)
    hex_code = models.CharField(max_length=7) # e.g. #000000

    def __str__(self):
        return self.name

class Product(models.Model):
    GENDER_CHOICES = (
        ('Men', 'Men'),
        ('Women', 'Women'),
        ('Unisex', 'Unisex'),
    )
    OCCASION_CHOICES = (
        ('Casual', 'Casual'),
        ('Formal', 'Formal'),
        ('Sport', 'Sport'),
        ('Luxury', 'Luxury'),
    )
    FUNCTION_CHOICES = (
        ('Analog', 'Analog'),
        ('Digital', 'Digital'),
        ('Chronograph', 'Chronograph'),
        ('Automatic', 'Automatic'),
    )
    BADGE_CHOICES = (
        ('Sale', 'Sale'),
        ('Limited Edition', 'Limited Edition'),
        ('New Arrival', 'New Arrival'),
        ('Exclusive', 'Exclusive'),
        ('Luxury', 'Luxury'),
        ('Premium', 'Premium'),
        ('Signature Series', 'Signature Series'),
        ('Best Seller', 'Best Seller'),
    )

    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name='products')
    name = models.CharField(max_length=200)
    brand = models.CharField(max_length=100, default="TimeHub")
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, default='Unisex')
    occasion = models.CharField(max_length=50, choices=OCCASION_CHOICES, default='Casual')
    strap_material = models.CharField(max_length=100, blank=True)
    strap_color = models.CharField(max_length=100, blank=True)
    dial_color = models.CharField(max_length=100, blank=True)
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
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def get_best_discounted_price(self):
        """Calculates price after applying the best available offer (Product vs Category)."""
        from admin_apps.offers.models import ProductOffer, CategoryOffer
        from django.utils import timezone
        from decimal import Decimal
        
        now = timezone.now()
        
        # Get highest active product offer
        product_offer = self.product_offers.filter(
            is_active=True, valid_from__lte=now, valid_to__gte=now
        ).order_by('-discount_percentage').first()
        
        # Get highest active category offer (via collection)
        category_offer = self.collection.category_offers.filter(
            is_active=True, valid_from__lte=now, valid_to__gte=now
        ).order_by('-discount_percentage').first()
        
        prod_disc_perc = product_offer.discount_percentage if product_offer else 0
        cat_disc_perc = category_offer.discount_percentage if category_offer else 0
        
        best_disc_perc = max(prod_disc_perc, cat_disc_perc)
        
        if best_disc_perc > 0:
            discount_amount = (self.price * Decimal(best_disc_perc)) / Decimal(100)
            return (self.price - discount_amount).quantize(Decimal('0.00'))
        
        # Fallback to manual discount_price if no offers active
        return self.discount_price if self.discount_price else self.price
        
    @property
    def display_price(self):
        """Dynamic price property that accounts for offers."""
        return self.get_best_discounted_price()

    @property
    def has_offer(self):
        return self.get_best_discounted_price() < self.price

class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='product_images/')
    is_main = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for {self.product.name}"

class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    image = models.ImageField(upload_to='variant_images/', null=True, blank=True)
    strap_material = models.CharField(max_length=100, blank=True)
    strap_color = models.CharField(max_length=100, blank=True)
    dial_color = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    sku = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        parts = [self.product.name]
        if self.strap_color:
            parts.append(self.strap_color)
        if self.dial_color:
            parts.append(self.dial_color)
        return ' — '.join(parts)

    @property
    def effective_price(self):
        return self.price if self.price else self.product.price

    @property
    def effective_discount_price(self):
        """Calculates discount price for variant based on best offer or manual discount."""
        from decimal import Decimal
        
        base_price = self.price if self.price else self.product.price
        
        # First check if the base product has an offer (applies to variants too)
        best_price = self.product.get_best_discounted_price()
        
        # If product has an offer, we apply that same percentage to the variant price
        if self.product.has_offer:
            discount_perc = 100 - (best_price * 100 / self.product.price)
            discount_amount = (base_price * discount_perc) / 100
            return (base_price - discount_amount).quantize(Decimal('0.00'))
            
        # Fallback to manual variant discount or product discount
        return self.discount_price if self.discount_price else self.product.discount_price


class Order(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('CONFIRMED', 'Confirmed'),
        ('Processing', 'Processing'),
        ('Shipped', 'Shipped'),
        ('Out for Delivery', 'Out for Delivery'),
        ('Delivered', 'Delivered'),
        ('Cancelled', 'Cancelled'),
        ('Returned', 'Returned'),
        ('Return Requested', 'Return Requested'),
    )
    PAYMENT_CHOICES = (
        ('cod', 'Cash on Delivery'),
        ('razorpay', 'Razorpay'),
        ('wallet', 'TimeHub Wallet'),
    )
    RETURN_STATUS_CHOICES = (
        ('None', 'None'),
        ('Requested', 'Requested'),
        ('Processing', 'Processing'),
        ('Pickup Scheduled', 'Pickup Scheduled'),
        ('Returned', 'Returned'),
        ('Rejected', 'Rejected'),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    address_snapshot = models.TextField(blank=True, help_text='JSON snapshot of address at time of order')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='cod')
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    return_status = models.CharField(max_length=20, choices=RETURN_STATUS_CHOICES, default='None')
    cancel_reason = models.TextField(blank=True, null=True)
    return_reason = models.TextField(blank=True, null=True)
    reschedule_reason = models.TextField(blank=True, null=True)
    requested_reschedule_date = models.DateField(blank=True, null=True)
    requested_reschedule_time = models.TimeField(blank=True, null=True)
    coupon_code = models.CharField(max_length=50, blank=True, null=True, help_text="Coupon code applied at checkout")
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=200, blank=True, null=True)
    reschedule_status = models.CharField(max_length=20, choices=[('None', 'None'), ('Pending', 'Pending'), ('Approved', 'Approved'), ('Rejected', 'Rejected')], default='None')
    reschedule_count = models.PositiveIntegerField(default=0)
    scheduled_delivery_date = models.DateField(blank=True, null=True)
    scheduled_delivery_time = models.TimeField(blank=True, null=True)
    refund_processed_at = models.DateTimeField(blank=True, null=True)
    refund_method = models.CharField(max_length=50, blank=True, null=True)
    is_paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order #{self.id} by {self.user.email}"

    def update_totals(self):
        """Recalculate subtotal, tax, and total based on active items."""
        active_items = self.items.filter(is_cancelled=False)
        self.subtotal = sum(item.price * item.quantity for item in active_items)
        
        # 3% tax as per project standard
        self.tax = round(self.subtotal * Decimal('0.03'), 2)
        
        # Calculate shipping based on subtotal (Standard: Free for high-value orders)
        shipping = Decimal('99.00')
        if self.subtotal >= Decimal('20000.00'):
            shipping = Decimal('0.00')
        elif self.subtotal >= Decimal('5000.00'):
            shipping = Decimal('49.00')
        self.shipping_charge = shipping
        
        # Total amount
        self.total_amount = self.subtotal + self.tax + self.shipping_charge - self.discount
        self.save()

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_cancelled = models.BooleanField(default=False)
    cancel_reason = models.TextField(blank=True, null=True)

    @property
    def total_price(self):
        return self.price * self.quantity

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification for {self.user.email} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

class ComparisonHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comparison_history')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Comparison Histories'

    def __str__(self):
        return f"{self.user.email} compared {self.product.name}"

class Cart(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cart')
    coupon = models.ForeignKey('offers.Coupon', on_delete=models.SET_NULL, null=True, blank=True, related_name='carts')
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Cart for {self.user.email}"

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    
    @property
    def total_price(self):
        if self.variant:
            price = self.variant.effective_discount_price
        else:
            price = self.product.discount_price if self.product.discount_price else self.product.price
        return price * self.quantity

class Wishlist(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlist')
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Wishlist for {self.user.email}"

class WishlistItem(models.Model):
    wishlist = models.ForeignKey(Wishlist, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('wishlist', 'product')
        
    def __str__(self):
        return f"{self.product.name} in {self.wishlist.user.email}'s wishlist"

class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Wallet of {self.user.email} - Balance: {self.balance}"

class WalletTransaction(models.Model):
    TRANSACTION_TYPES = (
        ('Credit', 'Credit'),
        ('Debit', 'Debit'),
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.transaction_type} of {self.amount} for {self.wallet.user.email}"
