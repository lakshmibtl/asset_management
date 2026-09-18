from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
import qrcode
import base64
import socket
from io import BytesIO
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone

# --------------------------------------------------------------------
# Custom User Model
# --------------------------------------------------------------------
# models.py

#ROLE_CHOICES = [
 #    ("admin", "Admin"),
   # ("manager", "Manager"),
    #("purchase", "Purchase Manager"),
    #("accounts", "Account Manager"),
    #("user", "User"),
#]

#class CustomUser(AbstractUser):
 #   role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="user")


  #  def __str__(self):
   #     return f"{self.username} ({self.role})"
# --------------------------------------------------------------------
# Asset Model
# --------------------------------------------------------------------
class Asset(models.Model):
    ASSET_TYPES = [
        ('Laptop', 'Laptop'),
        ('Desktop', 'Desktop'),
        ('Printer', 'Printer'),
        ('IPPBX', 'IPPBX'),
        ('Mouse', 'Mouse'),
        ('Other', 'Other'),
    ]

    ASSET_STATUS = [
        ('Available', 'Available'),
        ('In Use', 'In Use'),
        ('Other', 'Other'),
    ]

    RAM_CHOICES = [
        ('4GB', '4GB'),
        ('8GB', '8GB'),
        ('12GB', '12GB'),
        ('16GB', '16GB'),
        ('32GB', '32GB'),
        ('64GB', '64GB'),
        ('Other', 'Other'),
    ]

    STORAGE_CHOICES = [
        ('128GB', '128GB'),
        ('256GB', '256GB'),
        ('512GB', '512GB'),
        ('1TB', '1TB'),
        ('2TB', '2TB'),
        ('Other', 'Other'),
    ]

    WARRANTY_CHOICES = [
        ('1', '1 Year'),
        ('2', '2 Years'),
        ('3', '3 Years'),
        ('Other', 'Other'),
    ]

    asset_id = models.CharField(max_length=20, unique=True, blank=True)
    asset_type = models.CharField(max_length=50, default='Laptop')
    name = models.CharField(max_length=100, blank=True, default='')
    company_name = models.CharField(max_length=100, blank=True)
    series_number = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=50, choices=ASSET_STATUS, default='Available')

    ram = models.CharField(max_length=50, choices=RAM_CHOICES, blank=True, null=True)
    storage = models.CharField(max_length=50, choices=STORAGE_CHOICES, blank=True, null=True)

    image = models.ImageField(upload_to='assets/', blank=True, null=True)
    qr_code_base64 = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    purchase_date = models.DateField(blank=True, null=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    warranty = models.CharField(max_length=10, choices=WARRANTY_CHOICES, blank=True, null=True)
    warranty_end_date = models.DateField(blank=True, null=True)


 

    def __str__(self):
        return f"{self.asset_type} - {self.asset_id}"

    @property
    def warranty_label(self):
        return dict(self.WARRANTY_CHOICES).get(self.warranty, self.warranty or "-")

    @property
    def days_until_warranty_end(self):
        if not self.warranty_end_date:
            return None
        return (self.warranty_end_date - timezone.localdate()).days

    @property
    def warranty_status(self):
        if not self.warranty_end_date:
            return 'No Warranty'
        days = self.days_until_warranty_end
        if days < 0:
            return 'Expired'
        if days <= 30:
            return 'Expiring Soon'
        return 'Active'

    def save(self, *args, **kwargs):
        # Auto-generate unique asset_id
        if not self.asset_id:
            prefix_map = {'Laptop': 'LP', 'Desktop': 'DT', 'Printer': 'PR'}
            prefix = prefix_map.get(self.asset_type, 'AS')
            used = set(
                Asset.objects.filter(asset_id__startswith=f"{prefix}-")
                .values_list('asset_id', flat=True)
            )
            next_number = 1
            while f"{prefix}-{next_number:04d}" in used:
                next_number += 1
            self.asset_id = f"{prefix}-{next_number:04d}"

        # Auto-calculate warranty end date = add/purchase date + warranty years/months/days
        import re
        from datetime import timedelta
        
        years, months, days = 0, 0, 0
        try:
            years = int(self.warranty) if self.warranty else 0
        except (TypeError, ValueError):
            if self.warranty:
                match = re.match(r'^(\d+)\s*(year|month|day)s?', self.warranty.lower().strip())
                if match:
                    num = int(match.group(1))
                    unit = match.group(2)
                    if unit == 'year': years = num
                    elif unit == 'month': months = num
                    elif unit == 'day': days = num

        if years > 0 or months > 0 or days > 0:
            base_date = self.purchase_date or timezone.localdate()
            if years > 0:
                try:
                    base_date = base_date.replace(year=base_date.year + years)
                except ValueError:  # Feb 29 in a non-leap target year -> leap to Feb 28
                    base_date = base_date.replace(year=base_date.year + years, day=28)
            
            if months > 0:
                new_month = base_date.month + months
                add_years = (new_month - 1) // 12
                new_month = (new_month - 1) % 12 + 1
                try:
                    base_date = base_date.replace(year=base_date.year + add_years, month=new_month)
                except ValueError:
                    # E.g. Jan 31 + 1 month -> Feb 31 (ValueError) -> Feb 28
                    base_date = base_date.replace(year=base_date.year + add_years, month=new_month, day=28)
                    
            if days > 0:
                base_date = base_date + timedelta(days=days)
                
            self.warranty_end_date = base_date
        else:
            self.warranty_end_date = None

        super().save(*args, **kwargs)

        # Generate QR code for public view
        from django.conf import settings
        qr_url = reverse('public_asset_detail', args=[self.id])
        base_url = getattr(settings, 'SITE_BASE_URL', None)
        if not base_url:
            base_url = f"http://{socket.gethostname()}:8000"
        qr_full_url = f"{base_url}{qr_url}"

        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(qr_full_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        qr_code_data = base64.b64encode(buffer.getvalue()).decode()

        Asset.objects.filter(pk=self.pk).update(qr_code_base64=qr_code_data)

# --------------------------------------------------------------------
# Asset History Model
# --------------------------------------------------------------------
class AssetHistory(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='edit_history')
    edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    edited_at = models.DateTimeField(auto_now_add=True)
    changes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.asset.asset_id} edited by {self.edited_by.username if self.edited_by else 'Unknown'} on {self.edited_at}"

# --------------------------------------------------------------------
# Asset Request Model
# --------------------------------------------------------------------
class AssetRequest(models.Model):
    ASSET_TYPES = [
        ('Laptop', 'Laptop'),
        ('Desktop', 'Desktop'),
        ('Printer', 'Printer'),
        ('IPPBX', 'IPPBX'),
        ('Mouse', 'Mouse'),
        ('Other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('Pending_Manager', 'Pending Manager Approval'),
        ('Pending_Admin', 'Pending Admin Approval'),
        ('Pending_SuperAdmin', 'Pending Super Admin Approval'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]

    asset_category = models.CharField(max_length=50, default='Laptop')
    asset_type = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(default=1)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending_Manager')
    requested_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True)
    required_date = models.DateField(null=True, blank=True)
    



class Ticket(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='tickets')
    department = models.CharField(max_length=100, default='Network')
    subject = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=50, default='pending')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    feedback = models.TextField(blank=True, null=True)
    resolution_message = models.TextField(blank=True, null=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tickets')

    def __str__(self):
        return f"{self.subject} - {self.status}"




# --------------------------------------------------------------------
# Procurement Request Model (Required for Procurement Workflow)
from django.conf import settings
from django.db import models

# --------------------------------------------------------------------
# MODEL 1 (Requirement → Vendor → Asset Added)
# --------------------------------------------------------------------
class ProcurementRequestInitial(models.Model):
    STATUS = [
        ('Requirement Raised', 'Requirement Raised'),
        ('Purchase Approved', 'Purchase Approved'),
        ('Vendor Selected', 'Vendor Selected'),
        ('Asset Received', 'Asset Received'),
        ('Asset Added', 'Asset Added'),
    ]

    ASSET_TYPES = [
        ('Laptop', 'Laptop'),
        ('Desktop', 'Desktop'),
        ('Server', 'Server'),
        ('Software License', 'Software License'),
        ('Peripheral', 'Peripheral'),
    ]

    asset_type = models.CharField(max_length=50, choices=ASSET_TYPES)
    description = models.TextField(blank=True, null=True)

    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    status = models.CharField(max_length=50, choices=STATUS, default="Requirement Raised")

    vendor_name = models.CharField(max_length=100, blank=True, null=True)
    purchase_order_number = models.CharField(max_length=100, blank=True, null=True)
    invoice_number = models.CharField(max_length=100, blank=True, null=True)

    warranty_period = models.CharField(max_length=50, blank=True, null=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.asset_type} - {self.requested_by}"


# --------------------------------------------------------------------
# MODEL 2 (Manager → Purchase → Invoice → Payment)
# --------------------------------------------------------------------
# --------------------------------------------------------------------
# MODEL 2 (Manager → Purchase → Invoice → Payment)
# --------------------------------------------------------------------
class ProcurementRequestWorkflow(models.Model):

    STATUS = [
        ('Pending Manager Approval', 'Pending Manager Approval'),
        ('Rejected by Manager', 'Rejected by Manager'),

        ('Pending Admin Approval', 'Pending Admin Approval'),
        ('Rejected by Admin', 'Rejected by Admin'),

        ('Pending Super Admin Approval', 'Pending Super Admin Approval'),
        ('Rejected by Super Admin', 'Rejected by Super Admin'),

        ('Completed', 'Completed'),
    ]

    asset_type = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    # Workflow state
    status = models.CharField(max_length=50, choices=STATUS, default="Pending Manager Approval")
    payment_status = models.CharField(max_length=50, default="Unpaid")

    # Purchase Team Fields
    vendor_name = models.CharField(max_length=100, blank=True, null=True)
    purchase_order = models.CharField(max_length=100, blank=True, null=True)

    # Multiple Invoices
    invoice_file1 = models.FileField(upload_to="invoices/", blank=True, null=True)
    invoice_file2 = models.FileField(upload_to="invoices/", blank=True, null=True)
    invoice_file3 = models.FileField(upload_to="invoices/", blank=True, null=True)

    # NEW FIELDS
    request_date = models.DateTimeField(auto_now_add=True)  # Automatically set
    completed_date = models.DateTimeField(null=True, blank=True)  # Filled when completed

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.asset_type} - {self.status}"

    # Auto-set completed_date when marked Completed
    def save(self, *args, **kwargs):
        if self.status == "Completed" and self.completed_date is None:
            self.completed_date = timezone.now()

        super().save(*args, **kwargs)

# --------------------------------------------------------------------
# MODEL 3 (Simple procurement)
# --------------------------------------------------------------------
class ProcurementRequest1(models.Model):
    asset_type = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    invoice_file = models.FileField(upload_to="invoices/", null=True, blank=True)

    status = models.CharField(max_length=50, default="Manager Approval Pending")
    payment_status = models.CharField(max_length=20, default="Unpaid")

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.asset_type} - {self.status}"



class Employee(models.Model):
    employee_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    department = models.CharField(max_length=100)
    branch = models.CharField(max_length=100, blank=True, null=True)
    email = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.name
    


# --------------------------------------------------------------------
# Assignment Model
# --------------------------------------------------------------------
class Assignment(models.Model):
    STATUS_CHOICES = [
        ('In Use', 'In Use'),
        ('Returned', 'Returned'),
        ('Temporary', 'Temporary Use'),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default='In Use'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_date = models.DateField(blank=True, null=True)
    
    # Digital Signature Fields
    signature = models.TextField(blank=True, null=True)
    is_signed = models.BooleanField(default=False)
    agreement_date = models.DateTimeField(null=True, blank=True)

    # Return Fields
    return_reason = models.TextField(blank=True, null=True)
    returned_at = models.DateTimeField(null=True, blank=True)

    # Tracking
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='assignments_made', null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"{self.employee.name} - {self.asset.asset_id}"


class ReturnRequest(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending Manager Approval'),
        ('Manager_Approved', 'Pending Admin Approval'),
        ('Admin_Approved', 'Pending Super Admin Approval'),
        ('Accepted', 'Accepted'),
        ('Rejected', 'Rejected'),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE)
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    reason = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    processed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Return {self.asset.asset_id} by {self.employee.name} ({self.status})"


# --------------------------------------------------------------------
# Notification Model
# --------------------------------------------------------------------
class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('asset_request', 'Asset Request'),
        ('ticket', 'Ticket'),
        ('procurement', 'Procurement Request'),
        ('return_request', 'Return Request'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications'
    )
    notification_type = models.CharField(
        max_length=50, choices=NOTIFICATION_TYPES, default='asset_request'
    )
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recipient} - {self.title}"
