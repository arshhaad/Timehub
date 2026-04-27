from django import forms
from .models import Coupon
from django.utils import timezone

class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = [
            'code', 'discount_type', 'discount_value', 
            'min_purchase_amount', 'max_discount_amount', 
            'valid_from', 'valid_to', 'usage_limit', 
            'is_first_order_only', 'is_referral_only',
            'applicable_collection', 'is_active'
        ]
        widgets = {
            'valid_from': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'valid_to': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. SUMMER50'}),
            'discount_type': forms.Select(attrs={'class': 'form-control'}),
            'discount_value': forms.NumberInput(attrs={'class': 'form-control'}),
            'min_purchase_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'max_discount_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'usage_limit': forms.NumberInput(attrs={'class': 'form-control'}),
            'applicable_collection': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean_code(self):
        code = self.cleaned_data.get('code').upper()
        if Coupon.objects.filter(code=code).exclude(id=self.instance.id).exists():
            raise forms.ValidationError("A coupon with this code already exists.")
        return code

    def clean(self):
        cleaned_data = super().clean()
        valid_from = cleaned_data.get('valid_from')
        valid_to = cleaned_data.get('valid_to')
        discount_type = cleaned_data.get('discount_type')
        discount_value = cleaned_data.get('discount_value')

        if valid_from and valid_to and valid_to <= valid_from:
            raise forms.ValidationError("End date must be after the start date.")

        if discount_type == 'percentage' and discount_value:
            if discount_value > 100 or discount_value <= 0:
                raise forms.ValidationError("Percentage discount must be between 1 and 100.")
        
        if discount_type == 'fixed' and discount_value:
            if discount_value <= 0:
                raise forms.ValidationError("Fixed discount must be greater than 0.")

        return cleaned_data
