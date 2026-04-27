from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.db.models import Sum
from user_apps.core.models import Order, Wallet, WalletTransaction


@login_required
@never_cache
def payment_list(request):
    """Shows all payments made by the user and their cashback/wallet credits."""
    user = request.user

    # All orders — used to display payment history
    orders = Order.objects.filter(user=user).order_by('-created_at')
    total_spent = orders.aggregate(total=Sum('total_amount'))['total'] or 0

    # Wallet & transactions
    wallet = None
    transactions = []
    total_cashback = 0
    try:
        wallet = user.wallet
        transactions = wallet.transactions.all().order_by('-timestamp')
        total_cashback = (
            transactions.filter(transaction_type='Credit')
            .aggregate(total=Sum('amount'))['total'] or 0
        )
    except Exception:
        pass

    context = {
        'orders': orders,
        'total_spent': total_spent,
        'wallet': wallet,
        'transactions': transactions,
        'total_cashback': total_cashback,
    }
    return render(request, 'payment_list.html', context)
