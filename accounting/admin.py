from django.contrib import admin

from .models import Category, Gst, Ledger, Transaction


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ('name',)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'description', 'type', 'category', 'amount')
    list_filter = ('type', 'date')
    search_fields = ('description',)


@admin.register(Gst)
class GstAdmin(admin.ModelAdmin):
    list_display = ('transaction', 'gst_percentage', 'gst_amount')


@admin.register(Ledger)
class LedgerAdmin(admin.ModelAdmin):
    list_display = ('date', 'transaction', 'current_balance')
    list_filter = ('date',)
