from decimal import Decimal
from django.db import transaction
from admin_apps.offers.models import ReferralOffer
from user_apps.core.models import Wallet, WalletTransaction

def process_referee_reward(user):
    """
    Previously credited rewards on signup. 
    Now does nothing because rewards are consolidated into process_referrer_reward 
    which runs after the first confirmed purchase.
    """
    return False

def process_referrer_reward(referee):
    """
    Credits rewards to BOTH the referrer and the referee after the referee's first purchase is confirmed/paid.
    This fulfills the requirement that rewards are only issued after a verified purchase.
    """
    from user_apps.core.models import Order, Wallet, WalletTransaction
    
    # Check if this is the referee's first PAID order
    # Note: This is called after order.is_paid is set to True
    paid_orders = Order.objects.filter(user=referee, is_paid=True).order_by('created_at')
    paid_orders_count = paid_orders.count()
    
    if paid_orders_count != 1:
        return False

    referral_offer = ReferralOffer.objects.filter(is_active=True).first()
    if referral_offer and referee.referred_by:
        with transaction.atomic():
            # 1. Reward the Referrer
            referrer_wallet, _ = Wallet.objects.get_or_create(user=referee.referred_by)
            referrer_reward_amount = referral_offer.referrer_reward
            
            if referrer_reward_amount > 0:
                reward_desc_referrer = f"Referral reward: {referee.email} completed their first purchase"
                if not WalletTransaction.objects.filter(wallet=referrer_wallet, description=reward_desc_referrer).exists():
                    referrer_wallet.balance += referrer_reward_amount
                    referrer_wallet.save()
                    WalletTransaction.objects.create(
                        wallet=referrer_wallet,
                        transaction_type='Credit',
                        amount=referrer_reward_amount,
                        description=reward_desc_referrer
                    )

            # 2. Reward the Referee (New User) - both signup and order rewards
            referee_wallet, _ = Wallet.objects.get_or_create(user=referee)
            total_referee_reward = referral_offer.referee_signup_reward + referral_offer.referee_order_reward
            
            if total_referee_reward > 0:
                reward_desc_referee = "Referral reward for joining and completing your first purchase"
                if not WalletTransaction.objects.filter(wallet=referee_wallet, description=reward_desc_referee).exists():
                    referee_wallet.balance += total_referee_reward
                    referee_wallet.save()
                    WalletTransaction.objects.create(
                        wallet=referee_wallet,
                        transaction_type='Credit',
                        amount=total_referee_reward,
                        description=reward_desc_referee
                    )
            return True
    return False


def get_referral_first_order_discount(user, items=None, subtotal=None):
    """Calculate discount for referee's first order, restricted to the 2 most expensive products."""
    if not user.is_authenticated or not user.referred_by:
        return Decimal('0.00')
    
    from user_apps.core.models import Order
    if Order.objects.filter(user=user, is_paid=True).exists():
        return Decimal('0.00') # Not their first paid order
        
    referral_offer = ReferralOffer.objects.filter(is_active=True).first()
    if referral_offer:
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
            # Fallback if items list not provided
            discount = (subtotal * percent) / Decimal('100.00')
        else:
            return Decimal('0.00')
            
        return round(discount, 2)
    return Decimal('0.00')
