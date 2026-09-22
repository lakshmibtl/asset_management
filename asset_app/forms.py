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

    other_status = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg rounded-3 shadow-sm mt-2',
            'placeholder': 'Enter custom status...',
            'style': 'display: none;',
            'id': 'otherStatusInput'
        })
    )

    ram = forms.ChoiceField(
        choices=Asset.RAM_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select form-select-lg rounded-3 shadow-sm',
            'id': 'id_ram'
        })
    )

    other_ram = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg rounded-3 shadow-sm mt-2',
            'placeholder': 'Enter custom RAM...',
            'style': 'display: none;',
            'id': 'otherRamInput'
        })
    )

    storage = forms.ChoiceField(
        choices=Asset.STORAGE_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select form-select-lg rounded-3 shadow-sm',
            'id': 'id_storage'
        })
    )

    other_storage = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg rounded-3 shadow-sm mt-2',
            'placeholder': 'Enter custom storage...',
            'style': 'display: none;',
            'id': 'otherStorageInput'
        })
    )

    warranty = forms.ChoiceField(
        choices=Asset.WARRANTY_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select form-select-lg rounded-3 shadow-sm'
        })
    )

    other_warranty = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg rounded-3 shadow-sm mt-2',
            'placeholder': 'Enter custom warranty...',
            'style': 'display: none;',
            'id': 'otherWarrantyInput'
        })
    )

    purchase_date = forms.DateField(
        required=False,
        input_formats=['%d/%m/%Y'],
        widget=forms.DateInput(
            attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'placeholder': 'DD/MM/YYYY',
            },
            format='%d/%m/%Y',
        ),
    )

    warranty_end_date = forms.DateField(
        required=False,
        input_formats=['%d/%m/%Y'],
        widget=forms.DateInput(
            attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'placeholder': 'DD/MM/YYYY',
            },
            format='%d/%m/%Y',
        ),
    )

    class Meta:
        model = Asset
        fields = ['asset_type', 'model', 'series_number', 'vendor_name', 'company_name', 'status', 'ram', 'storage', 'purchase_date', 'cost', 'warranty', 'warranty_end_date', 'image']

        widgets = {
            'model': forms.TextInput(attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'placeholder': 'Enter Model Name',
                'required': 'required'
            }),
            'series_number': forms.TextInput(attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'placeholder': 'Enter Serial / Series Number',
                'required': 'required'
            }),
            'vendor_name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'placeholder': 'Enter Vendor Name',
            }),
            'company_name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'placeholder': 'Enter Company Name',
                'required': 'required'   # ✅ browser validation
            }),
            'cost': forms.NumberInput(attrs={
                'class': 'form-control form-control-lg rounded-3 shadow-sm',
                'placeholder': 'Enter Cost',
                'required': 'required'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ✅ DOUBLE SAFETY: server-side required
        self.fields['company_name'].required = True
        self.fields['series_number'].required = True
        self.fields['model'].required = True
        self.fields['cost'].required = True

        # Handle custom asset type on Edit
        if self.instance and self.instance.pk:
            valid_types = [choice[0] for choice in Asset.ASSET_TYPES]
            if self.instance.asset_type and self.instance.asset_type not in valid_types:
                # Add the custom type to choices dynamically so it can render, or just set it to 'Other'
                self.initial['other_asset_type'] = self.instance.asset_type
                self.initial['asset_type'] = 'Other'
                
        # Handle custom status on Edit
        if self.instance and self.instance.pk:
            valid_statuses = [choice[0] for choice in Asset.ASSET_STATUS]
            if self.instance.status and self.instance.status not in valid_statuses:
                self.initial['other_status'] = self.instance.status
                self.initial['status'] = 'Other'
                
        # Handle custom warranty on Edit
        if self.instance and self.instance.pk:
            valid_warranties = [choice[0] for choice in Asset.WARRANTY_CHOICES]
            if self.instance.warranty and self.instance.warranty not in valid_warranties:
                self.initial['other_warranty'] = self.instance.warranty
                self.initial['warranty'] = 'Other'

        # Handle custom RAM on Edit
        if self.instance and self.instance.pk:
            valid_rams = [choice[0] for choice in Asset.RAM_CHOICES]
            if self.instance.ram and self.instance.ram not in valid_rams:
                self.initial['other_ram'] = self.instance.ram
                self.initial['ram'] = 'Other'
                
        # Handle custom storage on Edit
        if self.instance and self.instance.pk:
            valid_storages = [choice[0] for choice in Asset.STORAGE_CHOICES]
            if self.instance.storage and self.instance.storage not in valid_storages:
                self.initial['other_storage'] = self.instance.storage
                self.initial['storage'] = 'Other'

    def clean_series_number(self):
        series_number = self.cleaned_data.get('series_number', '').strip()
        if series_number:
            qs = Asset.objects.filter(series_number__iexact=series_number)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)  # Allow editing same asset
            if qs.exists():
                existing = qs.first()
                raise forms.ValidationError(
                    f'Serial number "{series_number}" is already used by asset {existing.asset_id} ({existing.asset_type}). Please enter a unique serial number.'
                )
        return series_number

    def clean(self):
        cleaned_data = super().clean()
        asset_type = cleaned_data.get('asset_type')
        other = cleaned_data.get('other_asset_type')
        
        if asset_type == 'Other':
            if not other:
                self.add_error('other_asset_type', 'Please specify the asset type.')
            else:
                # Store the custom type directly in asset_type so it shows up in dashboard stats
                cleaned_data['asset_type'] = other.strip()
                
        status = cleaned_data.get('status')
        other_status = cleaned_data.get('other_status')
        
        if status == 'Other':
            if not other_status:
                self.add_error('other_status', 'Please specify the custom status.')
            else:
                cleaned_data['status'] = other_status.strip()
                
        warranty = cleaned_data.get('warranty')
        other_warranty = cleaned_data.get('other_warranty')
        
        if warranty == 'Other':
            if not other_warranty:
                self.add_error('other_warranty', 'Please specify the custom warranty.')
            else:
                cleaned_data['warranty'] = other_warranty.strip()

        warranty_end_raw = self.data.get('warranty_end_date', '').strip()
        if warranty == 'Complete' or (cleaned_data.get('warranty') and str(cleaned_data.get('warranty')).lower() in ['complete', 'complete warranty']) or warranty_end_raw.lower() in ['complete', 'complete warranty']:
            cleaned_data['warranty_end_date'] = None
            if 'warranty_end_date' in self._errors:
                del self._errors['warranty_end_date']

        ram = cleaned_data.get('ram')
        other_ram = cleaned_data.get('other_ram')
        
        if ram == 'Other':
            if not other_ram:
                self.add_error('other_ram', 'Please specify the custom RAM.')
            else:
                cleaned_data['ram'] = other_ram.strip()
                
        storage = cleaned_data.get('storage')
        other_storage = cleaned_data.get('other_storage')
        
        if storage == 'Other':
            if not other_storage:
                self.add_error('other_storage', 'Please specify the custom storage.')
            else:
                cleaned_data['storage'] = other_storage.strip()
        
        return cleaned_data



# asset_app/forms.py
from django import forms
from .models import Assignment, AssetRequest


# ---------------------------------------------------------
# 🔹 Assignment Form  ✅ MUST BE EXACT NAME
# ---------------------------------------------------------
class AssignmentForm(forms.ModelForm):
    assigned_date = forms.DateField(
        required=False,
        input_formats=['%d/%m/%Y', '%Y-%m-%d'],
        widget=forms.DateInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'DD/MM/YYYY',
            },
            format='%d/%m/%Y',
        ),
    )

    class Meta:
        model = Assignment
        fields = ['asset', 'employee', 'status', 'assigned_date']
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
    asset_category = forms.CharField(
        required=False,
        widget=forms.Select(choices=AssetRequest.ASSET_TYPES, attrs={'class': 'form-select'})
    )

    required_date = forms.DateField(
        required=False,
        input_formats=['%d/%m/%Y'],
        widget=forms.DateInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'DD/MM/YYYY',
            },
            format='%d/%m/%Y',
        ),
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

        # Always store a meaningful category (which may be a free-form custom type)
        if not cleaned_data.get('asset_category'):
            raw = self.data.get('asset_category', '').strip()
            if raw:
                cleaned_data['asset_category'] = raw
            else:
                self.add_error('asset_category', 'Please select a category.')

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
        fields = ['asset', 'department', 'subject', 'description']
        widgets = {
            'asset': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Employee
        from django.contrib.auth import get_user_model
        from django.db.models import Q
        User = get_user_model()
        
        choices = [
            ('Network', 'Network'),
        ]
            
        self.fields['department'].widget.choices = choices
        self.fields['department'].choices = choices


# ---------------------------------------------------------
# 🔹 Update Request Form
# ---------------------------------------------------------
class UpdateRequestForm(forms.ModelForm):
    class Meta:
        model = AssetRequest
        fields = ['status']
