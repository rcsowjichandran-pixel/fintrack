from django.urls import path

from . import views


app_name = 'accounting'

urlpatterns = [
    path('transactions/add/', views.add_transaction, name='add_transaction'),
    path('transactions/categories/', views.categorize_transactions, name='categorize_transactions'),
    path('reports/gst/', views.gst_report_options, name='gst_report_options'),
    path('reports/gst/download/', views.generate_gst_report, name='generate_gst_report'),
    path('transactions/<int:transaction_id>/gst-bill/', views.generate_gst_bill, name='generate_gst_bill'),
    path('analytics/', views.predictive_analytics, name='predictive_analytics'),
]
