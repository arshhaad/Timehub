from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.cache import never_cache
from .models import Coupon, ProductOffer, CategoryOffer, ReferralOffer
from user_apps.core.models import Collection, Product

def superuser_required(view_func):
    @login_required(login_url="admin_login")
    def wrap(request, *args, **kwargs):
        if not request.user.is_superuser:
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
        product_id = request.POST.get('product_id')
        discount = request.POST.get('discount')
        valid_from = request.POST.get('valid_from')
        valid_to = request.POST.get('valid_to')
        is_active = request.POST.get('is_active') == 'on'
        
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
        category_id = request.POST.get('category_id')
        discount = request.POST.get('discount')
        valid_from = request.POST.get('valid_from')
        valid_to = request.POST.get('valid_to')
        is_active = request.POST.get('is_active') == 'on'
        
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
        if offer_type == 'product':
            offer = get_object_or_404(ProductOffer, id=offer_id)
            offer.product_id = request.POST.get('product_id')
        else:
            offer = get_object_or_404(CategoryOffer, id=offer_id)
            offer.category_id = request.POST.get('category_id')
            
        offer.discount_percentage = request.POST.get('discount')
        offer.valid_from = request.POST.get('valid_from')
        offer.valid_to = request.POST.get('valid_to')
        offer.is_active = request.POST.get('is_active') == 'on'
        offer.save()
        
        messages.success(request, f"{offer_type.title()} offer updated successfully.")
    return redirect('admin_offers_list')

@never_cache
@superuser_required
def update_referral_offer(request):
    if request.method == 'POST':
        referrer_reward = request.POST.get('referrer_reward')
        referee_signup_reward = request.POST.get('referee_signup_reward')
        referee_order_reward = request.POST.get('referee_order_reward')
        referee_discount_percent = request.POST.get('referee_discount_percent')
        is_active = request.POST.get('is_active') == 'on'
        
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
        code = request.POST.get('code', '').strip().upper()
        discount_type = request.POST.get('discount_type')
        discount_value = request.POST.get('discount_value')
        min_purchase = request.POST.get('min_purchase_amount', 0)
        max_discount = request.POST.get('max_discount_amount')
        valid_from = request.POST.get('valid_from')
        valid_to = request.POST.get('valid_to')
        usage_limit = request.POST.get('usage_limit')
        is_first_order = request.POST.get('is_first_order_only') == 'on'
        is_referral = request.POST.get('is_referral_only') == 'on'
        collection_id = request.POST.get('applicable_collection')
        
        if Coupon.objects.filter(code=code).exists():
            messages.error(request, f"Coupon code '{code}' already exists.")
            return redirect('coupon_manage')
            
        try:
            coupon = Coupon.objects.create(
                code=code,
                discount_type=discount_type,
                discount_value=discount_value,
                min_purchase_amount=min_purchase,
                max_discount_amount=max_discount if max_discount else None,
                valid_from=valid_from,
                valid_to=valid_to,
                usage_limit=usage_limit if usage_limit else None,
                usage_limit_per_user=request.POST.get('usage_limit_per_user', 1),
                max_items_count=request.POST.get('max_items_count') if request.POST.get('max_items_count') else None,
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
        coupon.code = request.POST.get('code', '').strip().upper()
        coupon.discount_type = request.POST.get('discount_type')
        coupon.discount_value = request.POST.get('discount_value')
        coupon.min_purchase_amount = request.POST.get('min_purchase_amount', 0)
        
        max_discount = request.POST.get('max_discount_amount')
        coupon.max_discount_amount = max_discount if max_discount else None
        
        coupon.valid_from = request.POST.get('valid_from')
        coupon.valid_to = request.POST.get('valid_to')
        
        usage_limit = request.POST.get('usage_limit')
        coupon.usage_limit = usage_limit if usage_limit else None
        
        coupon.usage_limit_per_user = request.POST.get('usage_limit_per_user', 1)
        
        max_items = request.POST.get('max_items_count')
        coupon.max_items_count = max_items if max_items else None
        
        coupon.is_first_order_only = request.POST.get('is_first_order_only') == 'on'
        coupon.is_referral_only = request.POST.get('is_referral_only') == 'on'
        
        collection_id = request.POST.get('applicable_collection')
        coupon.applicable_collection_id = collection_id if collection_id else None
        
        coupon.is_active = request.POST.get('is_active') == 'on'
        
        try:
            coupon.save()
            messages.success(request, f"Coupon '{coupon.code}' updated successfully.")
        except Exception as e:
            messages.error(request, f"Error updating coupon: {str(e)}")
            
    return redirect('coupon_manage')

@never_cache
@superuser_required
def delete_coupon(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    code = coupon.code
    coupon.delete()
    messages.success(request, f"Coupon '{code}' deleted successfully.")
    return redirect('coupon_manage')
