from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import CategoryForm, GSTReportFilterForm, TransactionForm
from .models import Category, Gst, Ledger, Transaction


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}, SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class ProjectFixtureTestCase(TestCase):
    fixtures = ['finance_sample.json']


class TransactionViewTests(ProjectFixtureTestCase):
    def test_add_transaction_get_renders_form(self):
        response = self.client.get(reverse('accounting:add_transaction'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'TRANSACTION DETAILS')
        self.assertContains(response, 'name="category"')

    def test_add_transaction_post_saves_transaction_gst_and_ledger(self):
        starting_count = Transaction.objects.count()
        category = Category.objects.get(name='Salary')

        response = self.client.post(reverse('accounting:add_transaction'), {
            'date': '2026-11-15',
            'description': 'Client project payment',
            'amount': '1250.50',
            'type': Transaction.Type.INCOME,
            'category': category.pk,
        })

        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(Transaction.objects.count(), starting_count + 1)
        saved = Transaction.objects.get(description='Client project payment')
        self.assertEqual(saved.category, category)
        self.assertEqual(saved.amount, Decimal('1250.50'))
        tax_record = Gst.objects.get(transaction=saved)
        self.assertEqual(tax_record.gst_percentage, Decimal('18.00'))
        self.assertEqual(tax_record.gst_amount, Decimal('225.09'))
        self.assertEqual(saved.ledger_entry.date, date(2026, 11, 15))
        self.assertEqual(
            saved.ledger_entry.current_balance,
            sum(
                (tx.amount if tx.type == Transaction.Type.INCOME else -tx.amount)
                for tx in Transaction.objects.all()
            ),
        )


class GSTReportViewTests(ProjectFixtureTestCase):
    def test_gst_report_returns_downloadable_pdf(self):
        response = self.client.get(reverse('accounting:generate_gst_report'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment;', response['Content-Disposition'])
        pdf_content = b''.join(response.streaming_content)
        response.close()
        self.assertTrue(pdf_content.startswith(b'%PDF-'))
        self.assertGreater(len(pdf_content), 1000)

    def test_gst_report_accepts_date_and_category_filters(self):
        category = Category.objects.get(name='Groceries')
        response = self.client.get(reverse('accounting:generate_gst_report'), {
            'start_date': '2025-01-01',
            'end_date': '2025-12-31',
            'category': category.pk,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
        response.close()


class AccountingFormTests(ProjectFixtureTestCase):
    def test_transaction_form_accepts_valid_transaction(self):
        form = TransactionForm(data={
            'date': '2025-06-15',
            'description': 'Market supplies',
            'amount': '89.50',
            'type': Transaction.Type.EXPENSE,
            'category': Category.objects.get(name='Groceries').pk,
        })

        self.assertTrue(form.is_valid(), form.errors)

    def test_transaction_form_rejects_zero_amount(self):
        form = TransactionForm(data={
            'date': '2025-06-15',
            'description': 'Invalid transaction',
            'amount': '0.00',
            'type': Transaction.Type.EXPENSE,
            'category': '',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('amount', form.errors)

    def test_category_form_validates_unique_name(self):
        duplicate = CategoryForm(data={'name': 'Groceries'})
        new_category = CategoryForm(data={'name': 'Utilities'})

        self.assertFalse(duplicate.is_valid())
        self.assertTrue(new_category.is_valid(), new_category.errors)

    def test_gst_report_form_rejects_reversed_date_range(self):
        form = GSTReportFilterForm(data={
            'start_date': '2025-12-31',
            'end_date': '2025-01-01',
        })

        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())
