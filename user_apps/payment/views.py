import json
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from admin_apps.offers.services import process_referrer_reward
from user_apps.core.models import CartItem, Order, Wallet, WalletTransaction

from .models import Payment
from .services import get_razorpay_client

ONLINE_PAYMENT_DISCOUNT_PCT = Decimal("3")   # 5% off when switching COD → Online
ORDERS_PER_PAGE = 10
TRANSACTIONS_PER_PAGE = 15

@login_required
@never_cache
def payment_list(request):
    user = request.user

    # --- Summary metrics ---
    orders_qs = Order.objects.filter(user=user).order_by("-created_at")
    total_spent = orders_qs.aggregate(total=Sum("total_amount"))["total"] or 0

    wallet, _ = Wallet.objects.get_or_create(user=user)
    total_rewards = (
        WalletTransaction.objects
        .filter(wallet=wallet, transaction_type="Credit")
        .aggregate(total=Sum("amount"))["total"] or 0
    )
    transactions_qs = wallet.transactions.all().order_by("-timestamp")

    # --- Paginate orders ---
    orders_page = _paginate(orders_qs, request.GET.get("orders_page", 1), ORDERS_PER_PAGE)

    # --- Paginate wallet transactions ---
    tx_page = _paginate(transactions_qs, request.GET.get("tx_page", 1), TRANSACTIONS_PER_PAGE)

    return render(request, "payments/payment_list.html", {
        "orders": orders_page,
        "transactions": tx_page,
        "wallet": wallet,
        "total_spent": total_spent,
        "total_cashback": total_rewards,
        "total_orders_count": orders_qs.count(),
        "total_tx_count": transactions_qs.count(),
    })



@login_required
def start_payment(request, order_id):
    """
    Step 1: Initialize a Razorpay payment session for a pending order.

    - Fetches the user's unpaid, pending order
    - Creates a corresponding order on Razorpay
    - Stores a local Payment record for tracking
    - Renders the Razorpay checkout page
    """
    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user,
        is_paid=False,
        status="Pending",
    )

    paise = _to_paise(order.total_amount)
    client = get_razorpay_client()

    try:
        razor_order = client.order.create({
            "amount": paise,
            "currency": "INR",
            "receipt": f"order_rcpt_{order.id}",
            "payment_capture": 1,
        })

        payment = Payment.objects.create(
            order=order,
            gateway="RAZORPAY",
            amount=order.total_amount,
            currency="INR",
            status="PENDING",
            razorpay_order_id=razor_order["id"],
        )

        # Store the Razorpay order ID on our order for easy lookup later
        order.razorpay_order_id = razor_order["id"]
        order.save(update_fields=["razorpay_order_id"])

        return render(request, "payments/razorpay_checkout.html", {
            "order": order,
            "payment": payment,
            "razorpay_key": settings.RAZORPAY_KEY_ID,
            "razorpay_order_id": razor_order["id"],
            "amount": paise,
            "currency": "INR",
        })

    except Exception as e:
        print(f"[Payment Error] Razorpay order creation failed: {e}")
        return redirect("order_detail", order_uuid=order.uuid)


@login_required
def pay_online_cod(request, order_id):
    """
    Allow a Cash-on-Delivery order to be paid online in exchange for a 5% discount.

    - Only available for unpaid COD orders in Pending / Confirmed / Processing state
    - Calculates the discounted total and creates a Razorpay order for that amount
    - The discount is applied to the order record inside _complete_order_payment()
    """
    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user,
        is_paid=False,
        payment_method="cod",
        status__in=["Pending", "Confirmed", "Processing"],
    )

    discount_fraction = ONLINE_PAYMENT_DISCOUNT_PCT / Decimal("100")
    online_discount = round(order.total_amount * discount_fraction, 2)
    discounted_total = max(Decimal("0"), order.total_amount - online_discount)
    paise = _to_paise(discounted_total)

    if paise <= 0:
        messages.error(request, "Invalid payment amount.")
        return redirect("order_detail", order_uuid=order.uuid)

    client = get_razorpay_client()
    try:
        razor_order = client.order.create({
            "amount": paise,
            "currency": "INR",
            "receipt": f"cod_online_{order.id}",
            "payment_capture": 1,
        })

        payment = Payment.objects.create(
            order=order,
            gateway="RAZORPAY",
            amount=discounted_total,
            currency="INR",
            status="PENDING",
            razorpay_order_id=razor_order["id"],
        )

        order.razorpay_order_id = razor_order["id"]
        order.save(update_fields=["razorpay_order_id"])

        return render(request, "payments/razorpay_checkout.html", {
            "order": order,
            "payment": payment,
            "razorpay_key": settings.RAZORPAY_KEY_ID,
            "razorpay_order_id": razor_order["id"],
            "amount": paise,
            "currency": "INR",
            # Extra context for the template to show discount info
            "online_discount": online_discount,
            "discounted_total": discounted_total,
            "discount_pct": ONLINE_PAYMENT_DISCOUNT_PCT,
            "is_cod_switch": True,
        })

    except Exception as e:
        print(f"[Payment Error] COD-to-online switch failed: {e}")
        messages.error(request, "Payment initialization failed. Please try again.")
        return redirect("order_detail", order_uuid=order.uuid)


def _complete_order_payment(order, payment, razorpay_payment_id, razorpay_signature):
    """
    Atomically finalize an order after Razorpay confirms payment.

    Steps:
    1. Lock the Payment row to prevent duplicate processing
    2. Mark the payment as SUCCESS
    3. Apply the 5% online discount if this was a COD → Online switch
    4. Mark the order as paid and confirmed
    5. Trigger referral reward logic for the buyer
    6. Clean up any matching cart items
    """
    with transaction.atomic():
        # Lock to prevent race conditions (e.g. webhook + callback arriving at the same time)
        payment = Payment.objects.select_for_update().get(id=payment.id)

        if payment.status == "SUCCESS":
            return order  # Already processed — nothing to do

        # --- Mark payment as successful ---
        payment.razorpay_payment_id = razorpay_payment_id
        payment.razorpay_signature = razorpay_signature
        payment.status = "SUCCESS"
        payment.save()

        # --- Apply COD → Online discount if applicable ---
        if order.payment_method == "cod" and not order.is_paid:
            online_discount = round(order.total_amount * Decimal("0.05"), 2)
            order.discount += online_discount
            order.total_amount = max(Decimal("0"), order.total_amount - online_discount)

        # --- Confirm the order ---
        order.is_paid = True
        order.status = "Confirmed"
        order.payment_method = "razorpay"
        order.save()

        # --- Reward the referrer (if applicable) ---
        process_referrer_reward(order.user, order=order)

        # --- Remove ordered items from the buyer's cart ---
        for order_item in order.items.all():
            CartItem.objects.filter(
                cart__user=order.user,
                product=order_item.product,
                variant=order_item.variant,
            ).delete()

    return order


def _verify_and_complete_payment(razorpay_order_id, razorpay_payment_id, razorpay_signature):
    """
    Core verification logic used by both AJAX and Redirect-based flows.
    Verifies the signature and marks the order as paid.
    Returns (success: bool, order: Order, error_msg: str)
    """
    client = get_razorpay_client()
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id":   razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature":  razorpay_signature,
        })

        payment = Payment.objects.get(razorpay_order_id=razorpay_order_id)
        order = _complete_order_payment(payment.order, payment, razorpay_payment_id, razorpay_signature)
        return True, order, payment, None

    except Exception as e:
        error_msg = str(e)
        print(f"[Payment Error] Verification failed: {error_msg}")
        Payment.objects.filter(razorpay_order_id=razorpay_order_id).update(status="FAILED")
        payment = Payment.objects.filter(razorpay_order_id=razorpay_order_id).first()
        return False, None, payment, error_msg


@csrf_exempt
def verify_payment(request):
    """
    Step 3 (AJAX path): Verify the Razorpay payment signature and complete the order.
    """
    if request.method != "POST":
        return render(request, "payments/payment_failed.html")

    payment_id = request.POST.get("razorpay_payment_id")
    order_id   = request.POST.get("razorpay_order_id")
    signature  = request.POST.get("razorpay_signature")

    if not all([payment_id, order_id, signature]):
        return render(request, "payments/payment_failed.html", {"reason": "Missing required payment fields."})

    success, order, payment, error_msg = _verify_and_complete_payment(order_id, payment_id, signature)

    if success:
        return render(request, "payments/payment_success.html", {"order": order, "payment": payment})
    else:
        return render(request, "payments/payment_failed.html", {"reason": error_msg, "payment": payment})


@csrf_exempt
def razorpay_callback(request):
    """
    Step 3 (redirect path): Redirect version of verify_payment.
    """
    if request.method != "POST":
        return redirect("payments:failed")

    payment_id = request.POST.get("razorpay_payment_id")
    order_id   = request.POST.get("razorpay_order_id")
    signature  = request.POST.get("razorpay_signature")

    if not all([payment_id, order_id, signature]):
        return redirect(f"{reverse('payments:failed')}?reason=Missing+payment+fields")

    success, order, payment, error_msg = _verify_and_complete_payment(order_id, payment_id, signature)

    if success:
        return redirect("payments:success_with_order", order_uuid=order.uuid)
    else:
        return redirect(f"{reverse('payments:failed')}?reason={error_msg}")



def payment_success(request, order_uuid=None):
    """
    Show the payment success screen.

    Handles two cases:
    - Order payment: identified by order_uuid in the URL
    - Wallet top-up: identified by ?payment_id= query parameter
    """
    context = {}

    if order_uuid:
        order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
        context["order"] = order
        # Attempt to find the successful payment for this order
        context["payment"] = Payment.objects.filter(order=order, status="SUCCESS").order_by("-created_at").first()

    wallet_payment_id = request.GET.get("payment_id")
    if wallet_payment_id:
        context["payment"] = get_object_or_404(
            Payment, id=wallet_payment_id, user=request.user, status="SUCCESS"
        )
        context["is_wallet"] = True

    return render(request, "payments/payment_success.html", context)


def payment_failed(request):
    """Show the payment failure screen."""
    reason = request.GET.get('reason')
    return render(request, "payments/payment_failed.html", {"reason": reason})


@login_required
def add_wallet_fund(request):
    """
    Step 1: Initialize a Razorpay payment to top up the user's wallet.

    Accepts a POST with {'amount': <INR value>} and renders the
    Razorpay checkout page. On success, verify_wallet_fund() credits the balance.
    """
    if request.method != "POST":
        return redirect("user_wallet")

    try:
        amount = Decimal(str(request.POST.get("amount", 0)))
        if amount <= 0:
            raise ValueError("Amount must be positive.")
    except (ValueError, Exception):
        messages.error(request, "Please enter a valid amount.")
        return redirect("user_wallet")

    paise = _to_paise(amount)
    client = get_razorpay_client()

    try:
        razor_order = client.order.create({
            "amount": paise,
            "currency": "INR",
            "payment_capture": 1,
        })

        payment = Payment.objects.create(
            user=request.user,
            amount=amount,
            gateway="RAZORPAY",
            status="PENDING",
            razorpay_order_id=razor_order["id"],
        )

        return render(request, "payments/razorpay_wallet_checkout.html", {
            "payment": payment,
            "razorpay_key": settings.RAZORPAY_KEY_ID,
            "razorpay_order_id": razor_order["id"],
            "amount": paise,
        })

    except Exception as e:
        print(f"[Wallet Error] Fund initialization failed: {e}")
        messages.error(request, "Payment initialization failed. Please try again.")
        return redirect("user_wallet")


@csrf_exempt
def verify_wallet_fund(request):
    """
    Step 2: Verify Razorpay signature for a wallet top-up and credit the balance.

    On success:
    - Marks the Payment as SUCCESS
    - Adds the amount to the user's wallet balance
    - Creates a WalletTransaction record for audit trail
    """
    if request.method != "POST":
        return redirect("user_wallet")

    payment_id = request.POST.get("razorpay_payment_id")
    order_id   = request.POST.get("razorpay_order_id")
    signature  = request.POST.get("razorpay_signature")

    if not all([payment_id, order_id, signature]):
        return render(request, "payments/payment_failed.html")

    client = get_razorpay_client()
    try:
        client.utility.verify_payment_signature({
            "razorpay_payment_id": payment_id,
            "razorpay_order_id":   order_id,
            "razorpay_signature":  signature,
        })

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(razorpay_order_id=order_id)

            if payment.status == "SUCCESS":
                return redirect("user_wallet")  # Already processed

            payment.razorpay_payment_id = payment_id
            payment.razorpay_signature  = signature
            payment.status = "SUCCESS"
            payment.save()

            wallet, _ = Wallet.objects.get_or_create(user=payment.user)
            wallet.balance += payment.amount
            wallet.save()

            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type="Credit",
                amount=payment.amount,
                description=f"Wallet top-up via Razorpay (Ref: {payment_id})",
            )

        return redirect(f"{reverse('payments:success')}?payment_id={payment.id}")

    except Exception as e:
        error_msg = str(e)
        print(f"[Wallet Error] Fund verification failed: {error_msg}")
        Payment.objects.filter(razorpay_order_id=order_id).update(status="FAILED")
        return render(request, "payments/payment_failed.html", {"reason": error_msg})


@login_required
def create_razorpay_order(request):
    """
    AJAX endpoint to create a Razorpay order on-the-fly.

    Accepts POST with either:
    - {'order_id': <int>}  → uses that order's total amount
    - {'amount': <float>}  → uses the provided INR amount (e.g. for wallet top-up)

    Returns JSON: { id, amount, currency }
    """
    if request.method != "POST":
        return JsonResponse({"error": "Only POST requests are allowed."}, status=405)

    order_id   = request.POST.get("order_id")
    amount_val = request.POST.get("amount")
    client = get_razorpay_client()

    try:
        if order_id:
            order = get_object_or_404(Order, id=order_id, user=request.user)
            paise   = _to_paise(order.total_amount)
            receipt = f"order_{order.id}"
        elif amount_val:
            paise   = _to_paise(Decimal(str(amount_val)))
            receipt = f"wallet_{request.user.id}_{int(timezone.now().timestamp())}"
        else:
            return JsonResponse({"error": "Provide either 'order_id' or 'amount'."}, status=400)

        razor_order = client.order.create({
            "amount": paise,
            "currency": "INR",
            "receipt": receipt,
            "payment_capture": 1,
        })

        return JsonResponse({
            "id":       razor_order["id"],
            "amount":   razor_order["amount"],
            "currency": razor_order["currency"],
        })

    except Exception as e:
        print(f"[Payment Error] AJAX order creation failed: {e}")
        return JsonResponse({"error": str(e)}, status=500)


def _to_paise(amount: Decimal) -> int:
    """Convert an INR Decimal amount to paise (smallest unit Razorpay expects)."""
    return int(amount * 100)


def _paginate(queryset, page_number, per_page):
    """
    Paginate a queryset. Returns page 1 if the requested page is invalid or out of range.
    """
    paginator = Paginator(queryset, per_page)
    try:
        return paginator.page(page_number)
    except (PageNotAnInteger, EmptyPage):
        return paginator.page(1)