"""Admin Product Management Views."""

import uuid
import json
import re
import io
import logging
from PIL import Image, ImageOps

from django.core.files.base import ContentFile
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.contrib import messages
from django.http import JsonResponse
from django.db import transaction
from django.core.exceptions import ValidationError

from user_apps.core.models import (
    Collection, Product, ProductImage, 
    ProductVariant, VariantImage, Color
)
from admin_apps.offers.models import ProductOffer, CategoryOffer, ReferralOffer

# Setup logging for background tasks like image processing
logger = logging.getLogger(__name__)




def process_product_image(uploaded_file, size=(800, 800)):
    """Resize and crop uploaded images to a standard 800x800 square."""
    if not uploaded_file or uploaded_file.size == 0:
        return None, "File is empty."

    try:
        img = Image.open(uploaded_file)

        # Convert to RGB to ensure JPEG compatibility (strips alpha channel)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # Smart crop and resize
        img = ImageOps.fit(img, size, Image.LANCZOS)

        # Save to memory buffer
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=90)
        content = buffer.getvalue()

        return ContentFile(content, name=f"{uuid.uuid4()}.jpg"), None

    except Exception as e:
        logger.exception("Image processing error")
        return None, f"Failed: {str(e)}"


def superuser_required(view_func):
    """Restrict access to administrators only."""
    @login_required(login_url="admin_login")
    def wrap(request, *args, **kwargs):
        if not request.user.is_superuser or hasattr(request.user, 'seller_profile'):
            return redirect("home")
        return view_func(request, *args, **kwargs)
    return wrap




@never_cache
@superuser_required
def category_list(request):
    """Manage product categories and hierarchy."""
    if request.method == "POST":
        action = request.POST.get("action")

        # 1. Add New Category
        if action == "add_category":
            name = request.POST.get("name", "").strip()
            desc = request.POST.get("description", "").strip()
            parent_id = request.POST.get("parent_id")

            if not name:
                messages.error(request, "Name is required.")
            elif not re.match(r'^[a-zA-Z0-9 ]+$', name):
                messages.error(request, "Special characters are not allowed in names.")
            elif Collection.objects.filter(name__iexact=name, is_deleted=False).exists():
                messages.error(request, f"'{name}' already exists.")
            else:
                parent = Collection.objects.filter(id=parent_id).first() if parent_id else None
                Collection.objects.create(name=name, description=desc, parent=parent)
                messages.success(request, f"Category '{name}' created.")
            return redirect("category_list")

        # 2. Update Existing Category
        elif action == "edit_category":
            cat = get_object_or_404(Collection, id=request.POST.get("category_id"))
            name = request.POST.get("name", "").strip()
            desc = request.POST.get("description", "").strip()
            parent_id = request.POST.get("parent_id")

            if not name or not re.match(r'^[a-zA-Z0-9 ]+$', name):
                messages.error(request, "Invalid category name.")
            else:
                cat.name, cat.description = name, desc
                cat.parent = Collection.objects.filter(id=parent_id).first() if parent_id else None
                cat.save()
                messages.success(request, f"Updated '{name}'.")
            return redirect("category_list")

        # 3. Soft Delete Category
        elif action == "delete_category":
            cat = get_object_or_404(Collection, id=request.POST.get("category_id"))
            cat.is_deleted = True
            cat.save()
            messages.success(request, f"Category '{cat.name}' removed.")
            return redirect("category_list")

    # Fetch results with search and pagination
    query = request.GET.get("q", "")
    cats = Collection.objects.filter(is_deleted=False).order_by('-id')
    if query:
        cats = cats.filter(Q(name__icontains=query) | Q(description__icontains=query))

    paginator = Paginator(cats, 10)
    return render(request, "Category.html", {
        'categories': paginator.get_page(request.GET.get('page')),
        'all_categories': Collection.objects.filter(is_deleted=False).order_by('name'),
        'query': query, 'active_menu': 'categories',
    })




@never_cache
@superuser_required
def product_list(request):
    """List and manage all products in the catalog."""
    if request.method == "POST":
        action = request.POST.get("action")

        # Quick Edit: Handles basic price/stock/status updates
        if action == "edit_product":
            p = get_object_or_404(Product, id=request.POST.get("product_id"))
            try:
                with transaction.atomic():
                    p.name = request.POST.get("name", "").strip()
                    p.price = float(request.POST.get("price", p.price))
                    p.stock = int(request.POST.get("stock", p.stock))
                    p.collection = get_object_or_404(Collection, id=request.POST.get("collection_id"))
                    p.is_active = request.POST.get("is_active") == "on"
                    p.save()
                    
                    # Process deeper updates (variants and images)
                    v_map = _save_variants(p, request)
                    _save_product_images(p, request, v_map)
                    
                    if not p.variants.filter(is_active=True).exists():
                        raise ValidationError("At least one active variant is required.")
                
                messages.success(request, f"Product '{p.name}' updated.")
            except Exception as e:
                messages.error(request, f"Update failed: {str(e)}")
            return redirect("product_list")

        # Soft Delete
        elif action == "delete_product":
            p = get_object_or_404(Product, id=request.POST.get("product_id"))
            p.is_deleted = True
            p.save()
            messages.success(request, "Product removed.")
            return redirect("product_list")

    # Fetch and filter
    query = request.GET.get("q", "")
    prods = Product.objects.filter(is_deleted=False).prefetch_related('collection').order_by('-id')
    if query:
        prods = prods.filter(Q(name__icontains=query) | Q(collection__name__icontains=query))

    paginator = Paginator(prods, 10)
    return render(request, "product.html", {
        'products': paginator.get_page(request.GET.get('page')),
        'all_categories': Collection.objects.filter(is_deleted=False).order_by('name'),
        'all_colors': Color.objects.all(),
        'query': query, 'active_menu': 'products',
    })


@never_cache
@superuser_required
def add_product(request):
    """Add a new product to the catalog."""
    if request.method == "POST":
        try:
            with transaction.atomic():
                p = Product.objects.create(
                    name=request.POST.get("name", "").strip(),
                    collection=get_object_or_404(Collection, id=request.POST.get("collection_id")),
                    price=float(request.POST.get("price", 0)),
                    description=request.POST.get("description", "").strip(),
                    is_active=request.POST.get("is_active") == "on",
                    brand=request.POST.get("brand", "TimeHub"),
                    gender=request.POST.get("gender", "Unisex"),
                    occasion=request.POST.get("occasion", "Casual"),
                )
                v_map = _save_variants(p, request)
                _save_product_images(p, request, v_map)
                
                if not p.variants.filter(is_active=True).exists():
                    raise ValidationError("Product must have at least one variant.")
                
                _ensure_product_main_image(p)
                messages.success(request, f"Product '{p.name}' added successfully.")
                return redirect("product_list")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, "add_product.html", {
        'all_categories': Collection.objects.filter(is_deleted=False).order_by('name'),
        'all_colors': Color.objects.all(),
    })


@never_cache
@superuser_required
def edit_product(request, product_id):
    """Edit existing product details and variants."""
    p = get_object_or_404(Product, id=product_id)
    if request.method == "POST":
        try:
            with transaction.atomic():
                p.name = request.POST.get("name", "").strip()
                p.collection = get_object_or_404(Collection, id=request.POST.get("collection_id"))
                p.price = float(request.POST.get("price", p.price))
                p.description = request.POST.get("description", "").strip()
                p.is_active = request.POST.get("is_active") == "on"
                p.save()
                
                v_map = _save_variants(p, request)
                _save_product_images(p, request, v_map)
                
                if not p.variants.filter(is_active=True).exists():
                    raise ValidationError("Product must have an active variant.")
                
                _ensure_product_main_image(p)
                messages.success(request, "Product updated.")
                return redirect("product_list")
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "add_product.html", {
        'product': p, 'is_edit': True,
        'all_categories': Collection.objects.filter(is_deleted=False).order_by('name'),
        'all_colors': Color.objects.all(),
    })




@never_cache
@superuser_required
def offers_list(request):
    """Manage discounts and promotional offers."""
    return render(request, "offers.html", {
        'product_offers': ProductOffer.objects.all().order_by('-created_at'),
        'category_offers': CategoryOffer.objects.all().order_by('-created_at'),
        'referral_offer': ReferralOffer.objects.filter(is_active=True).first(),
        'all_products': Product.objects.filter(is_deleted=False).order_by('name'),
        'all_categories': Collection.objects.filter(is_deleted=False).order_by('name'),
        'active_menu': 'offers',
    })


@never_cache
@superuser_required
def add_product_offer(request):
    """Create a new discount for a specific product."""
    if request.method == 'POST':
        ProductOffer.objects.create(
            product_id=request.POST.get('product_id'),
            discount_percentage=request.POST.get('discount'),
            valid_from=request.POST.get('valid_from'),
            valid_to=request.POST.get('valid_to'),
            is_active=request.POST.get('is_active') == 'on',
        )
        messages.success(request, "Product offer created.")
    return redirect('admin_offers_list')




def _save_variants(product, request):
    """Synchronize product variants with form data."""
    ids = request.POST.getlist("variant_id[]")
    skus = request.POST.getlist("variant_sku[]")
    mats = request.POST.getlist("variant_strap_material[]")
    clrs = request.POST.getlist("variant_strap_color[]")
    dials = request.POST.getlist("variant_dial_color[]")
    stks = request.POST.getlist("variant_stock[]")
    idxs = request.POST.getlist("variant_image_idx[]")
    
    seen_ids = set()
    v_map = {}

    for i in range(len(ids)):
        v_id, sku, stock = ids[i], skus[i], int(stks[i] or 0)
        
        # 1. Resolve Variant Object
        if v_id and v_id.isdigit():
            v = ProductVariant.objects.get(id=int(v_id), product=product)
        else:
            v = ProductVariant(product=product)

        v.sku, v.stock, v.strap_material, v.strap_color, v.dial_color = sku, stock, mats[i], clrs[i], dials[i] if i < len(dials) else ''
        v.is_active = True
        v.save()
        seen_ids.add(v.id)

        # 2. Handle Variant Images (New Uploads)
        v_idx = idxs[i]
        if v_idx:
            v_map[v_idx] = v
            for j in range(1, 4):
                file = request.FILES.get(f"variant_image_input_{v_idx}_{j}")
                if file:
                    processed, _ = process_product_image(file)
                    if processed:
                        # Clear old images for this slot if replacing
                        if j == 1: v.images.all().delete()
                        vi = VariantImage.objects.create(variant=v, image=processed, is_main=(j==1), order=j)
                        if j == 1: v.image = vi.image; v.save()

    # De-activate variants removed from the UI
    product.variants.filter(is_active=True).exclude(id__in=seen_ids).update(is_active=False)
    
    # Sync total product stock and color filters
    active = product.variants.filter(is_active=True)
    product.stock = active.aggregate(Sum('stock'))['stock__sum'] or 0
    product.colors.set(Color.objects.filter(name__in=active.values_list('strap_color', flat=True).distinct()))
    product.save()
    
    return v_map


def _save_product_images(product, request, variant_map):
    """Process and link gallery images to the product."""
    for i in range(1, 4):
        file = request.FILES.get(f"product_image_{i}")
        if file:
            processed, _ = process_product_image(file)
            if processed:
                if i == 1: ProductImage.objects.filter(product=product, is_main=True).update(is_main=False)
                v_idx = request.POST.get(f"product_image_variant_{i}")
                linked_v = variant_map.get(v_idx) if v_idx and v_idx != 'all' else None
                
                img = ProductImage.objects.create(product=product, variant=linked_v, image=processed, is_main=(i==1))
                if i == 1: product.image = img.image; product.save()


def _ensure_product_main_image(product):
    """Set a fallback main image if none is explicitly marked."""
    if not product.image:
        main = ProductImage.objects.filter(product=product).first()
        if main:
            product.image = main.image
        else:
            v = product.variants.filter(is_active=True).exclude(Q(image="") | Q(image=None)).first()
            if v: product.image = v.image
        product.save()




@never_cache
@superuser_required
def product_detail_api(request, product_id):
    """API endpoint for fetching product details."""
    p = get_object_or_404(Product, id=product_id)
    return JsonResponse({
        'id': p.id, 'name': p.name, 'price': str(p.price), 'stock': p.stock,
        'collection_id': p.collection_id, 'description': p.description,
        'is_active': p.is_active,
        'images': [{'id': i.id, 'url': i.image.url, 'is_main': i.is_main} for i in p.images.all()],
        'variants': [{
            'id': v.id, 'sku': v.sku, 'stock': v.stock, 'strap_color': v.strap_color,
            'image_url': v.image.url if v.image else ''
        } for v in p.variants.filter(is_active=True)]
    })


@never_cache
@superuser_required
def delete_product_image(request, image_id):
    """Delete a product gallery image."""
    if request.method == 'POST':
        img = get_object_or_404(ProductImage, id=image_id)
        p, was_main = img.product, img.is_main
        img.delete()
        if was_main: _ensure_product_main_image(p)
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=405)


@never_cache
@superuser_required
def delete_variant(request, variant_id):
    """Deactivate a specific product variant."""
    if request.method == 'POST':
        v = get_object_or_404(ProductVariant, id=variant_id)
        v.is_active = False
        v.save()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=405)
