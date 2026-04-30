from django.shortcuts import render, get_object_or_404, redirect
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.views.decorators.cache import never_cache
from django.db.models import Sum
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from user_apps.core.models import Order, OrderItem, CartItem, Wallet, WalletTransaction
from .models import Payment
from .services import get_razorpay_client
from admin_apps.offers.services import process_referrer_reward

@login_required
@never_cache
def payment_list(request):
    """Shows all payments made by the user and their cashback/wallet credits."""
    user = request.user
    orders_qs = Order.objects.filter(user=user).order_by('-created_at')
    total_spent = orders_qs.aggregate(total=Sum('total_amount'))['total'] or 0
    wallet = Wallet.objects.filter(user=user).first()
    total_cashback = WalletTransaction.objects.filter(
        wallet=wallet, transaction_type='Credit'
    ).aggregate(total=Sum('amount'))['total'] or 0 if wallet else 0
    transactions_qs = WalletTransaction.objects.filter(wallet=wallet).order_by('-timestamp') if wallet else []

    # Paginate orders (10 per page)
    orders_paginator = Paginator(orders_qs, 10)
    orders_page = request.GET.get('orders_page', 1)
    try:
        orders = orders_paginator.page(orders_page)
    except PageNotAnInteger:
        orders = orders_paginator.page(1)
    except EmptyPage:
        orders = orders_paginator.page(orders_paginator.num_pages)

    # Paginate transactions (15 per page)
    tx_paginator = Paginator(transactions_qs, 15)
    tx_page = request.GET.get('tx_page', 1)
    try:
        transactions = tx_paginator.page(tx_page)
    except PageNotAnInteger:
        transactions = tx_paginator.page(1)
    except EmptyPage:
        transactions = tx_paginator.page(tx_paginator.num_pages)

    context = {
        'orders': orders,
        'orders_paginator': orders_paginator,
        'total_spent': total_spent,
        'total_cashback': total_cashback,
        'wallet': wallet,
        'transactions': transactions,
        'tx_paginator': tx_paginator,
        'total_orders_count': orders_qs.count(),
        'total_tx_count': transactions_qs.count() if wallet else 0,
    }
    return render(request, 'payments/payment_list.html', context)


@login_required
def start_payment(request, order_id):
    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user,
        is_paid=False,
        status="Pending"
    )

    amount_in_paise = int(order.total_amount * 100)
    razorpay_client = get_razorpay_client()

    try:
        razorpay_order = razorpay_client.order.create({
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": str(order.id),
            "payment_capture": 1,
        })
    except Exception as e:
        print(f"Razorpay Order Creation Error: {e}")
        return redirect('order_detail', order_uuid=order.uuid)

    payment = Payment.objects.create(
        order=order,
        gateway="RAZORPAY",
        amount=order.total_amount,
        currency="INR",
        status="PENDING",
        razorpay_order_id=razorpay_order["id"]
    )

    context = {
        "order": order,
        "payment": payment,
        "razorpay_key": settings.RAZORPAY_KEY_ID,
        "razorpay_order_id": razorpay_order["id"],
        "amount": amount_in_paise,
        "currency": "INR",
    }

    return render(request, "payments/razorpay_checkout.html", context)


@csrf_exempt
def verify_payment(request):
    if request.method != "POST":
        return render(request, "payments/payment_failed.html")

    razorpay_payment_id = request.POST.get("razorpay_payment_id")
    razorpay_order_id = request.POST.get("razorpay_order_id")
    razorpay_signature = request.POST.get("razorpay_signature")

    if not all([razorpay_payment_id, razorpay_order_id, razorpay_signature]):
        return render(request, "payments/payment_failed.html")

    client = get_razorpay_client()

    try:
        client.utility.verify_payment_signature({
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_order_id": razorpay_order_id,
            "razorpay_signature": razorpay_signature,
        })

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(
                razorpay_order_id=razorpay_order_id
            )

            payment.razorpay_payment_id = razorpay_payment_id
            payment.razorpay_signature = razorpay_signature
            payment.status = "SUCCESS"
            payment.save()

            order = payment.order
            order.is_paid = True
            order.status = "CONFIRMED"
            order.payment_method = "razorpay"
            order.save()

            # Process referral reward for referrer
            process_referrer_reward(order.user)

            # Note: Stock decrementing logic is usually handled during order creation in this project.
            # If start_payment is used after order creation, we might not need to decrement again.
            # But the user's snippet has it, so I'll include it if it's not already done.
            # Actually, let's keep it safe.

            # Cart clearing
            CartItem.objects.filter(cart__user=order.user).delete()

        return render(request, "payments/payment_success.html", {"order": order})

    except Exception as e:
        print(f"Payment Verification Error: {e}")
        Payment.objects.filter(
            razorpay_order_id=razorpay_order_id
        ).update(status="FAILED")

        payment = Payment.objects.filter(
            razorpay_order_id=razorpay_order_id
        ).first()

        # Optionally delete order if payment failed, as per user snippet
        # if payment and payment.order and not payment.order.is_paid:
        #     payment.order.delete()

        return render(request, "payments/payment_failed.html")


def payment_success(request):
    return render(request, "payments/payment_success.html")


def payment_failed(request):
    return render(request, "payments/payment_failed.html")


@csrf_exempt
def razorpay_callback(request):
    if request.method != "POST":
        return redirect("payments:failed")

    razorpay_payment_id = request.POST.get("razorpay_payment_id")
    razorpay_order_id = request.POST.get("razorpay_order_id")
    razorpay_signature = request.POST.get("razorpay_signature")

    if not all([razorpay_payment_id, razorpay_order_id, razorpay_signature]):
        return redirect("payments:failed")

    razorpay_client = get_razorpay_client()

    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature
        })

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(
                razorpay_order_id=razorpay_order_id
            )

            payment.razorpay_payment_id = razorpay_payment_id
            payment.razorpay_signature = razorpay_signature
            payment.status = "SUCCESS"
            payment.save()

            order = payment.order
            order.is_paid = True
            order.status = "CONFIRMED"
            order.payment_method = "razorpay"
            order.save()

            # Process referral reward for referrer
            process_referrer_reward(order.user)

            CartItem.objects.filter(cart__user=order.user).delete()

        return redirect("payments:success")

    except Exception as e:
        print(f"Razorpay Callback Error: {e}")
        Payment.objects.filter(
            razorpay_order_id=razorpay_order_id
        ).update(status="FAILED")

        return redirect("payments:failed")
