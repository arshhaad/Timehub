import uuid
from django.core.files.base import ContentFile
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.db.models import Q
from django.core.paginator import Paginator
from django.contrib import messages
from user_apps.core.models import Collection, Product, ProductImage, Color
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

@never_cache
@superuser_required
def category_list(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_category":
            name = request.POST.get("name")
            description = request.POST.get("description", "")
            parent_id = request.POST.get("parent_id")
            parent = Collection.objects.get(id=parent_id) if parent_id and parent_id != "" else None
            
            Collection.objects.create(name=name, description=description, parent=parent)
            messages.success(request, f"Category '{name}' created successfully.")
            return redirect("category_list")

        elif action == "edit_category":
            cat_id = request.POST.get("category_id")
            cat = get_object_or_404(Collection, id=cat_id)
            cat.name = request.POST.get("name")
            cat.description = request.POST.get("description", "")
            parent_id = request.POST.get("parent_id")
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


@never_cache
@superuser_required
def product_list(request):
    if request.method == "POST":
        action = request.POST.get("action")
        
        if action == "add_product":
            name = request.POST.get("name")
            collection_id = request.POST.get("collection_id")
            price = request.POST.get("price")
            discount_price = request.POST.get("discount_price")
            colors = request.POST.getlist("colors")
            stock = request.POST.get("stock")
            description = request.POST.get("description", "")
            is_active = request.POST.get("is_active") == "on"
            
            # stocks and discount 
            try:
                price = float(price) if price else 0.0
                discount_price = float(discount_price) if discount_price else None
                stock = int(stock) if stock else 0
            except ValueError:
                price, discount_price, stock = 0.0, None, 0
            
            collection = get_object_or_404(Collection, id=collection_id)
            
            product = Product.objects.create(
                name=name, collection=collection, price=price,
                discount_price=discount_price,
                stock=stock, description=description,
                is_active=is_active
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

            messages.success(request, f"Product '{name}' created successfully.")
            return redirect("product_list")

        elif action == "edit_product":
            prod_id = request.POST.get("product_id")
            product = get_object_or_404(Product, id=prod_id)
            
            # Update fields
            try:
                product.price = float(request.POST.get("price", 0))
                disc_price = request.POST.get("discount_price")
                product.discount_price = float(disc_price) if disc_price else None
                product.stock = int(request.POST.get("stock", 0))
            except ValueError:
                pass

            product.name = request.POST.get("name")
            colors = request.POST.getlist("colors")
            product.colors.set(colors)
            product.collection = get_object_or_404(Collection, id=request.POST.get("collection_id"))
            product.description = request.POST.get("description", "")
            product.is_active = request.POST.get("is_active") == "on"
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
    products_qs = Product.objects.filter(is_deleted=False).prefetch_related('images', 'collection', 'colors').order_by('-id')

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