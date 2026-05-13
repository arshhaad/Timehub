from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.cache import never_cache
from .models import Coupon, ProductOffer, CategoryOffer, ReferralOffer
from user_apps.core.models import Collection, Product

def superuser_required(view_func):
    @login_required(login_url="admin_login")
    def wrap(request, *args, **kwargs):
        if not request.user.is_superuser or hasattr(request.user, 'seller_profile'):
            return redirect("home")
        return view_func(request, *args, **kwargs)
    return wrap

@never_cache
@superuser_required
def offers_list(request):
    product_offers = ProductOffer.objects.all().order_by('-created_at')
    category_offers = CategoryOffer.objects.all().order_by('-created_at')
    all_products = Product.objects.filter(is_deleted=False).order_by('name')
    all_categories = Collection.objects.filter(is_deleted=False).order_by('name')
    
    referral_offer = ReferralOffer.objects.filter(is_active=True).first()
    
    context = {
        'product_offers': product_offers,
        'category_offers': category_offers,
        'referral_offer': referral_offer,
        'all_products': all_products,
        'all_categories': all_categories,
        'active_menu': 'offers'
    }
    return render(request, 'offers.html', context)

@never_cache
@superuser_required
def add_product_offer(request):
    if request.method == 'POST':
        from datetime import datetime
        product_id = request.POST.get('product_id')
        discount_raw = request.POST.get('discount', '').strip()
        valid_from_raw = request.POST.get('valid_from', '').strip()
        valid_to_raw = request.POST.get('valid_to', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        
        if not product_id:
            messages.error(request, "Please select a product.")
            return redirect('admin_offers_list')
        
        try:
            discount = int(discount_raw)
            if discount < 1 or discount > 99:
                raise ValueError
        except ValueError:
            messages.error(request, "Discount must be a number between 1 and 99.")
            return redirect('admin_offers_list')
            
        if not valid_from_raw or not valid_to_raw:
            messages.error(request, "Both validity dates are required.")
            return redirect('admin_offers_list')
            
        try:
            valid_from = datetime.fromisoformat(valid_from_raw)
            valid_to = datetime.fromisoformat(valid_to_raw)
            if valid_to <= valid_from:
                messages.error(request, "Expiry date must be after start date.")
                return redirect('admin_offers_list')
        except ValueError:
            messages.error(request, "Invalid date format.")
            return redirect('admin_offers_list')

        # Check if offer already exists for this product
        if ProductOffer.objects.filter(product_id=product_id).exists():
            messages.error(request, "An offer already exists for this product. Edit the existing one instead.")
            return redirect('admin_offers_list')

        ProductOffer.objects.create(
            product_id=product_id,
            discount_percentage=discount,
            valid_from=valid_from,
            valid_to=valid_to,
            is_active=is_active
        )
        messages.success(request, "Product offer added successfully.")
    return redirect('admin_offers_list')

@never_cache
@superuser_required
def add_category_offer(request):
    if request.method == 'POST':
        from datetime import datetime
        category_id = request.POST.get('category_id')
        discount_raw = request.POST.get('discount', '').strip()
        valid_from_raw = request.POST.get('valid_from', '').strip()
        valid_to_raw = request.POST.get('valid_to', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        
        if not category_id:
            messages.error(request, "Please select a category.")
            return redirect('admin_offers_list')
            
        try:
            discount = int(discount_raw)
            if discount < 1 or discount > 99:
                raise ValueError
        except ValueError:
            messages.error(request, "Discount must be a number between 1 and 99.")
            return redirect('admin_offers_list')

        if not valid_from_raw or not valid_to_raw:
            messages.error(request, "Both validity dates are required.")
            return redirect('admin_offers_list')
            
        try:
            valid_from = datetime.fromisoformat(valid_from_raw)
            valid_to = datetime.fromisoformat(valid_to_raw)
            if valid_to <= valid_from:
                messages.error(request, "Expiry date must be after start date.")
                return redirect('admin_offers_list')
        except ValueError:
            messages.error(request, "Invalid date format.")
            return redirect('admin_offers_list')

        # Check if offer already exists for this category
        if CategoryOffer.objects.filter(category_id=category_id).exists():
            messages.error(request, "An offer already exists for this category. Edit the existing one instead.")
            return redirect('admin_offers_list')
        
        CategoryOffer.objects.create(
            category_id=category_id,
            discount_percentage=discount,
            valid_from=valid_from,
            valid_to=valid_to,
            is_active=is_active
        )
        messages.success(request, "Category offer added successfully.")
    return redirect('admin_offers_list')

@never_cache
@superuser_required
def delete_offer(request, offer_type, offer_id):
    if request.method == 'POST':
        if offer_type == 'product':
            offer = get_object_or_404(ProductOffer, id=offer_id)
        else:
            offer = get_object_or_404(CategoryOffer, id=offer_id)
        
        offer.delete()
        messages.success(request, "Offer deleted successfully.")
    return redirect('admin_offers_list')

@never_cache
@superuser_required
def edit_offer(request, offer_type, offer_id):
    if request.method == 'POST':
        from datetime import datetime
        discount_raw = request.POST.get('discount', '').strip()
        valid_from_raw = request.POST.get('valid_from', '').strip()
        valid_to_raw = request.POST.get('valid_to', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        # Validation
        try:
            discount = int(discount_raw)
            if discount < 1 or discount > 99:
                raise ValueError
        except ValueError:
            messages.error(request, "Discount must be a number between 1 and 99.")
            return redirect('admin_offers_list')

        if not valid_from_raw or not valid_to_raw:
            messages.error(request, "Both validity dates are required.")
            return redirect('admin_offers_list')

        try:
            valid_from = datetime.fromisoformat(valid_from_raw)
            valid_to = datetime.fromisoformat(valid_to_raw)
            if valid_to <= valid_from:
                messages.error(request, "Expiry date must be after start date.")
                return redirect('admin_offers_list')
        except ValueError:
            messages.error(request, "Invalid date format.")
            return redirect('admin_offers_list')

        if offer_type == 'product':
            offer = get_object_or_404(ProductOffer, id=offer_id)
            offer.product_id = request.POST.get('product_id')
        else:
            offer = get_object_or_404(CategoryOffer, id=offer_id)
            offer.category_id = request.POST.get('category_id')
            
        offer.discount_percentage = discount
        offer.valid_from = valid_from
        offer.valid_to = valid_to
        offer.is_active = is_active
        offer.save()
        
        messages.success(request, f"{offer_type.title()} offer updated successfully.")
    return redirect('admin_offers_list')

@never_cache
@superuser_required
def update_referral_offer(request):
    if request.method == 'POST':
        from decimal import Decimal, InvalidOperation
        referrer_reward_raw = request.POST.get('referrer_reward', '0').strip()
        referee_signup_reward_raw = request.POST.get('referee_signup_reward', '0').strip()
        referee_order_reward_raw = request.POST.get('referee_order_reward', '0').strip()
        referee_discount_percent_raw = request.POST.get('referee_discount_percent', '50').strip()
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            referrer_reward = Decimal(referrer_reward_raw)
            referee_signup_reward = Decimal(referee_signup_reward_raw)
            referee_order_reward = Decimal(referee_order_reward_raw)
            if referrer_reward < 0 or referee_signup_reward < 0 or referee_order_reward < 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            messages.error(request, "Reward amounts must be non-negative numbers.")
            return redirect('admin_offers_list')

        try:
            referee_discount_percent = int(referee_discount_percent_raw)
            if referee_discount_percent < 1 or referee_discount_percent > 99:
                raise ValueError
        except ValueError:
            messages.error(request, "Referee discount must be between 1 and 99.")
            return redirect('admin_offers_list')

        # Deactivate all others and create/update the active one
        ReferralOffer.objects.all().update(is_active=False)
        
        ReferralOffer.objects.create(
            referrer_reward=referrer_reward,
            referee_signup_reward=referee_signup_reward,
            referee_order_reward=referee_order_reward,
            referee_discount_percent=referee_discount_percent,
            is_active=is_active
        )
        messages.success(request, "Referral offer updated successfully.")
    return redirect('admin_offers_list')

@never_cache
@superuser_required
def coupon_manage(request):
    coupons = Coupon.objects.all().order_by('-created_at')
    all_categories = Collection.objects.filter(is_deleted=False).order_by('name')
    
    context = {
        'coupons': coupons,
        'all_categories': all_categories,
        'active_menu': 'coupons'
    }
    return render(request, 'coupons.html', context)

@never_cache
@superuser_required
def add_coupon(request):
    if request.method == 'POST':
        from django.utils import timezone
        from decimal import Decimal, InvalidOperation
        from datetime import datetime

        code = request.POST.get('code', '').strip().upper()
        discount_type = request.POST.get('discount_type')
        discount_value_raw = request.POST.get('discount_value', '').strip()
        min_purchase_raw = request.POST.get('min_purchase_amount', '0').strip()
        max_discount_raw = request.POST.get('max_discount_amount', '').strip()
        valid_from_raw = request.POST.get('valid_from', '').strip()
        valid_to_raw = request.POST.get('valid_to', '').strip()
        usage_limit_raw = request.POST.get('usage_limit', '').strip()
        usage_limit_per_user_raw = request.POST.get('usage_limit_per_user', '1').strip()
        max_items_raw = request.POST.get('max_items_count', '').strip()
        is_first_order = request.POST.get('is_first_order_only') == 'on'
        is_referral = request.POST.get('is_referral_only') == 'on'
        collection_id = request.POST.get('applicable_collection', '').strip()

        # --- Validation ---
        if not code:
            messages.error(request, "Coupon code is required.")
            return redirect('coupon_manage')

        if not code.isalnum() and not all(c.isalnum() or c in ('_', '-') for c in code):
            messages.error(request, "Coupon code can only contain letters, numbers, hyphens, and underscores.")
            return redirect('coupon_manage')

        if Coupon.objects.filter(code=code).exists():
            messages.error(request, f"Coupon code '{code}' already exists.")
            return redirect('coupon_manage')

        if discount_type not in ('percentage', 'fixed'):
            messages.error(request, "Invalid discount type. Must be 'percentage' or 'fixed'.")
            return redirect('coupon_manage')

        try:
            discount_value = Decimal(discount_value_raw)
        except (InvalidOperation, ValueError):
            messages.error(request, "Discount value must be a valid number.")
            return redirect('coupon_manage')

        if discount_type == 'percentage' and (discount_value <= 0 or discount_value > 99):
            messages.error(request, "Percentage discount must be between 1 and 99.")
            return redirect('coupon_manage')

        if discount_type == 'fixed' and discount_value <= 0:
            messages.error(request, "Fixed discount amount must be greater than 0.")
            return redirect('coupon_manage')

        try:
            min_purchase = Decimal(min_purchase_raw) if min_purchase_raw else Decimal('0')
        except (InvalidOperation, ValueError):
            messages.error(request, "Minimum purchase amount must be a valid number.")
            return redirect('coupon_manage')
        if min_purchase < 0:
            messages.error(request, "Minimum purchase amount cannot be negative.")
            return redirect('coupon_manage')

        max_discount = None
        if max_discount_raw:
            try:
                max_discount = Decimal(max_discount_raw)
            except (InvalidOperation, ValueError):
                messages.error(request, "Maximum discount amount must be a valid number.")
                return redirect('coupon_manage')
            if max_discount <= 0:
                messages.error(request, "Maximum discount amount must be greater than 0.")
                return redirect('coupon_manage')

        if not valid_from_raw or not valid_to_raw:
            messages.error(request, "Both 'Valid From' and 'Valid To' dates are required.")
            return redirect('coupon_manage')

        try:
            valid_from = datetime.fromisoformat(valid_from_raw)
            valid_to = datetime.fromisoformat(valid_to_raw)
        except (ValueError, TypeError):
            messages.error(request, "Invalid date format for validity dates.")
            return redirect('coupon_manage')

        if valid_to <= valid_from:
            messages.error(request, "Expiry date must be after the start date.")
            return redirect('coupon_manage')

        usage_limit = None
        if usage_limit_raw:
            try:
                usage_limit = int(usage_limit_raw)
            except ValueError:
                messages.error(request, "Total usage limit must be a valid whole number.")
                return redirect('coupon_manage')
            if usage_limit <= 0:
                messages.error(request, "Total usage limit must be greater than 0.")
                return redirect('coupon_manage')

        try:
            usage_limit_per_user = int(usage_limit_per_user_raw) if usage_limit_per_user_raw else 1
        except ValueError:
            messages.error(request, "Per-user usage limit must be a valid whole number.")
            return redirect('coupon_manage')
        if usage_limit_per_user <= 0:
            messages.error(request, "Per-user usage limit must be at least 1.")
            return redirect('coupon_manage')

        max_items = None
        if max_items_raw:
            try:
                max_items = int(max_items_raw)
            except ValueError:
                messages.error(request, "Max items count must be a valid whole number.")
                return redirect('coupon_manage')
            if max_items <= 0:
                messages.error(request, "Max items count must be greater than 0.")
                return redirect('coupon_manage')

        # --- Create ---
        try:
            Coupon.objects.create(
                code=code,
                discount_type=discount_type,
                discount_value=discount_value,
                min_purchase_amount=min_purchase,
                max_discount_amount=max_discount,
                valid_from=valid_from,
                valid_to=valid_to,
                usage_limit=usage_limit,
                usage_limit_per_user=usage_limit_per_user,
                max_items_count=max_items,
                is_first_order_only=is_first_order,
                is_referral_only=is_referral,
                applicable_collection_id=collection_id if collection_id else None
            )
            messages.success(request, f"Coupon '{code}' created successfully.")
        except Exception as e:
            messages.error(request, f"Error creating coupon: {str(e)}")

    return redirect('coupon_manage')

@never_cache
@superuser_required
def edit_coupon(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    if request.method == 'POST':
        from decimal import Decimal, InvalidOperation
        from datetime import datetime

        code = request.POST.get('code', '').strip().upper()
        discount_type = request.POST.get('discount_type')
        discount_value_raw = request.POST.get('discount_value', '').strip()
        min_purchase_raw = request.POST.get('min_purchase_amount', '0').strip()
        max_discount_raw = request.POST.get('max_discount_amount', '').strip()
        valid_from_raw = request.POST.get('valid_from', '').strip()
        valid_to_raw = request.POST.get('valid_to', '').strip()
        usage_limit_raw = request.POST.get('usage_limit', '').strip()
        usage_limit_per_user_raw = request.POST.get('usage_limit_per_user', '1').strip()
        max_items_raw = request.POST.get('max_items_count', '').strip()

        # --- Validation ---
        if not code:
            messages.error(request, "Coupon code is required.")
            return redirect('coupon_manage')

        if not all(c.isalnum() or c in ('_', '-') for c in code):
            messages.error(request, "Coupon code can only contain letters, numbers, hyphens, and underscores.")
            return redirect('coupon_manage')

        if Coupon.objects.filter(code=code).exclude(id=coupon_id).exists():
            messages.error(request, f"Another coupon with code '{code}' already exists.")
            return redirect('coupon_manage')

        if discount_type not in ('percentage', 'fixed'):
            messages.error(request, "Invalid discount type.")
            return redirect('coupon_manage')

        try:
            discount_value = Decimal(discount_value_raw)
        except (InvalidOperation, ValueError):
            messages.error(request, "Discount value must be a valid number.")
            return redirect('coupon_manage')

        if discount_type == 'percentage' and (discount_value <= 0 or discount_value > 99):
            messages.error(request, "Percentage discount must be between 1 and 99.")
            return redirect('coupon_manage')

        if discount_type == 'fixed' and discount_value <= 0:
            messages.error(request, "Fixed discount amount must be greater than 0.")
            return redirect('coupon_manage')

        try:
            min_purchase = Decimal(min_purchase_raw) if min_purchase_raw else Decimal('0')
        except (InvalidOperation, ValueError):
            messages.error(request, "Minimum purchase amount must be a valid number.")
            return redirect('coupon_manage')
        if min_purchase < 0:
            messages.error(request, "Minimum purchase amount cannot be negative.")
            return redirect('coupon_manage')

        max_discount = None
        if max_discount_raw:
            try:
                max_discount = Decimal(max_discount_raw)
            except (InvalidOperation, ValueError):
                messages.error(request, "Maximum discount amount must be a valid number.")
                return redirect('coupon_manage')
            if max_discount <= 0:
                messages.error(request, "Maximum discount amount must be greater than 0.")
                return redirect('coupon_manage')

        if not valid_from_raw or not valid_to_raw:
            messages.error(request, "Both 'Valid From' and 'Valid To' dates are required.")
            return redirect('coupon_manage')

        try:
            valid_from = datetime.fromisoformat(valid_from_raw)
            valid_to = datetime.fromisoformat(valid_to_raw)
        except (ValueError, TypeError):
            messages.error(request, "Invalid date format for validity dates.")
            return redirect('coupon_manage')

        if valid_to <= valid_from:
            messages.error(request, "Expiry date must be after the start date.")
            return redirect('coupon_manage')

        usage_limit = None
        if usage_limit_raw:
            try:
                usage_limit = int(usage_limit_raw)
            except ValueError:
                messages.error(request, "Total usage limit must be a valid whole number.")
                return redirect('coupon_manage')
            if usage_limit <= 0:
                messages.error(request, "Total usage limit must be greater than 0.")
                return redirect('coupon_manage')

        try:
            usage_limit_per_user = int(usage_limit_per_user_raw) if usage_limit_per_user_raw else 1
        except ValueError:
            messages.error(request, "Per-user usage limit must be a valid whole number.")
            return redirect('coupon_manage')
        if usage_limit_per_user <= 0:
            messages.error(request, "Per-user usage limit must be at least 1.")
            return redirect('coupon_manage')

        max_items = None
        if max_items_raw:
            try:
                max_items = int(max_items_raw)
            except ValueError:
                messages.error(request, "Max items count must be a valid whole number.")
                return redirect('coupon_manage')
            if max_items <= 0:
                messages.error(request, "Max items count must be greater than 0.")
                return redirect('coupon_manage')

        # --- Update ---
        try:
            coupon.code = code
            coupon.discount_type = discount_type
            coupon.discount_value = discount_value
            coupon.min_purchase_amount = min_purchase
            coupon.max_discount_amount = max_discount
            coupon.valid_from = valid_from
            coupon.valid_to = valid_to
            coupon.usage_limit = usage_limit
            coupon.usage_limit_per_user = usage_limit_per_user
            coupon.max_items_count = max_items
            coupon.is_first_order_only = request.POST.get('is_first_order_only') == 'on'
            coupon.is_referral_only = request.POST.get('is_referral_only') == 'on'
            collection_id = request.POST.get('applicable_collection', '').strip()
            coupon.applicable_collection_id = collection_id if collection_id else None
            coupon.is_active = request.POST.get('is_active') == 'on'
            coupon.save()
            messages.success(request, f"Coupon '{coupon.code}' updated successfully.")
        except Exception as e:
            messages.error(request, f"Error updating coupon: {str(e)}")

    return redirect('coupon_manage')

@never_cache
@superuser_required
def delete_coupon(request, coupon_id):
    if request.method == 'POST':
        coupon = get_object_or_404(Coupon, id=coupon_id)
        code = coupon.code
        coupon.delete()
        messages.success(request, f"Coupon '{code}' deleted successfully.")
        return redirect('coupon_manage')
    messages.error(request, "Invalid request method.")
    return redirect('coupon_manage')
