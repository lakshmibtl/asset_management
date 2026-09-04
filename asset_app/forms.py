from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model

from .models import (
    Asset,
    Assignment,
    AssetRequest,
    Ticket,
    ProcurementRequestInitial,
    ProcurementRequest1,
    ProcurementRequestWorkflow,
)

# Load correct CustomUser from asset_management
CustomUser = get_user_model()


# ---------------------------------------------------------
# 🔹 Login Form
# ---------------------------------------------------------
class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter Username'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter Password'
        })
    )


# ---------------------------------------------------------
# 🔹 Asset Form
# ---------------------------------------------------------
# forms.py
from django import forms
from .models import Asset


class AssetForm(forms.ModelForm):

    asset_type = forms.ChoiceField(
        choices=Asset.ASSET_TYPES,
        required=True,   # ✅ server-side required
        widget=forms.Select(attrs={
            'class': 'form-select form-select-lg rounded-3 shadow-sm',
            'required': 'required'  # ✅ browser validation
        })
    )

    other_asset_type = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg rounded-3 shadow-sm mt-2',
            'placeholder': 'Enter custom asset type...',
            'style': 'display: none;',
            'id': 'otherAssetTypeInput'
        })
    )

    status = forms.ChoiceField(
        choices=Asset.ASSET_STATUS,
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-select form-select-lg rounded-3 shadow-sm',
            'required': 'required'
        })
    )

    class Meta:
        model = Asset
        fields = ['asset_type', 'other_asset_type', 'company_name', 'series_number', 'model', 'status', 'purchase_date', 'cost', 'warranty', 'image']

        widgets = {
            'company_name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'placeholder': 'Enter Company Name',
                'required': 'required'   # ✅ browser validation
            }),
            'series_number': forms.TextInput(attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'placeholder': 'Enter Series Number',
                'required': 'required'
            }),
            'model': forms.TextInput(attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'placeholder': 'Enter Model',
                'required': 'required'
            }),
            'purchase_date': forms.DateInput(attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'type': 'date'
            }),
            'cost': forms.NumberInput(attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'placeholder': 'Enter Cost'
            }),
            'warranty': forms.TextInput(attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'placeholder': 'Enter Warranty'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ✅ DOUBLE SAFETY: server-side required
        self.fields['company_name'].required = True
        self.fields['series_number'].required = True
        self.fields['model'].required = True

    def clean(self):
        cleaned_data = super().clean()
        asset_type = cleaned_data.get('asset_type')
        other = cleaned_data.get('other_asset_type')
        
        if asset_type == 'Other':
            if not other:
                self.add_error('other_asset_type', 'Please specify the asset type.')
            else:
                cleaned_data['asset_type'] = other
        
        return cleaned_data



# asset_app/forms.py
from django import forms
from .models import Assignment, AssetRequest


# ---------------------------------------------------------
# 🔹 Assignment Form  ✅ MUST BE EXACT NAME
# ---------------------------------------------------------
class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ['asset', 'employee', 'status']
        widgets = {
            'asset': forms.Select(attrs={
                'class': 'form-select form-select-lg custom-input'
            }),
            'employee': forms.Select(attrs={
                'class': 'form-select form-select-lg custom-input'
            }),
            'status': forms.Select(attrs={
                'class': 'form-select form-select-lg custom-input'
            }),
        }



# ---------------------------------------------------------
# 🔹 Asset Request Form
# ---------------------------------------------------------
ASSET_CHOICES = [
    ('Laptop', 'Laptop'),
    ('Desktop', 'Desktop'),
    ('Printer', 'Printer'),
]

class AssetRequestForm(forms.ModelForm):
    asset_category = forms.ChoiceField(
        choices=AssetRequest.ASSET_TYPES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    other_asset_category = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control mt-2',
            'placeholder': 'Enter custom category...',
            'style': 'display: none;',
            'id': 'otherAssetCategoryInput'
        })
    )

    class Meta:
        model = AssetRequest
        fields = ['asset_category', 'other_asset_category', 'asset_type', 'quantity', 'reason', 'required_date']
        widgets = {
            'asset_type': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Dell Laptop'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1'
            }),
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Reason for request'
            }),
            'required_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        asset_category = cleaned_data.get('asset_category')
        other = cleaned_data.get('other_asset_category')
        
        if asset_category == 'Other':
            if not other:
                self.add_error('other_asset_category', 'Please specify the custom category.')
            else:
                cleaned_data['asset_category'] = other
        
        return cleaned_data


# ---------------------------------------------------------
# 🔹 Add User Form (CustomUser)
# ---------------------------------------------------------
class AddUserForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'role']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = "Username / Emp ID"

    def save(self, commit=True):
        user = super().save(commit=False)

        # Auto assign staff access to admin-level roles
        if user.role in ["superadmin", "asset_admin", "stationery_admin"]:
            user.is_staff = True
        else:
            user.is_staff = False

        if commit:
            user.save()
        return user


# ---------------------------------------------------------
# 🔹 Ticket Form
# ---------------------------------------------------------
class TicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ['asset', 'subject', 'description']
        widgets = {
            'asset': forms.Select(attrs={'class': 'form-select'}),
            'subject': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter subject'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Describe your issue',
                'rows': 3
            }),
        }


# ---------------------------------------------------------
# 🔹 Update Request Form
# ---------------------------------------------------------
class UpdateRequestForm(forms.ModelForm):
    class Meta:
        model = AssetRequest
        fields = ['status']
