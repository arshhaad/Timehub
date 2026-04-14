from django import forms
from .models import Address
from django.contrib.auth import get_user_model
import re

User = get_user_model()

class UserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'avatar']

    def clean_first_name(self):
        first_name = self.cleaned_data.get('first_name')
        if first_name and not re.match(r'^[a-zA-Z\s]+$', first_name):
            raise forms.ValidationError("First name can only contain letters and spaces.")
        return first_name

    def clean_last_name(self):
        last_name = self.cleaned_data.get('last_name')
        if last_name and not re.match(r'^[a-zA-Z\s]+$', last_name):
            raise forms.ValidationError("Last name can only contain letters and spaces.")
        return last_name

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        if phone and not re.match(r'^[\+]?[\d\s\-\(\)]{10,15}$', phone):
            raise forms.ValidationError("Enter a valid phone number (10-15 digits).")
        return phone

class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = [
            'full_name',
            'street',
            'city',
            'state',
            'postal_code',
            'country',
            'phone',
            'is_default'
        ]

    def clean_full_name(self):
        full_name = self.cleaned_data.get('full_name')
        if full_name:
            if not re.match(r'^[a-zA-Z\s.\- \']+$', full_name):
                raise forms.ValidationError("Name can only contain letters and spaces.")
            if len(full_name) < 3:
                raise forms.ValidationError("Name must be at least 3 characters.")
        return full_name

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone and not re.match(r'^[\+]?[\d\s\-\(\)]{10,15}$', phone):
            raise forms.ValidationError("Enter a valid phone number (10-15 digits).")
        return phone

    def clean_street(self):
        street = self.cleaned_data.get('street')
        if street:
            if len(street) < 5:
                raise forms.ValidationError("Street address must be at least 5 characters.")
            if street.isdigit():
                raise forms.ValidationError("Street address cannot contain only numbers.")
        return street

    def clean_city(self):
        city = self.cleaned_data.get('city')
        if city:
            if not re.match(r'^[a-zA-Z\s]+$', city):
                raise forms.ValidationError("City name can only contain letters and spaces.")
            if len(city) < 2:
                raise forms.ValidationError("City name must be at least 2 characters.")
        return city

    def clean_state(self):
        state = self.cleaned_data.get('state')
        if state:
            if not re.match(r'^[a-zA-Z\s]+$', state):
                raise forms.ValidationError("State name can only contain letters and spaces.")
            if len(state) < 2:
                raise forms.ValidationError("State name must be at least 2 characters.")
        return state

    def clean_postal_code(self):
        postal_code = self.cleaned_data.get('postal_code')
        if postal_code:
            if not re.match(r'^[0-9A-Za-z\s\-]+$', postal_code):
                raise forms.ValidationError("Postal code can only contain digits, letters, spaces, and hyphens.")
            if len(postal_code) < 4:
                raise forms.ValidationError("Postal code must be at least 4 characters.")
        return postal_code