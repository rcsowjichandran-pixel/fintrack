from collections import defaultdict
from datetime import date
from decimal import Decimal
from decimal import ROUND_HALF_UP
from io import BytesIO
import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

from django.contrib import messages
from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .forms import CategoryForm, GSTReportFilterForm, TransactionForm
from .models import Category, Gst, Ledger, Transaction

GST_RATE = Decimal('18.00')
PDF_GREEN = colors.HexColor('#31583B')
PDF_LIGHT_GREEN = colors.HexColor('#EAF1E8')
PDF_MUTED = colors.HexColor('#687367')
GEMINI_INTERACTIONS_URL = 'https://generativelanguage.googleapis.com/v1beta/interactions'
ANALYTICS_RESPONSE_SCHEMA = {
    'type': 'object',
    'properties': {
        'predictions': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'month': {'type': 'string'},
                    'projected_income': {'type': 'number'},
                    'projected_expense': {'type': 'number'},
                },
                'required': ['month', 'projected_income', 'projected_expense'],
            },
        },
        'insights': {'type': 'array', 'items': {'type': 'string'}},
        'recommendations': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['predictions', 'insights', 'recommendations'],
}


def dashboard(request):
    transactions = Transaction.objects.all()[:8]
    income = Transaction.objects.filter(type=Transaction.Type.INCOME).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    expenses = Transaction.objects.filter(type=Transaction.Type.EXPENSE).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    latest_ledger = Ledger.objects.order_by('-date', '-pk').first()
    return render(request, 'accounting/dashboard.html', {
        'transactions': transactions,
        'income': income,
        'expenses': expenses,
        'balance': latest_ledger.current_balance if latest_ledger else income - expenses,
        'transaction_count': Transaction.objects.count(),
    })


def add_transaction(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            with db_transaction.atomic():
                saved_transaction = form.save()
                gst_amount = (saved_transaction.amount * GST_RATE / Decimal('100')).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
                Gst.objects.create(
                    transaction=saved_transaction,
                    gst_percentage=GST_RATE,
                    gst_amount=gst_amount,
                )
            messages.success(request, 'Transaction saved and your ledger is up to date.')
            return redirect('dashboard')
    else:
        form = TransactionForm()

    return render(request, 'accounting/add_transaction.html', {
        'form': form,
        'gst_rate': GST_RATE,
    })


def categorize_transactions(request):
    if request.method == 'POST' and request.POST.get('action') == 'add_category':
        category_form = CategoryForm(request.POST)
        if category_form.is_valid():
            category_form.save()
            messages.success(request, 'Category created.')
            return redirect('accounting:categorize_transactions')
    elif request.method == 'POST':
        transaction_id = request.POST.get('transaction_id')
        transaction = get_object_or_404(Transaction, pk=transaction_id)
        category_id = request.POST.get('category_id')
        if category_id:
            transaction.category = get_object_or_404(Category, pk=category_id)
        else:
            transaction.category = None
        transaction.save(update_fields=['category'])
        messages.success(request, 'Transaction category updated.')
        return redirect('accounting:categorize_transactions')
    else:
        category_form = CategoryForm()

    return render(request, 'accounting/categorize_transactions.html', {
        'transactions': Transaction.objects.select_related('category').all(),
        'categories': Category.objects.all(),
        'category_form': category_form,
    })


def gst_report_options(request):
    return render(request, 'accounting/gst_report_options.html', {
        'form': GSTReportFilterForm(),
    })


def generate_gst_report(request):
    form = GSTReportFilterForm(request.GET)
    if not form.is_valid():
        return render(request, 'accounting/gst_report_options.html', {
            'form': form,
        }, status=400)

    filters = form.cleaned_data
    transactions = Transaction.objects.filter(
        tax_records__isnull=False,
    ).select_related('category').prefetch_related('tax_records').distinct()
    if filters['start_date']:
        transactions = transactions.filter(date__gte=filters['start_date'])
    if filters['end_date']:
        transactions = transactions.filter(date__lte=filters['end_date'])
    if filters['category']:
        transactions = transactions.filter(category=filters['category'])
    transactions = transactions.order_by('date', 'pk')

    taxable_total = Decimal('0.00')
    gst_collected = Decimal('0.00')
    gst_paid = Decimal('0.00')
    monthly = defaultdict(lambda: [Decimal('0.00'), Decimal('0.00'), Decimal('0.00')])
    by_category = defaultdict(lambda: [Decimal('0.00'), Decimal('0.00'), Decimal('0.00')])

    for item in transactions:
        tax_amount = sum(
            (record.gst_amount for record in item.tax_records.all()), Decimal('0.00')
        )
        taxable_total += item.amount
        if item.type == Transaction.Type.INCOME:
            gst_collected += tax_amount
            collected, paid = tax_amount, Decimal('0.00')
        else:
            gst_paid += tax_amount
            collected, paid = Decimal('0.00'), tax_amount
        month_key = item.date.strftime('%Y-%m')
        category_key = item.category.name if item.category else 'Uncategorized'
        for group in (monthly[month_key], by_category[category_key]):
            group[0] += item.amount
            group[1] += collected
            group[2] += paid

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=17 * mm, bottomMargin=17 * mm,
        title='FinTrack GST Report', author='FinTrack',
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='ReportTitle', parent=styles['Title'], fontName='Helvetica-Bold',
        fontSize=22, leading=27, textColor=PDF_GREEN, alignment=TA_LEFT,
        spaceAfter=4 * mm,
    ))
    styles.add(ParagraphStyle(
        name='ReportSub', parent=styles['Normal'], fontSize=9,
        textColor=PDF_MUTED, spaceAfter=5 * mm,
    ))
    styles.add(ParagraphStyle(
        name='SectionHeading', parent=styles['Heading2'], fontSize=12,
        leading=15, textColor=PDF_GREEN, spaceBefore=5 * mm, spaceAfter=2 * mm,
    ))
    styles.add(ParagraphStyle(
        name='SmallCell', parent=styles['BodyText'], fontSize=8, leading=10,
    ))

    def money(value):
        return f'INR {value:,.2f}'

    def make_table(rows, widths, right_columns=()):
        table = Table(rows, colWidths=widths, repeatRows=1, hAlign='LEFT')
        commands = [
            ('BACKGROUND', (0, 0), (-1, 0), PDF_GREEN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('LEADING', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), .35, colors.HexColor('#D9E0D7')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, PDF_LIGHT_GREEN]),
        ]
        for column in right_columns:
            commands.append(('ALIGN', (column, 1), (column, -1), 'RIGHT'))
        table.setStyle(TableStyle(commands))
        return table

    start_label = filters['start_date'].strftime('%d %b %Y') if filters['start_date'] else 'Beginning'
    end_label = filters['end_date'].strftime('%d %b %Y') if filters['end_date'] else 'Today'
    category_label = filters['category'].name if filters['category'] else 'All categories'
    story = [
        Paragraph('GST summary report', styles['ReportTitle']),
        Paragraph(
            f'Period: {escape(start_label)} to {escape(end_label)} '
            f'&nbsp;&nbsp; | &nbsp;&nbsp; Category: {escape(category_label)} '
            f'&nbsp;&nbsp; | &nbsp;&nbsp; Generated: {timezone.localdate():%d %b %Y}',
            styles['ReportSub'],
        ),
    ]
    summary_rows = [
        ['Tax summary', 'Amount'],
        ['Taxable transaction amount', money(taxable_total)],
        ['GST collected on income', money(gst_collected)],
        ['GST paid on expenses', money(gst_paid)],
        ['Net GST (collected less paid)', money(gst_collected - gst_paid)],
    ]
    story.extend([make_table(summary_rows, [105 * mm, 65 * mm], (1,)), Spacer(1, 4 * mm)])

    story.append(Paragraph('Monthly breakdown', styles['SectionHeading']))
    month_rows = [['Month', 'Taxable', 'GST collected', 'GST paid']]
    for key in sorted(monthly):
        values = monthly[key]
        month_rows.append([key, *(money(value) for value in values)])
    if len(month_rows) == 1:
        month_rows.append(['No matching transactions', money(Decimal('0')), money(Decimal('0')), money(Decimal('0'))])
    story.append(make_table(month_rows, [32 * mm, 45 * mm, 47 * mm, 46 * mm], (1, 2, 3)))

    story.append(Paragraph('Category breakdown', styles['SectionHeading']))
    category_rows = [['Category', 'Taxable', 'GST collected', 'GST paid']]
    for key in sorted(by_category, key=str.casefold):
        values = by_category[key]
        category_rows.append([Paragraph(escape(key), styles['SmallCell']), *(money(value) for value in values)])
    if len(category_rows) == 1:
        category_rows.append(['No matching transactions', money(Decimal('0')), money(Decimal('0')), money(Decimal('0'))])
    story.append(make_table(category_rows, [32 * mm, 45 * mm, 47 * mm, 46 * mm], (1, 2, 3)))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph('Only transactions with a saved GST record are included.', styles['ReportSub']))
    doc.build(story)
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename='fintrack-gst-report.pdf', content_type='application/pdf')


def generate_gst_bill(request, transaction_id):
    item = get_object_or_404(
        Transaction.objects.select_related('category').prefetch_related('tax_records'),
        pk=transaction_id,
    )
    gst_amount = sum(
        (record.gst_amount for record in item.tax_records.all()), Decimal('0.00')
    )
    gst_percentage = sum(
        (record.gst_percentage for record in item.tax_records.all()), Decimal('0.00')
    )
    total = item.amount + gst_amount

    def money(value):
        return f'INR {value:,.2f}'

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=22 * mm, leftMargin=22 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=f'FinTrack GST Bill {item.pk}', author='FinTrack',
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='BillTitle', parent=styles['Title'], fontName='Helvetica-Bold',
        fontSize=25, leading=30, textColor=PDF_GREEN, alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(
        name='BillMuted', parent=styles['Normal'], fontSize=9,
        leading=14, textColor=PDF_MUTED,
    ))
    styles.add(ParagraphStyle(
        name='BillDesc', parent=styles['BodyText'], fontSize=10, leading=14,
    ))
    story = [
        Paragraph('FINTRACK', styles['BillMuted']),
        Paragraph('GST bill', styles['BillTitle']),
        Spacer(1, 3 * mm),
        Paragraph(f'Bill reference: FT-{item.pk:06d}', styles['BillMuted']),
        Paragraph(f'Transaction date: {item.date:%d %b %Y}', styles['BillMuted']),
        Paragraph(f'Transaction type: {escape(item.get_type_display())}', styles['BillMuted']),
        Paragraph(f'Category: {escape(item.category.name if item.category else "Uncategorized")}', styles['BillMuted']),
        Spacer(1, 10 * mm),
    ]
    bill_rows = [
        ['Description', 'Taxable amount'],
        [Paragraph(escape(item.description).replace('\n', '<br/>'), styles['BillDesc']), money(item.amount)],
    ]
    bill_table = Table(bill_rows, colWidths=[115 * mm, 55 * mm], hAlign='LEFT')
    bill_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PDF_GREEN),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), .45, colors.HexColor('#D9E0D7')),
        ('BACKGROUND', (0, 1), (-1, -1), PDF_LIGHT_GREEN),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
    ]))
    story.extend([bill_table, Spacer(1, 8 * mm)])
    tax_label = 'GST collected' if item.type == Transaction.Type.INCOME else 'GST paid'
    totals = [
        ['Taxable amount', money(item.amount)],
        [f'GST ({gst_percentage:.2f}%)', money(gst_amount)],
        ['Total including GST', money(total)],
    ]
    totals_table = Table(totals, colWidths=[115 * mm, 55 * mm], hAlign='LEFT')
    totals_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -2), 'Helvetica'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, -1), (-1, -1), PDF_GREEN),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('LINEABOVE', (0, -1), (-1, -1), 1, PDF_GREEN),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.extend([totals_table, Spacer(1, 10 * mm), Paragraph(f'{tax_label} is recorded for this transaction.', styles['BillMuted'])])
    doc.build(story)
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f'fintrack-gst-bill-{item.pk}.pdf',
        content_type='application/pdf',
    )


def _subtract_months(value, months):
    month_index = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(month_index, 12)
    month = month_index + 1
    return date(year, month, min(value.day, 28))


def _extract_interaction_text(payload):
    for step in reversed(payload.get('steps', [])):
        if step.get('type') != 'model_output':
            continue
        text = ''.join(
            part.get('text', '')
            for part in step.get('content', [])
            if part.get('type') == 'text'
        )
        if text:
            return text
    return payload.get('output_text', '')


def _validate_analytics_result(result):
    if not isinstance(result, dict):
        raise ValueError('The response must be a JSON object.')
    for key in ('predictions', 'insights', 'recommendations'):
        if not isinstance(result.get(key), list):
            raise ValueError(f'The {key} field is missing or invalid.')
    predictions = []
    for row in result['predictions']:
        if not isinstance(row, dict) or not isinstance(row.get('month'), str):
            raise ValueError('A forecast entry is invalid.')
        clean_row = {'month': row['month']}
        for key in ('projected_income', 'projected_expense'):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('A forecast amount is invalid.')
            clean_row[key] = max(0, value)
        predictions.append(clean_row)
    if len(predictions) != 6:
        raise ValueError('The response must contain six monthly predictions.')
    result['predictions'] = predictions
    for key in ('insights', 'recommendations'):
        if any(not isinstance(item, str) for item in result[key]):
            raise ValueError(f'The {key} entries must be text.')
        result[key] = [item.strip() for item in result[key] if item.strip()]
    return result


def predictive_analytics(request):
    today = timezone.localdate()
    first_month = _subtract_months(today.replace(day=1), 23)
    first_month = first_month.replace(day=1)
    monthly_totals = defaultdict(lambda: {
        'income': Decimal('0.00'),
        'expense': Decimal('0.00'),
    })
    history_rows = list(
        Transaction.objects.filter(date__gte=first_month, date__lte=today)
        .values('date', 'type', 'amount')
        .order_by('date', 'pk')
    )
    for row in history_rows:
        key = row['date'].strftime('%Y-%m')
        type_key = 'income' if row['type'] == Transaction.Type.INCOME else 'expense'
        monthly_totals[key][type_key] += row['amount']

    labels = []
    history_income = []
    history_expenses = []
    for offset in range(24):
        month_date = _subtract_months(today.replace(day=1), 23 - offset).replace(day=1)
        label = month_date.strftime('%Y-%m')
        labels.append(label)
        history_income.append(float(monthly_totals[label]['income']))
        history_expenses.append(float(monthly_totals[label]['expense']))

    result = None
    error = None
    api_key = settings.GEMINI_API_KEY
    if not history_rows:
        error = 'Add some transactions from the last 24 months to generate financial insights.'
    elif not api_key:
        error = 'Gemini is not configured yet. Set the GEMINI_API_KEY environment variable to enable predictions.'
    else:
        prompt_data = [
            {
                'month': month,
                'type': transaction_type,
                'amount': float(monthly_totals[month][transaction_type]),
                'currency': 'INR',
            }
            for month in labels
            for transaction_type in ('income', 'expense')
            if monthly_totals[month][transaction_type] != 0
        ]
        prompt = (
            'Act as a careful financial analyst. Analyze the following monthly totals '
            'aggregated from the user\'s transaction history. Each item includes a month, '
            'transaction type, and total amount in INR. Forecast the next six months of '
            'income and expenses based only on these values. Identify spending patterns, '
            'uncertainty or limitations, and practical areas for financial improvement. '
            'Do not claim certainty or present this as professional financial advice. '
            'Return concise, specific, nonjudgmental findings. Use YYYY-MM month labels '
            'for all six future predictions. Ensure income and expense forecasts are '
            'non-negative numbers.\n\n'
            'Monthly transaction history (JSON):\n'
            f'{json.dumps(prompt_data, separators=(",", ":"))}'
        )
        request_body = json.dumps({
            'model': settings.GEMINI_MODEL,
            'input': prompt,
            'system_instruction': 'You are a cautious financial analyst. Output valid structured JSON only.',
            'response_format': {
                'type': 'text',
                'mime_type': 'application/json',
                'schema': ANALYTICS_RESPONSE_SCHEMA,
            },
            'store': False,
        }).encode('utf-8')
        api_request = Request(
            GEMINI_INTERACTIONS_URL,
            data=request_body,
            headers={
                'Content-Type': 'application/json',
                'x-goog-api-key': api_key,
            },
            method='POST',
        )
        try:
            with urlopen(api_request, timeout=30) as response:
                api_response = json.loads(response.read().decode('utf-8'))
            output_text = _extract_interaction_text(api_response)
            if not output_text:
                raise ValueError('Gemini returned an empty response.')
            result = _validate_analytics_result(json.loads(output_text))
        except HTTPError as exc:
            error = f'Gemini could not generate the report (HTTP {exc.code}). Please try again later.'
        except (URLError, TimeoutError):
            error = 'Could not connect to Gemini. Check the server connection and try again.'
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError, KeyError):
            error = 'Gemini returned an invalid analytics response. Please try again.'
        except Exception:
            error = 'The analytics request failed unexpectedly. Please try again later.'

    predictions = result['predictions'] if result else []
    chart_labels = labels + [row['month'] for row in predictions]
    historical_income = history_income + [None] * len(predictions)
    historical_expenses = history_expenses + [None] * len(predictions)
    projected_income = [None] * max(len(labels) - 1, 0)
    projected_expenses = [None] * max(len(labels) - 1, 0)
    projected_income.append(history_income[-1] if history_income else 0)
    projected_expenses.append(history_expenses[-1] if history_expenses else 0)
    projected_income.extend(row['projected_income'] for row in predictions)
    projected_expenses.extend(row['projected_expense'] for row in predictions)
    chart_data = {
        'labels': chart_labels,
        'historyIncome': historical_income,
        'historyExpenses': historical_expenses,
        'projectedIncome': projected_income,
        'projectedExpenses': projected_expenses,
    }
    return render(request, 'accounting/analytics_report.html', {
        'predictions': predictions,
        'insights': result['insights'] if result else [],
        'recommendations': result['recommendations'] if result else [],
        'chart_data': chart_data,
        'error': error,
        'has_history': bool(history_rows),
        'history_months': 24,
    })
