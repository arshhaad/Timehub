from decimal import Decimal
from django.db import transaction
from admin_apps.offers.models import ReferralOffer
from user_apps.core.models import Wallet, WalletTransaction


def _credit_wallet_and_notify(user, amount, description, notification_message):
    """Helper: credit wallet + create notification if transaction doesn't already exist."""
    from user_apps.core.models import Notification

    wallet, _ = Wallet.objects.get_or_create(user=user)
    if WalletTransaction.objects.filter(wallet=wallet, description=description).exists():
        return False  # Already rewarded, skip

    wallet.balance += amount
    wallet.save()

    WalletTransaction.objects.create(
        wallet=wallet,
        transaction_type='Credit',
        amount=amount,
        description=description,
    )

    Notification.objects.create(
        user=user,
        message=notification_message,
    )
    return True


def process_referee_reward(user):
    """
    Called immediately after referee (user) completes signup/verification.
    Credits:
      - The REFEREE with signup_reward (admin-configured)
      - The REFERRER with referrer_reward (admin-configured)
    """
    if not user.referred_by:
        return False

    referral_offer = ReferralOffer.objects.filter(is_active=True).first()
    if not referral_offer:
        return False

    referrer = user.referred_by
    rewarded_anyone = False

    with transaction.atomic():
        # ── 1. REFEREE SIGNUP REWARD ──────────────────────────────────────
        signup_reward = referral_offer.referee_signup_reward
        if signup_reward and signup_reward > 0:
            desc = f"Referral signup bonus (referred by {referrer.email})"
            msg = (
                f"🎉 Welcome bonus! You've received ₹{signup_reward} cashback in your wallet "
                f"for joining TimeHub via a referral link."
            )
            if _credit_wallet_and_notify(user, signup_reward, desc, msg):
                rewarded_anyone = True

        # ── 2. REFERRER REWARD (ON SIGNUP) ──────────────────────────────
        referrer_reward = referral_offer.referrer_reward
        if referrer_reward and referrer_reward > 0:
            desc = f"Referral reward: {user.email} joined TimeHub"
            msg = (
                f"🎁 Great news! You've earned ₹{referrer_reward} cashback because "
                f"{user.first_name or user.email} joined TimeHub using your referral link."
            )
            if _credit_wallet_and_notify(referrer, referrer_reward, desc, msg):
                rewarded_anyone = True

    return rewarded_anyone


def process_referrer_reward(referee, order=None):
    """
    Called after the referee's first successful confirmed order.
    Credits:
      - The REFEREE with referee_order_reward (admin-configured)
    Pass `order` explicitly to handle COD orders where is_paid is set
    within the same DB transaction and the count check may lag.
    """
    from user_apps.core.models import Order

    if not referee.referred_by:
        return False

    # If an order is passed, check whether it is the user's FIRST paid order.
    # We include the current order manually so it counts even inside a transaction.
    if order:
        paid_before = Order.objects.filter(user=referee, is_paid=True).exclude(pk=order.pk).count()
        if paid_before >= 1:
            return False  # Already had a paid order before this one
    else:
        paid_orders_count = Order.objects.filter(user=referee, is_paid=True).count()
        if paid_orders_count != 1:
            return False

    referral_offer = ReferralOffer.objects.filter(is_active=True).first()
    if not referral_offer:
        return False

    referrer = referee.referred_by

    with transaction.atomic():
        rewarded_anyone = False

        # ── REFEREE ORDER REWARD ─────────────────────────────────────────
        referee_order_reward = referral_offer.referee_order_reward
        if referee_order_reward and referee_order_reward > 0:
            desc = f"Referral first-order cashback (referred by {referrer.email})"
            msg = (
                f"💰 Your order has been confirmed! As a referral reward, "
                f"₹{referee_order_reward} cashback has been added to your wallet. "
                f"Thank you for shopping on TimeHub!"
            )
            rewarded = _credit_wallet_and_notify(referee, referee_order_reward, desc, msg)
            if rewarded:
                rewarded_anyone = True

        # ── REFERRER REWARD (ON ORDER) ───────────────────────────────────
        referrer_reward = referral_offer.referrer_reward
        if referrer_reward and referrer_reward > 0:
            desc = f"Referral commission: {referee.email} first order"
            msg = (
                f"🎁 Congratulations! You've earned ₹{referrer_reward} cashback because "
                f"{referee.first_name or referee.email} successfully placed their first order. "
                f"Keep sharing TimeHub to earn more!"
            )
            if _credit_wallet_and_notify(referrer, referrer_reward, desc, msg):
                rewarded_anyone = True

    return rewarded_anyone


def get_referral_first_order_discount(user, items=None, subtotal=None):
    """Calculate discount for referee's first order, restricted to the 2 most expensive products."""
    if not user.is_authenticated or not user.referred_by:
        return Decimal('0.00')

    from user_apps.core.models import Order
    if Order.objects.filter(user=user, is_paid=True).exists():
        return Decimal('0.00')  # Not their first paid order

    referral_offer = ReferralOffer.objects.filter(is_active=True).first()
    if not referral_offer:
        return Decimal('0.00')

    percent = Decimal(referral_offer.referee_discount_percent)

    if items:
        # Sort most expensive items first
        sorted_items = sorted(
            items,
            key=lambda x: (x.variant.display_price if x.variant else x.product.display_price),
            reverse=True
        )

        discountable_subtotal = Decimal('0.00')
        units_counted = 0
        MAX_UNITS = 2

        for item in sorted_items:
            if units_counted >= MAX_UNITS:
                break
            price = item.variant.display_price if item.variant else item.product.display_price
            take_qty = min(item.quantity, MAX_UNITS - units_counted)
            discountable_subtotal += price * take_qty
            units_counted += take_qty

        discount = (discountable_subtotal * percent) / Decimal('100.00')

    elif subtotal:
        discount = (subtotal * percent) / Decimal('100.00')
    else:
        return Decimal('0.00')

    return round(discount, 2)
