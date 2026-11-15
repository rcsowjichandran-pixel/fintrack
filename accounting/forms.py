from django import forms

from .models import Category, Transaction


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'placeholder': 'e.g. Groceries',
                'maxlength': '100',
            }),
        }


class GSTReportFilterForm(forms.Form):
    start_date = forms.DateField(
        required=False,
        label='From date',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    end_date = forms.DateField(
        required=False,
        label='To date',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        required=False,
        empty_label='All categories',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.all()

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError('The start date must be on or before the end date.')
        return cleaned_data


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['date', 'description', 'amount', 'type', 'category']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'What was this transaction for?',
            }),
            'amount': forms.NumberInput(attrs={
                'min': '0.01',
                'step': '0.01',
                'placeholder': '0.00',
                'inputmode': 'decimal',
            }),
            'type': forms.Select(),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Enter an amount greater than zero.')
        return amount
