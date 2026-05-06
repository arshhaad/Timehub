import uuid
import json
import re
from django.core.files.base import ContentFile
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.contrib import messages
from django.http import JsonResponse
from user_apps.core.models import Collection, Product, ProductImage, ProductVariant, VariantImage, Color
from admin_apps.offers.models import ProductOffer, CategoryOffer, ReferralOffer, Coupon
from django.db import transaction
from django.core.exceptions import ValidationError
from PIL import Image, ImageOps
import io
import logging

logger = logging.getLogger(__name__)



def process_product_image(uploaded_file, size=(800, 800)):
    """Resize/crop an uploaded image to 800x800 JPEG."""
    if not uploaded_file or uploaded_file.size == 0:
        return None, "Uploaded file is empty."

    try:
        img = Image.open(uploaded_file)

        # Convert RGBA / palette images so JPEG save doesn't fail
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # Centre-crop and resize to exact square
        img = ImageOps.fit(img, size, Image.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=90)
        file_content = buffer.getvalue()

        if not file_content:
            return None, "Image output buffer is empty after processing."

        return ContentFile(file_content, name=f"{uuid.uuid4()}.jpg"), None

    except Exception as e:
        logger.exception("Error processing image: %s", e)
        return None, f"Image processing failed: {e}"


#  Auth decorator

def superuser_required(view_func):
    @login_required(login_url="admin_login")
    def wrap(request, *args, **kwargs):
        if not request.user.is_superuser or hasattr(request.user, 'seller_profile'):
            return redirect("home")
        return view_func(request, *args, **kwargs)
    return wrap


# Product Detail API

@never_cache
@superuser_required
def product_detail_api(request, product_id):
    """Returns product details (images, variants) as JSON for the edit modal."""
    product = get_object_or_404(Product, id=product_id)

    images = [
        {'id': img.id, 'url': img.image.url, 'is_main': img.is_main}
        for img in product.images.all().order_by('-is_main', 'created_at')
    ]

    variants = [
        {
            'id': v.id,
            'strap_material': v.strap_material,
            'strap_color': v.strap_color,
            'price': str(v.price) if v.price else '',
            'discount_price': str(v.discount_price) if v.discount_price else '',
            'stock': v.stock,
            'sku': v.sku,
            'is_active': v.is_active,
            'image_url': v.image.url if v.image else '',
        }
        for v in product.variants.filter(is_active=True).order_by('id')
    ]

    data = {
        'id': product.id,
        'name': product.name,
        'brand': product.brand,
        'gender': product.gender,
        'occasion': product.occasion,
        'strap_material': product.strap_material,
        'strap_color': product.strap_color,
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
    if request.method == 'POST':
        img = get_object_or_404(ProductImage, id=image_id)
        product = img.product
        was_main = img.is_main
        img.delete()

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
    if request.method == 'POST':
        variant = get_object_or_404(ProductVariant, id=variant_id)
        variant.is_active = False
        variant.save()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=405)


# Category List
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
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'categories': page_obj,
        'all_categories': all_categories,
        'query': query,
        'active_menu': 'categories',
    }
    return render(request, "Category.html", context)
def _save_variants(product, request):
    """Create / update variants from parallel form arrays."""
    post_data = request.POST

    strap_materials       = post_data.getlist("variant_strap_material[]")
    strap_colors          = post_data.getlist("variant_strap_color[]")
    dial_colors           = post_data.getlist("variant_dial_color[]")
    variant_stocks        = post_data.getlist("variant_stock[]")
    variant_skus          = post_data.getlist("variant_sku[]")
    variant_ids           = post_data.getlist("variant_id[]")
    variant_image_indices = post_data.getlist("variant_image_idx[]")
    variant_descriptions  = post_data.getlist("variant_description[]")

    # Pad descriptions list to match length of variant_ids
    while len(variant_descriptions) < len(variant_ids):
        variant_descriptions.append("")

    submitted_ids = set()
    variant_map   = {}

    for v_id, v_sku, v_strap_mat, v_strap_col, v_dial_col, v_stock_raw, v_img_idx, v_desc in zip(
        variant_ids, variant_skus, strap_materials, strap_colors,
        dial_colors, variant_stocks, variant_image_indices, variant_descriptions
    ):
        try:
            v_stock = int(v_stock_raw) if v_stock_raw else 0
        except ValueError:
            v_stock = 0

        variant = None

        if v_id and v_id.isdigit():
            # Update existing variant
            try:
                variant = ProductVariant.objects.get(id=int(v_id), product=product)
                variant.stock         = v_stock
                variant.sku           = v_sku
                variant.strap_material = v_strap_mat
                variant.strap_color   = v_strap_col
                variant.dial_color    = v_dial_col
                variant.description   = v_desc
                variant.is_active     = True

                if v_img_idx:
                    new_images_added = False
                    for i in range(1, 4):
                        field_name = f"variant_image_input_{v_img_idx}_{i}"
                        v_img = request.FILES.get(field_name)
                        if v_img:
                            processed, err = process_product_image(v_img)
                            if processed:
                                if not new_images_added:
                                    # Use the correct related name 'images' as defined in core.models
                                    variant.images.all().delete()
                                    new_images_added = True

                                vi = VariantImage.objects.create(
                                    variant=variant,
                                    image=processed,
                                    is_main=(i == 1),
                                    order=i,
                                )
                                if i == 1:
                                    variant.image = vi.image
                            else:
                                logger.warning("Variant image %s skipped: %s", field_name, err)

                variant.save()
                submitted_ids.add(variant.id)

            except ProductVariant.DoesNotExist:
                pass

        else:
            # Create new variant
            if v_sku or v_strap_mat or v_strap_col:
                variant = ProductVariant.objects.create(
                    product=product,
                    stock=v_stock,
                    sku=v_sku,
                    strap_material=v_strap_mat,
                    strap_color=v_strap_col,
                    dial_color=v_dial_col,
                    description=v_desc,
                    is_active=True,
                )

                if v_img_idx:
                    for i in range(1, 4):
                        field_name = f"variant_image_input_{v_img_idx}_{i}"
                        v_img = request.FILES.get(field_name)
                        if v_img:
                            processed, err = process_product_image(v_img)
                            if processed:
                                vi = VariantImage.objects.create(
                                    variant=variant,
                                    image=processed,
                                    is_main=(i == 1),
                                    order=i,
                                )
                                if i == 1:
                                    variant.image = vi.image
                            else:
                                logger.warning("New variant image %s skipped: %s", field_name, err)

                variant.save()
                submitted_ids.add(variant.id)

        if variant and v_img_idx:
            variant_map[v_img_idx] = variant

    # Soft-delete variants that were removed from the form
    if submitted_ids:
        product.variants.filter(is_active=True).exclude(id__in=submitted_ids).update(is_active=False)
    elif not variant_skus:
        product.variants.filter(is_active=True).update(is_active=False)

    # Recalculate total stock from active variants
    active_variants = product.variants.filter(is_active=True)
    total_stock = active_variants.aggregate(Sum('stock'))['stock__sum'] or 0
    product.stock = total_stock
    
    # Sync product colors from active variants
    variant_color_names = active_variants.values_list('strap_color', flat=True).distinct()
    color_objs = Color.objects.filter(name__in=variant_color_names)
    product.colors.set(color_objs)
    
    product.save()

    return variant_map


def _save_product_images(product, request, variant_map):
    """
    Handle product_image_1 … product_image_3 uploads.
    Returns a list of error strings (empty = all OK).
    """
    errors = []
    for i in range(1, 4):
        field_name = f"product_image_{i}"
        img_file = request.FILES.get(field_name)
        if not img_file:
            continue

        processed, err = process_product_image(img_file)
        if not processed:
            errors.append(f"Image {i}: {err}")
            continue

        is_main = (i == 1)
        if is_main:
            # Demote any existing main image
            ProductImage.objects.filter(product=product, is_main=True).update(is_main=False)

        v_idx = request.POST.get(f"product_image_variant_{i}")
        linked_variant = variant_map.get(v_idx) if v_idx and v_idx != 'all' else None

        img_obj = ProductImage.objects.create(
            product=product,
            variant=linked_variant,
            image=processed,
            is_main=is_main,
        )

        if is_main:
            product.image = img_obj.image
            product.save()

    return errors


def _ensure_product_main_image(product):
    """Fallback: if product.image is empty, pick the first available variant image."""
    if not product.image:
        # Try finding a ProductImage first
        main_img = ProductImage.objects.filter(product=product).first()
        if main_img:
            product.image = main_img.image
            product.save()
        else:
            # Try finding a Variant image
            first_v = product.variants.filter(is_active=True).exclude(Q(image="") | Q(image=None)).first()
            if first_v and first_v.image:
                product.image = first_v.image
                product.save()


# Product List
@never_cache
@superuser_required
def product_list(request):
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "edit_product":
            prod_id = request.POST.get("product_id")
            product = get_object_or_404(Product, id=prod_id)

            name             = request.POST.get("name", "").strip()
            price_raw        = request.POST.get("price")
            discount_price_raw = request.POST.get("discount_price")
            stock_raw        = request.POST.get("stock")

            if not name:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'Product name cannot be empty.'}, status=400)
                messages.error(request, "Product name cannot be empty.")
                return redirect("product_list")

            try:
                price_unit          = float(request.POST.get("price_unit", 1))
                price               = float(price_raw) * price_unit if price_raw else product.price
                if price <= 0:
                    raise ValueError("Price must be greater than zero.")

                discount_price_unit = float(request.POST.get("discount_price_unit", 1))
                discount_price      = float(discount_price_raw) * discount_price_unit if discount_price_raw else None
                if discount_price is not None and discount_price >= price:
                    raise ValueError("Discount price must be less than the original price.")

                stock = int(stock_raw) if stock_raw else product.stock
                if stock < 0:
                    raise ValueError("Stock cannot be negative.")

            except ValueError as ve:
                msg = str(ve) if str(ve) else "Invalid numeric values for price or stock."
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': msg}, status=400)
                messages.error(request, msg)
                return redirect("product_list")

            try:
                with transaction.atomic():
                    product.name           = name
                    product.price          = price
                    product.discount_price = discount_price
                    product.stock          = stock
                    product.collection     = get_object_or_404(Collection, id=request.POST.get("collection_id"))
                    product.description    = request.POST.get("description", "")
                    # FIX: removed duplicate brand/gender/occasion assignments
                    product.brand          = request.POST.get("brand", product.brand)
                    product.gender         = request.POST.get("gender", product.gender)
                    product.occasion       = request.POST.get("occasion", product.occasion)
                    product.function       = request.POST.get("function", product.function)
                    product.features       = request.POST.get("features", product.features)
                    product.save()

                    variant_map  = _save_variants(product, request)
                    img_errors   = _save_product_images(product, request, variant_map)

                    if img_errors:
                        # Surface image errors as warnings but don't roll back
                        for err in img_errors:
                            messages.warning(request, err)

                    has_variants = product.variants.filter(is_active=True).exists()
                    if not has_variants:
                        raise ValidationError("Product must have at least one variant.")

                    product.is_active = (request.POST.get("is_active") == "on") and has_variants
                    product.save()

                messages.success(request, f"Product '{product.name}' updated successfully.")

            except ValidationError as e:
                msg = str(e.message if hasattr(e, 'message') else e)
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': msg}, status=400)
                messages.error(request, msg)

            except Exception as e:
                logger.exception("Error updating product %s", prod_id)
                msg = f"Error updating product: {e}"
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': msg}, status=400)
                messages.error(request, msg)

            return redirect("product_list")

        elif action == "delete_product":
            prod_id = request.POST.get("product_id")
            product = get_object_or_404(Product, id=prod_id)
            product.is_deleted = True
            product.save()
            messages.success(request, "Product soft-deleted successfully.")
            return redirect("product_list")

    products_qs = (
        Product.objects
        .filter(is_deleted=False)
        .prefetch_related('images', 'collection', 'colors', 'variants')
        .order_by('-id')
    )

    query = request.GET.get("q", "")
    if query:
        products_qs = products_qs.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(collection__name__icontains=query)
        )

    paginator = Paginator(products_qs, 10)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'products':       page_obj,
        'all_categories': Collection.objects.filter(is_deleted=False).order_by('name'),
        'all_colors':     Color.objects.all(),
        'query':          query,
        'active_menu':    'products',
    }
    return render(request, "product.html", context)


# Offers

@never_cache
@superuser_required
def offers_list(request):
    context = {
        'product_offers':  ProductOffer.objects.all().order_by('-created_at'),
        'category_offers': CategoryOffer.objects.all().order_by('-created_at'),
        'referral_offer':  ReferralOffer.objects.filter(is_active=True).first(),
        'all_products':    Product.objects.filter(is_deleted=False).order_by('name'),
        'all_categories':  Collection.objects.filter(is_deleted=False).order_by('name'),
        'active_menu':     'offers',
    }
    return render(request, "offers.html", context)


@never_cache
@superuser_required
def add_product_offer(request):
    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        discount   = request.POST.get('discount')
        valid_from = request.POST.get('valid_from')
        valid_to   = request.POST.get('valid_to')

        if not all([product_id, discount, valid_from, valid_to]):
            messages.error(request, "All fields are required.")
            return redirect('admin_offers_list')

        ProductOffer.objects.create(
            product_id=product_id,
            discount_percentage=discount,
            valid_from=valid_from,
            valid_to=valid_to,
            is_active=request.POST.get('is_active') == 'on',
        )
        messages.success(request, "Product offer added successfully.")
    return redirect('admin_offers_list')


@never_cache
@superuser_required
def add_category_offer(request):
    if request.method == 'POST':
        category_id = request.POST.get('category_id')
        discount    = request.POST.get('discount')
        valid_from  = request.POST.get('valid_from')
        valid_to    = request.POST.get('valid_to')

        if not all([category_id, discount, valid_from, valid_to]):
            messages.error(request, "All fields are required.")
            return redirect('admin_offers_list')

        CategoryOffer.objects.create(
            category_id=category_id,
            discount_percentage=discount,
            valid_from=valid_from,
            valid_to=valid_to,
            is_active=request.POST.get('is_active') == 'on',
        )
        messages.success(request, "Category offer added successfully.")
    return redirect('admin_offers_list')


@never_cache
@superuser_required
def add_product(request):
    if request.method == "POST":
        name          = request.POST.get("name", "").strip()
        collection_id = request.POST.get("collection_id")
        price_raw     = request.POST.get("price")
        discount_price_raw = request.POST.get("discount_price")
        stock_raw     = request.POST.get("stock")
        description   = request.POST.get("description", "").strip()
        is_active     = request.POST.get("is_active") == "on"

        brand    = request.POST.get("brand", "TimeHub").strip()
        gender   = request.POST.get("gender", "Unisex")
        occasion = request.POST.get("occasion", "Casual")
        function = request.POST.get("function", "Analog")
        features = request.POST.get("features", "").strip()

        if not name or not collection_id:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': 'Name and Category are required.'}, status=400)
            messages.error(request, "Name and Category are required.")
            return redirect("add_product")

        try:
            price_unit          = float(request.POST.get("price_unit", 1))
            discount_price_unit = float(request.POST.get("discount_price_unit", 1))
            price               = float(price_raw) * price_unit if price_raw else 0.0
            discount_price      = float(discount_price_raw) * discount_price_unit if discount_price_raw else None
            stock               = int(stock_raw) if stock_raw else 0
            collection          = get_object_or_404(Collection, id=collection_id)

            with transaction.atomic():
                product = Product.objects.create(
                    name=name, collection=collection, price=price,
                    discount_price=discount_price, stock=stock,
                    description=description, is_active=is_active,
                    brand=brand, gender=gender, occasion=occasion,
                    function=function, features=features,
                )

                variant_map = _save_variants(product, request)
                img_errors  = _save_product_images(product, request, variant_map)

                if img_errors:
                    for err in img_errors:
                        messages.warning(request, err)

                if not product.variants.filter(is_active=True).exists():
                    raise ValidationError("At least one variant is required.")

                _ensure_product_main_image(product)

            messages.success(request, f"Product '{name}' added successfully.")
            return redirect("product_list")

        except ValidationError as e:
            msg = str(e.message if hasattr(e, 'message') else e)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': msg}, status=400)
            messages.error(request, msg)

        except Exception as e:
            logger.exception("Error adding product")
            msg = f"Error: {e}"
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': msg}, status=400)
            messages.error(request, msg)

    context = {
        'all_categories': Collection.objects.filter(is_deleted=False).order_by('name'),
        'all_colors':     Color.objects.all(),
    }
    return render(request, "add_product.html", context)


# Edit Product
@never_cache
@superuser_required
def edit_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if request.method == "POST":
        name          = request.POST.get("name", "").strip()
        collection_id = request.POST.get("collection_id")
        price_raw     = request.POST.get("price")
        discount_price_raw = request.POST.get("discount_price")
        stock_raw     = request.POST.get("stock")
        description   = request.POST.get("description", "").strip()
        is_active     = request.POST.get("is_active") == "on"

        brand    = request.POST.get("brand", "TimeHub").strip()
        gender   = request.POST.get("gender", "Unisex")
        occasion = request.POST.get("occasion", "Casual")
        function = request.POST.get("function", "Analog")
        features = request.POST.get("features", "").strip()

        if not name or not collection_id:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': 'Name and Category are required.'}, status=400)
            messages.error(request, "Name and Category are required.")
            return redirect("edit_product", product_id=product.id)

        try:
            price_unit          = float(request.POST.get("price_unit", 1))
            discount_price_unit = float(request.POST.get("discount_price_unit", 1))
            price               = float(price_raw) * price_unit if price_raw else 0.0
            discount_price      = float(discount_price_raw) * discount_price_unit if discount_price_raw else None
            stock               = int(stock_raw) if stock_raw else 0
            collection          = get_object_or_404(Collection, id=collection_id)

            with transaction.atomic():
                product.name           = name
                product.collection     = collection
                product.price          = price
                product.discount_price = discount_price
                product.stock          = stock
                product.description    = description
                product.is_active      = is_active
                product.brand          = brand
                product.gender         = gender
                product.occasion       = occasion
                product.function       = function
                product.features       = features
                product.save()

                variant_map = _save_variants(product, request)
                img_errors  = _save_product_images(product, request, variant_map)

                if img_errors:
                    for err in img_errors:
                        messages.warning(request, err)

                if not product.variants.filter(is_active=True).exists():
                    raise ValidationError("At least one variant is required.")

                _ensure_product_main_image(product)

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'message': 'Product updated successfully.'})

            messages.success(request, f"Product '{name}' updated successfully.")
            return redirect("product_list")

        except ValidationError as e:
            msg = str(e.message if hasattr(e, 'message') else e)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': msg}, status=400)
            messages.error(request, msg)

        except Exception as e:
            logger.exception("Error editing product %s", product_id)
            msg = f"Error: {e}"
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': msg}, status=400)
            messages.error(request, msg)

    context = {
        'product':        product,
        'all_categories': Collection.objects.filter(is_deleted=False).order_by('name'),
        'all_colors':     Color.objects.all(),
        'is_edit':        True,
    }
    return render(request, "add_product.html", context)
