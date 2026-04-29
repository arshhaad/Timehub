from decimal import Decimal
from django.db import transaction
from admin_apps.offers.models import ReferralOffer
from user_apps.core.models import Wallet, WalletTransaction

def process_referee_reward(user):
    """Credit initial signup reward to the new user who joined using a referral code."""
    referral_offer = ReferralOffer.objects.filter(is_active=True).first()
    if referral_offer and user.referred_by:
        with transaction.atomic():
            wallet, created = Wallet.objects.get_or_create(user=user)
            wallet.balance += referral_offer.referee_signup_reward
            wallet.save()
            
            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type='Credit',
                amount=referral_offer.referee_signup_reward,
                description=f"Referral signup reward (Initial part) - Referred by {user.referred_by.email}"
            )
            return True
    return False

def process_referrer_reward(referee):
    """Credit rewards to both referrer and referee when the referee makes their first purchase."""
    referrer = referee.referred_by
    if not referrer:
        return False
        
    # Check if this is the referee's first PAID order
    from user_apps.core.models import Order
    paid_orders_count = Order.objects.filter(user=referee, is_paid=True).count()
    if paid_orders_count != 1: 
        return False

    referral_offer = ReferralOffer.objects.filter(is_active=True).first()
    if referral_offer:
        with transaction.atomic():
            # Reward Referrer
            referrer_wallet, _ = Wallet.objects.get_or_create(user=referrer)
            referrer_wallet.balance += referral_offer.referrer_reward
            referrer_wallet.save()
            
            WalletTransaction.objects.create(
                wallet=referrer_wallet,
                transaction_type='Credit',
                amount=referral_offer.referrer_reward,
                description=f"Referral reward for {referee.email}'s first purchase"
            )

            # Reward Referee (Remaining part)
            referee_wallet, _ = Wallet.objects.get_or_create(user=referee)
            referee_wallet.balance += referral_offer.referee_order_reward
            referee_wallet.save()
            
            WalletTransaction.objects.create(
                wallet=referee_wallet,
                transaction_type='Credit',
                amount=referral_offer.referee_order_reward,
                description=f"Referral reward for completing your first purchase"
            )
            return True
    return False

def get_referral_first_order_discount(user, subtotal):
    """Calculate discount for referee's first order."""
    if not user.is_authenticated or not user.referred_by:
        return Decimal('0.00')
    
    from user_apps.core.models import Order
    if Order.objects.filter(user=user, is_paid=True).exists():
        return Decimal('0.00') # Not their first paid order
        
    referral_offer = ReferralOffer.objects.filter(is_active=True).first()
    if referral_offer:
        discount = (subtotal * Decimal(referral_offer.referee_discount_percent)) / Decimal('100.00')
        return round(discount, 2)
    return Decimal('0.00')
