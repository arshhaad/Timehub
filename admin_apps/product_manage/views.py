import uuid
import json
import re
from django.core.files.base import ContentFile
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.db.models import Q
from django.core.paginator import Paginator
from django.contrib import messages
from django.http import JsonResponse
from user_apps.core.models import Collection, Product, ProductImage, ProductVariant, Color
from PIL import Image, ImageOps
import io

# Helper to process images in backend (Pillow)
def process_product_image(uploaded_file, size=(800, 800)):
    try:
        img = Image.open(uploaded_file)
        # Convert RGBA to RGB if necessary (JPEG doesn't support alpha)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        # Center-crop and resize to exact square (800x800)
        img = ImageOps.fit(img, size, Image.LANCZOS)
        
        # Save to buffer
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=90)
        buffer.seek(0)
        
        return ContentFile(buffer.read(), name=f"{uuid.uuid4()}.jpg")
    except Exception as e:
        print(f"Error processing image: {e}")
        return None

# Create your views here.

def superuser_required(view_func):
    @login_required(login_url="admin_login")
    def wrap(request, *args, **kwargs):
        if not request.user.is_superuser:
            return redirect("home")
        return view_func(request, *args, **kwargs)
    return wrap


# Product Detail Endpoint
@never_cache
@superuser_required
def product_detail_api(request, product_id):
    """Returns product details (images, variants) as JSON for the edit modal."""
    product = get_object_or_404(Product, id=product_id)
    
    # Build images list
    images = []
    for img in product.images.all().order_by('-is_main', 'created_at'):
        images.append({
            'id': img.id,
            'url': img.image.url,
            'is_main': img.is_main,
        })
    
    # Build variants list
    variants = []
    for v in product.variants.filter(is_active=True).order_by('id'):
        variants.append({
            'id': v.id,
            'strap_material': v.strap_material,
            'strap_color': v.strap_color,
            'dial_color': v.dial_color,
            'price': str(v.price) if v.price else '',
            'discount_price': str(v.discount_price) if v.discount_price else '',
            'stock': v.stock,
            'sku': v.sku,
            'is_active': v.is_active,
            'image_url': v.image.url if v.image else '',
        })
    
    # Product fields
    data = {
        'id': product.id,
        'name': product.name,
        'brand': product.brand,
        'gender': product.gender,
        'occasion': product.occasion,
        'strap_material': product.strap_material,
        'strap_color': product.strap_color,
        'dial_color': product.dial_color,
        'function': product.function,
        'collection_id': product.collection_id,
        'price': str(product.price),
        'discount_price': str(product.discount_price) if product.discount_price else '',
        'stock': product.stock,
        'description': product.description,
        'features': product.features,
        'is_active': product.is_active,
        'colors': list(product.colors.values_list('id', flat=True)),
        'images': images,
        'variants': variants,
    }
    
    return JsonResponse(data)


# Delete Image Endpoint
@never_cache
@superuser_required
def delete_product_image(request, image_id):
    """Deletes a single product image via AJAX."""
    if request.method == 'POST':
        img = get_object_or_404(ProductImage, id=image_id)
        product = img.product
        was_main = img.is_main
        img.delete()
        
        # If deleted image was main, promote the next image
        if was_main:
            next_img = product.images.first()
            if next_img:
                next_img.is_main = True
                next_img.save()
                product.image = next_img.image
            else:
                product.image = None
            product.save()
        
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=405)


# Delete Variant Endpoint
@never_cache
@superuser_required
def delete_variant(request, variant_id):
    """Soft-deletes a product variant via AJAX."""
    if request.method == 'POST':
        variant = get_object_or_404(ProductVariant, id=variant_id)
        variant.is_active = False
        variant.save()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=405)

@never_cache
@superuser_required
def category_list(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_category":
            name = request.POST.get("name", "").strip()
            description = request.POST.get("description", "").strip()
            parent_id = request.POST.get("parent_id")
            
            if not name:
                messages.error(request, "Category name is required.")
                return redirect("category_list")
            
            # Special character validation: Only alphanumeric and spaces
            if not re.match(r'^[a-zA-Z0-9 ]+$', name):
                messages.error(request, "Category name cannot contain special characters or symbols.")
                return redirect("category_list")
            
            if Collection.objects.filter(name__iexact=name, is_deleted=False).exists():
                messages.error(request, f"Category '{name}' already exists.")
                return redirect("category_list")

            parent = Collection.objects.get(id=parent_id) if parent_id and parent_id != "" else None
            
            Collection.objects.create(name=name, description=description, parent=parent)
            messages.success(request, f"Category '{name}' created successfully.")
            return redirect("category_list")

        elif action == "edit_category":
            cat_id = request.POST.get("category_id")
            cat = get_object_or_404(Collection, id=cat_id)
            name = request.POST.get("name", "").strip()
            description = request.POST.get("description", "").strip()
            parent_id = request.POST.get("parent_id")

            if not name:
                messages.error(request, "Category name cannot be empty.")
                return redirect("category_list")
            
            # Special character validation: Only alphanumeric and spaces
            if not re.match(r'^[a-zA-Z0-9 ]+$', name):
                messages.error(request, "Category name cannot contain special characters or symbols.")
                return redirect("category_list")
            
            if Collection.objects.filter(name__iexact=name, is_deleted=False).exclude(id=cat.id).exists():
                messages.error(request, f"Another category with name '{name}' already exists.")
                return redirect("category_list")

            cat.name = name
            cat.description = description
            cat.parent = Collection.objects.get(id=parent_id) if parent_id and parent_id != "" else None
            cat.save()
            messages.success(request, f"Category '{cat.name}' updated successfully.")
            return redirect("category_list")

        elif action == "delete_category":
            cat_id = request.POST.get("category_id")
            cat = get_object_or_404(Collection, id=cat_id)
            cat.is_deleted = True
            cat.save()
            messages.success(request, f"Category '{cat.name}' soft deleted successfully.")
            return redirect("category_list")

    categories_qs = Collection.objects.filter(is_deleted=False).order_by('-id')
    query = request.GET.get("q", "")
    if query:
        categories_qs = categories_qs.filter(Q(name__icontains=query) | Q(description__icontains=query))

    all_categories = Collection.objects.filter(is_deleted=False).order_by('name')
    paginator = Paginator(categories_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'categories': page_obj,
        'all_categories': all_categories,
        'query': query,
        'active_menu': 'categories'
    }
    return render(request, "Category.html", context)


def _save_variants(product, request):
    """Helper to create/update variants from form arrays."""
    post_data = request.POST
    
    strap_colors = post_data.getlist("variant_strap_color[]")
    dial_colors = post_data.getlist("variant_dial_color[]")
    variant_stocks = post_data.getlist("variant_stock[]")
    variant_prices = post_data.getlist("variant_price[]")
    variant_skus = post_data.getlist("variant_sku[]")
    variant_ids = post_data.getlist("variant_id[]")
    variant_image_indices = post_data.getlist("variant_image_idx[]")
    
    # Track which existing variant IDs were submitted (for soft-deletion of removed ones)
    submitted_ids = set()
    
    # Use skus or ids as the base for the loop to ensure we process all submitted rows
    base_list = variant_skus if len(variant_skus) >= len(variant_ids) else variant_ids
    
    for idx in range(len(base_list)):
        v_id = variant_ids[idx] if idx < len(variant_ids) else ''
        v_stock_raw = variant_stocks[idx] if idx < len(variant_stocks) else '0'
        v_sku = variant_skus[idx] if idx < len(variant_skus) else ''
        
        # Handle variant image
        v_image = None
        if idx < len(variant_image_indices):
            v_img_idx = variant_image_indices[idx]
            v_image = request.FILES.get(f"variant_image_{v_img_idx}")

        # Parse numeric values
        try:
            v_stock = int(v_stock_raw) if v_stock_raw else 0
        except ValueError:
            v_stock = 0
        
        if v_id and v_id.isdigit():
            # Update existing variant
            try:
                variant = ProductVariant.objects.get(id=int(v_id), product=product)
                variant.stock = v_stock
                variant.sku = v_sku
                if v_image:
                    variant.image = v_image
                variant.is_active = True
                variant.save()
                submitted_ids.add(variant.id)
            except ProductVariant.DoesNotExist:
                pass
        else:
            # Create new variant
            if v_sku:
                variant = ProductVariant.objects.create(
                    product=product,
                    stock=v_stock,
                    sku=v_sku,
                    image=v_image
                )
                submitted_ids.add(variant.id)
    
    # Soft-delete variants removed from the form
    if submitted_ids:
        product.variants.filter(is_active=True).exclude(id__in=submitted_ids).update(is_active=False)
    elif len(strap_colors) == 0:
        # No variants submitted — soft-delete all active ones
        product.variants.filter(is_active=True).update(is_active=False)


@never_cache
@superuser_required
def product_list(request):
    if request.method == "POST":
        action = request.POST.get("action")
        
        if action == "add_product":
            name = request.POST.get("name", "").strip()
            collection_id = request.POST.get("collection_id")
            price_raw = request.POST.get("price")
            discount_price_raw = request.POST.get("discount_price")
            colors = request.POST.getlist("colors")
            stock_raw = request.POST.get("stock")
            description = request.POST.get("description", "").strip()
            is_active = request.POST.get("is_active") == "on"
            
            # Extra fields
            brand = request.POST.get("brand", "TimeHub").strip()
            gender = request.POST.get("gender", "Unisex")
            occasion = request.POST.get("occasion", "Casual")
            strap_material = ", ".join(request.POST.getlist("strap_material")).strip()
            strap_color = ", ".join(request.POST.getlist("strap_color")).strip()
            dial_color = ", ".join(request.POST.getlist("dial_color")).strip()
            function = request.POST.get("function", "Analog")
            features = request.POST.get("features", "").strip()

            # Validation
            if not name:
                messages.error(request, "Product name is required.")
                return redirect("product_list")
            
            if not collection_id:
                messages.error(request, "Please select a category.")
                return redirect("product_list")
            
            try:
                price = float(price_raw) if price_raw else 0.0
                if price <= 0:
                    messages.error(request, "Price must be greater than zero.")
                    return redirect("product_list")
                
                discount_price = float(discount_price_raw) if discount_price_raw else None
                if discount_price is not None and discount_price >= price:
                    messages.error(request, "Discount price must be less than the original price.")
                    return redirect("product_list")
                    
                stock = int(stock_raw) if stock_raw else 0
                if stock < 0:
                    messages.error(request, "Stock cannot be negative.")
                    return redirect("product_list")
            except ValueError:
                messages.error(request, "Invalid numeric values for price or stock.")
                return redirect("product_list")
            
            collection = get_object_or_404(Collection, id=collection_id)
            
            product = Product.objects.create(
                name=name, collection=collection, price=price,
                discount_price=discount_price,
                stock=stock, description=description,
                is_active=is_active,
                brand=brand, gender=gender, occasion=occasion,
                strap_material=strap_material, strap_color=strap_color,
                dial_color=dial_color, function=function, features=features,
            )
            
            if colors:
                product.colors.set(colors)
            
            # Process up to 3 numbered image slots
            for i in range(1, 4):
                img_file = request.FILES.get(f"product_image_{i}")
                if img_file:
                    processed_file = process_product_image(img_file)
                    if processed_file:
                        is_main = (i == 1)
                        img_obj = ProductImage.objects.create(
                            product=product, image=processed_file, is_main=is_main
                        )
                        if is_main:
                            product.image = img_obj.image
                            product.save()
            
            # Save variants
            _save_variants(product, request)

            messages.success(request, f"Product '{name}' created successfully.")
            return redirect("product_list")

        elif action == "edit_product":
            prod_id = request.POST.get("product_id")
            product = get_object_or_404(Product, id=prod_id)
            
            name = request.POST.get("name", "").strip()
            price_raw = request.POST.get("price")
            discount_price_raw = request.POST.get("discount_price")
            stock_raw = request.POST.get("stock")
            collection_id = request.POST.get("collection_id")

            # Validation
            if not name:
                messages.error(request, "Product name cannot be empty.")
                return redirect("product_list")
            
            try:
                price = float(price_raw) if price_raw else product.price
                if price <= 0:
                    messages.error(request, "Price must be greater than zero.")
                    return redirect("product_list")

                discount_price = float(discount_price_raw) if discount_price_raw else None
                if discount_price is not None and discount_price >= price:
                    messages.error(request, "Discount price must be less than the original price.")
                    return redirect("product_list")

                stock = int(stock_raw) if stock_raw else product.stock
                if stock < 0:
                    messages.error(request, "Stock cannot be negative.")
                    return redirect("product_list")
            except ValueError:
                messages.error(request, "Invalid numeric values for price or stock.")
                return redirect("product_list")

            product.name = name
            product.price = price
            product.discount_price = discount_price
            product.stock = stock
            colors = request.POST.getlist("colors")
            product.colors.set(colors)
            product.collection = get_object_or_404(Collection, id=request.POST.get("collection_id"))
            product.description = request.POST.get("description", "")
            product.is_active = request.POST.get("is_active") == "on"
            
            # Extra fields
            product.brand = request.POST.get("brand", product.brand)
            product.gender = request.POST.get("gender", product.gender)
            product.occasion = request.POST.get("occasion", product.occasion)
            product.strap_material = ", ".join(request.POST.getlist("strap_material")).strip()
            product.strap_color = ", ".join(request.POST.getlist("strap_color")).strip()
            product.dial_color = ", ".join(request.POST.getlist("dial_color")).strip()
            product.function = request.POST.get("function", product.function)
            product.features = request.POST.get("features", product.features)
            product.save()
            
            # Process image updates
            for i in range(1, 4):
                img_file = request.FILES.get(f"product_image_{i}")
                if img_file:
                    processed_file = process_product_image(img_file)
                    if processed_file:
                        is_main = (i == 1)
                        if is_main:
                            # If new main image uploaded, sync with Product model
                            ProductImage.objects.filter(product=product, is_main=True).update(is_main=False)
                        
                        img_obj = ProductImage.objects.create(
                            product=product, image=processed_file, is_main=is_main
                        )

                        if is_main:
                            product.image = img_obj.image
                            product.save()

            # Save variants
            _save_variants(product, request)

            messages.success(request, f"Product '{product.name}' updated successfully.")
            return redirect("product_list")

        elif action == "delete_product":
            prod_id = request.POST.get("product_id")
            product = get_object_or_404(Product, id=prod_id)
            product.is_deleted = True
            product.save()
            messages.success(request, "Product soft-deleted successfully.")
            return redirect("product_list")

    # Base queryset: only non-deleted products, sorted by ID descending
    products_qs = Product.objects.filter(is_deleted=False).prefetch_related('images', 'collection', 'colors', 'variants').order_by('-id')

    # Search logic
    query = request.GET.get("q", "")
    if query:
        products_qs = products_qs.filter(
            Q(name__icontains=query) | Q(description__icontains=query) | Q(collection__name__icontains=query)
        )

    all_categories = Collection.objects.filter(is_deleted=False).order_by('name')
    paginator = Paginator(products_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'products': page_obj,
        'all_categories': all_categories,
        'all_colors': Color.objects.all(),
        'query': query,
        'active_menu': 'products'
    }
    return render(request, "product.html", context)