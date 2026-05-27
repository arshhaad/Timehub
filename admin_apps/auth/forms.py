from django import forms
from user_apps.accounts.models import CustomUser

class AdminProfileForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['email', 'first_name', 'last_name', 'phone_number', 'avatar']
        widgets = {
            'email': forms.EmailInput(attrs={'placeholder': 'Email Address', 'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'First Name', 'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Last Name', 'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'placeholder': 'Phone Number', 'class': 'form-control'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if CustomUser.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This email address is already in use.")
        return email

    def clean_first_name(self):
        name = self.cleaned_data.get('first_name')
        if name and not name.isalpha():
            raise forms.ValidationError("First name should only contain letters.")
        return name

    def clean_last_name(self):
        name = self.cleaned_data.get('last_name')
        if name and not name.isalpha():
            raise forms.ValidationError("Last name should only contain letters.")
        return name

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        if phone:
            phone = phone.replace(' ', '').replace('-', '')
            if not phone.isdigit() and not (phone.startswith('+') and phone[1:].isdigit()):
                raise forms.ValidationError("Phone number must contain only digits and an optional '+' prefix.")
            if len(phone) < 10 or len(phone) > 13:
                raise forms.ValidationError("Phone number must be between 10 and 13 characters.")
        return phone

class AdminLoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'placeholder': 'Enter admin email',
            'class': 'form-control',
            'autocomplete': 'email',
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'placeholder': '••••••••',
            'class': 'form-control',
            'autocomplete': 'current-password',
        })
    )
