from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser


class SignupForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'placeholder': 'Email address',
            'autocomplete': 'email',
        }),
    )
    first_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'placeholder': 'First name',
        }),
    )
    last_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Last name (optional)',
        }),
    )
    phone_number = forms.CharField(
        max_length=13,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Phone number (optional)',
        }),
    )
    entered_referral_code = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Referral code (optional)',
        }),
    )

    class Meta:
        model = CustomUser
        fields = ('email', 'first_name', 'last_name', 'phone_number', 'entered_referral_code')

    def clean_email(self):
        email = self.cleaned_data.get('email').lower()
        if CustomUser.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered.")
        return email

    def clean_first_name(self):
        first_name = self.cleaned_data.get('first_name')
        if not first_name.strip():
            raise forms.ValidationError("First name is required.")
        if not first_name.isalpha():
            raise forms.ValidationError("First name should only contain letters.")
        return first_name

    def clean_last_name(self):
        last_name = self.cleaned_data.get('last_name')
        if last_name and not last_name.isalpha():
            raise forms.ValidationError("Last name should only contain letters.")
        return last_name

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        if phone:
            phone = phone.replace(' ', '').replace('-', '')
            if not phone.isdigit() and not (phone.startswith('+') and phone[1:].isdigit()):
                raise forms.ValidationError("Phone number must contain only digits and an optional '+' prefix.")
            if len(phone) < 10 or len(phone) > 13:
                raise forms.ValidationError("Phone number must be between 10 and 13 characters.")
        return phone


class LoginForm(forms.Form):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'placeholder': 'name@example.com',
            'autocomplete': 'email',
        }),
    )
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={
            'placeholder': '••••••••',
            'autocomplete': 'current-password',
        }),
    )


# Forgot Password Form
class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'placeholder': 'Enter your email'
        })
    )


# Reset Password
class ResetPasswordForm(forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'placeholder': 'New Password'
        })
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Confirm Password'
        })
    )


COUNTRY_CHOICES = [
    ('+91', '🇮🇳 India (+91)'),
    ('+1', '🇺🇸 USA / Canada (+1)'),
    ('+44', '🇬🇧 UK (+44)'),
    ('+971', '🇦🇪 UAE (+971)'),
    ('+966', '🇸🇦 Saudi Arabia (+966)'),
    ('+61', '🇦🇺 Australia (+61)'),
    ('+65', '🇸🇬 Singapore (+65)'),
    ('+49', '🇩🇪 Germany (+49)'),
    ('+33', '🇫🇷 France (+33)'),
    ('+974', '🇶🇦 Qatar (+974)'),
    ('+965', '🇰🇼 Kuwait (+965)'),
    ('+968', '🇴🇲 Oman (+968)'),
    ('+973', '🇧🇭 Bahrain (+973)'),
    ('+977', '🇳🇵 Nepal (+977)'),
    ('+880', '🇧🇩 Bangladesh (+880)'),
    ('+94', '🇱🇰 Sri Lanka (+94)'),
    ('+92', '🇵🇰 Pakistan (+92)'),
]

class PhoneLoginForm(forms.Form):
    country_code = forms.ChoiceField(
        choices=COUNTRY_CHOICES,
        initial='+91',
        widget=forms.Select(attrs={
            'class': 'country-code-select',
            'id': 'id_country_code',
        })
    )
    phone_number = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            'placeholder': '9876543210',
            'autocomplete': 'tel-national',
            'class': 'phone-number-input',
            'id': 'id_phone_number',
        }),
    )

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number', '').strip()
        if phone:
            phone_clean = phone.replace(' ', '').replace('-', '').lstrip('0')
            if not phone_clean.isdigit() and not (phone_clean.startswith('+') and phone_clean[1:].isdigit()):
                raise forms.ValidationError("Phone number must contain only digits.")
            if len(phone_clean) < 7 or len(phone_clean) > 13:
                raise forms.ValidationError("Please enter a valid phone number (7 to 13 digits).")
            return phone_clean
        raise forms.ValidationError("Phone number is required.")

    def get_full_phone_number(self):
        country_code = self.cleaned_data.get('country_code', '+91')
        phone_number = self.cleaned_data.get('phone_number', '')
        if phone_number.startswith('+'):
            return phone_number
        return f"{country_code}{phone_number}"
