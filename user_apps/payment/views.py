"""Payment Processing Views."""

from django.shortcuts import render, get_object_or_404, redirect
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.views.decorators.cache import never_cache
from django.db.models import Sum
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from user_apps.core.models import Order, CartItem, Wallet, WalletTransaction
from .models import Payment
from .services import get_razorpay_client
from admin_apps.offers.services import process_referrer_reward




@login_required
@never_cache
def payment_list(request):
    """View user transaction and payment history."""
    user = request.user
    
    # 1. Gather Global Metrics
    orders_qs = Order.objects.filter(user=user).order_by('-created_at')
    total_spent = orders_qs.aggregate(total=Sum('total_amount'))['total'] or 0
    
    wallet, _ = Wallet.objects.get_or_create(user=user)
    # Life-time rewards (sum of all Credit transactions)
    total_rewards = WalletTransaction.objects.filter(
        wallet=wallet, transaction_type='Credit'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    transactions_qs = wallet.transactions.all().order_by('-timestamp')

    # 2. Paginate Order History (10 per page)
    orders_pag = Paginator(orders_qs, 10)
    try:
        orders_page = orders_pag.page(request.GET.get('orders_page', 1))
    except (PageNotAnInteger, EmptyPage):
        orders_page = orders_pag.page(1)

    # 3. Paginate Transaction Ledger (15 per page)
    tx_pag = Paginator(transactions_qs, 15)
    try:
        tx_page = tx_pag.page(request.GET.get('tx_page', 1))
    except (PageNotAnInteger, EmptyPage):
        tx_page = tx_pag.page(1)

    context = {
        'orders': orders_page,
        'orders_paginator': orders_pag,
        'total_spent': total_spent,
        'total_cashback': total_rewards,
        'wallet': wallet,
        'transactions': tx_page,
        'tx_paginator': tx_pag,
        'total_orders_count': orders_qs.count(),
        'total_tx_count': transactions_qs.count(),
    }
    return render(request, 'payments/payment_list.html', context)




@login_required
def start_payment(request, order_id):
    """Initialize Razorpay payment for an order."""
    # Security: Ensure order belongs to user and is actually pending
    order = get_object_or_404(Order, id=order_id, user=request.user, is_paid=False, status="Pending")

    # Razorpay expects amount in the smallest currency unit (paise for INR)
    paise = int(order.total_amount * 100)
    client = get_razorpay_client()

    try:
        # Create order in Razorpay Dashboard
        razor_order = client.order.create({
            "amount": paise,
            "currency": "INR",
            "receipt": f"order_rcpt_{order.id}",
            "payment_capture": 1, # Auto-capture successful payments
        })
        
        # Create a local tracking record
        payment = Payment.objects.create(
            order=order, gateway="RAZORPAY", amount=order.total_amount,
            currency="INR", status="PENDING", razorpay_order_id=razor_order["id"]
        )

        return render(request, "payments/razorpay_checkout.html", {
            "order": order, "payment": payment,
            "razorpay_key": settings.RAZORPAY_KEY_ID,
            "razorpay_order_id": razor_order["id"],
            "amount": paise, "currency": "INR",
        })

    except Exception as e:
        print(f"Critcal Error: Razorpay integration failed: {e}")
        return redirect('order_detail', order_uuid=order.uuid)


@csrf_exempt
def verify_payment(request):
    """Verify Razorpay payment signature."""
    if request.method != "POST":
        return render(request, "payments/payment_failed.html")

    p_id = request.POST.get("razorpay_payment_id")
    o_id = request.POST.get("razorpay_order_id")
    sig = request.POST.get("razorpay_signature")

    if not all([p_id, o_id, sig]):
        return render(request, "payments/payment_failed.html")

    client = get_razorpay_client()

    try:
        # Cryptographic verification of the signature sent by Razorpay
        client.utility.verify_payment_signature({
            "razorpay_payment_id": p_id,
            "razorpay_order_id": o_id,
            "razorpay_signature": sig,
        })

        # Process successful payment within a database transaction
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(razorpay_order_id=o_id)
            payment.razorpay_payment_id, payment.razorpay_signature = p_id, sig
            payment.status = "SUCCESS"
            payment.save()

            order = payment.order
            order.is_paid = True
            order.status = "Confirmed"
            order.payment_method = "razorpay"
            order.save()

            # Trigger referral loyalty rewards
            process_referrer_reward(order.user)

            # Cleanup: Order is successful, clear the cart
            CartItem.objects.filter(cart__user=order.user).delete()

        return render(request, "payments/payment_success.html", {"order": order})

    except Exception as e:
        print(f"Signature Verification Failed: {e}")
        Payment.objects.filter(razorpay_order_id=o_id).update(status="FAILED")
        return render(request, "payments/payment_failed.html")




@csrf_exempt
def razorpay_callback(request):
    """Handle Razorpay status update callback."""
    if request.method != "POST":
        return redirect("payments:failed")

    p_id, o_id, sig = request.POST.get("razorpay_payment_id"), request.POST.get("razorpay_order_id"), request.POST.get("razorpay_signature")

    if not all([p_id, o_id, sig]):
        return redirect("payments:failed")

    client = get_razorpay_client()

    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": o_id, "razorpay_payment_id": p_id, "razorpay_signature": sig
        })

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(razorpay_order_id=o_id)
            payment.razorpay_payment_id, payment.razorpay_signature, payment.status = p_id, sig, "SUCCESS"
            payment.save()

            order = payment.order
            order.is_paid, order.status, order.payment_method = True, "Confirmed", "razorpay"
            order.save()

            process_referrer_reward(order.user)
            CartItem.objects.filter(cart__user=order.user).delete()

        return redirect("payments:success")

    except Exception:
        Payment.objects.filter(razorpay_order_id=o_id).update(status="FAILED")
        return redirect("payments:failed")


def payment_success(request):
    """Display payment success page."""
    return render(request, "payments/payment_success.html")


def payment_failed(request):
    """Display payment failure page."""
    return render(request, "payments/payment_failed.html")


@login_required
def add_wallet_fund(request):
    """Initialize Razorpay payment for wallet funding."""
    if request.method != "POST":
        return redirect('user_wallet')
        
    try:
        amount = float(request.POST.get('amount', 0))
        if amount <= 0:
            messages.error(request, "Invalid amount.")
            return redirect('user_wallet')
    except ValueError:
        messages.error(request, "Invalid amount format.")
        return redirect('user_wallet')

    client = get_razorpay_client()
    paise = int(amount * 100)
    
    try:
        razor_order = client.order.create({
            "amount": paise,
            "currency": "INR",
            "payment_capture": 1,
        })
        
        payment = Payment.objects.create(
            user=request.user, amount=amount,
            gateway="RAZORPAY", status="PENDING",
            razorpay_order_id=razor_order["id"]
        )

        return render(request, "payments/razorpay_wallet_checkout.html", {
            "payment": payment,
            "razorpay_key": settings.RAZORPAY_KEY_ID,
            "razorpay_order_id": razor_order["id"],
            "amount": paise,
        })
    except Exception as e:
        messages.error(request, f"Payment initialization failed: {e}")
        return redirect('user_wallet')


@csrf_exempt
def verify_wallet_fund(request):
    """Verify Razorpay payment for wallet funding and credit balance."""
    if request.method != "POST":
        return redirect('user_wallet')

    p_id = request.POST.get("razorpay_payment_id")
    o_id = request.POST.get("razorpay_order_id")
    sig = request.POST.get("razorpay_signature")

    if not all([p_id, o_id, sig]):
        return render(request, "payments/payment_failed.html")

    client = get_razorpay_client()
    try:
        client.utility.verify_payment_signature({
            "razorpay_payment_id": p_id,
            "razorpay_order_id": o_id,
            "razorpay_signature": sig,
        })

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(razorpay_order_id=o_id)
            if payment.status == "SUCCESS":
                return redirect('user_wallet')
                
            payment.razorpay_payment_id, payment.razorpay_signature = p_id, sig
            payment.status = "SUCCESS"
            payment.save()

            wallet, _ = Wallet.objects.get_or_create(user=payment.user)
            wallet.balance += payment.amount
            wallet.save()

            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type='Credit',
                amount=payment.amount,
                description=f'Added funds via Razorpay (Ref: {p_id})'
            )

        return render(request, "payments/payment_success.html", {"is_wallet": True, "payment": payment})

    except Exception as e:
        Payment.objects.filter(razorpay_order_id=o_id).update(status="FAILED")
        return render(request, "payments/payment_failed.html")
