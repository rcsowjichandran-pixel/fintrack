from decimal import Decimal

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Ledger, Transaction


def rebuild_ledger():
    """Recalculate every running balance in date order."""
    balance = Decimal('0.00')
    for transaction in Transaction.objects.order_by('date', 'pk'):
        if transaction.type == Transaction.Type.INCOME:
            balance += transaction.amount
        else:
            balance -= transaction.amount
        Ledger.objects.update_or_create(
            transaction=transaction,
            defaults={'date': transaction.date, 'current_balance': balance},
        )


@receiver(post_save, sender=Transaction)
@receiver(post_delete, sender=Transaction)
def update_running_ledger(**kwargs):
    rebuild_ledger()
