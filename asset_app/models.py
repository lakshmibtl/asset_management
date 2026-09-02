from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
import qrcode
import base64
from io import BytesIO
from django.urls import reverse
from django.contrib.auth.models import User  # ✅ Add this line

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
       
    ]

    asset_id = models.CharField(max_length=20, unique=True, blank=True)
    asset_type = models.CharField(max_length=50, default='Laptop')
    name = models.CharField(max_length=100)
    company_name = models.CharField(max_length=100, blank=True)
    series_number = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=50, choices=ASSET_STATUS, default='Available')
    
    image = models.ImageField(upload_to='assets/', blank=True, null=True)
    qr_code_base64 = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    purchase_date = models.DateField(blank=True, null=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    warranty = models.CharField(max_length=100, blank=True, null=True)


 

    def __str__(self):
        return f"{self.asset_type} - {self.asset_id}"

    def save(self, *args, **kwargs):
        # Auto-generate unique asset_id
        if not self.asset_id:
            prefix_map = {'Laptop': 'LP', 'Desktop': 'DT', 'Printer': 'PR'}
            last_asset = Asset.objects.filter(asset_type=self.asset_type).order_by('-id').first()
            next_number = 1
            if last_asset and last_asset.asset_id:
                try:
                    last_num = int(last_asset.asset_id.split('-')[-1])
                    next_number = last_num + 1
                except:
                    pass
            self.asset_id = f"{prefix_map.get(self.asset_type, 'AS')}-{next_number:04d}"

        super().save(*args, **kwargs)

        # Generate QR code for public view
        qr_url = reverse('public_asset_detail', args=[self.id])
        qr_full_url = f"http://172.21.7.102:8000{qr_url}"

        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(qr_full_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        qr_code_data = base64.b64encode(buffer.getvalue()).decode()

        Asset.objects.filter(pk=self.pk).update(qr_code_base64=qr_code_data)

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
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]

    asset_category = models.CharField(max_length=50, default='Laptop')
    asset_type = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(default=1)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    requested_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True)
    required_date = models.DateField(null=True, blank=True)
    



class Ticket(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='tickets')
    subject = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=50, default='pending')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

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
from django.utils import timezone

class ProcurementRequestWorkflow(models.Model):

    STATUS = [
        ('Pending Manager Approval', 'Pending Manager Approval'),
        ('Rejected by Manager', 'Rejected by Manager'),

        ('Pending Purchase Approval', 'Pending Purchase Approval'),
        ('Rejected by Purchase Manager', 'Rejected by Purchase Manager'),

        ('Invoice Pending', 'Invoice Pending'),

        ('Payment Pending', 'Payment Pending'),
        ('Rejected by Accounts Manager', 'Rejected by Accounts Manager'),

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

    def __str__(self):
        return self.name
    


# --------------------------------------------------------------------
# Assignment Model
# --------------------------------------------------------------------
class Assignment(models.Model):
    STATUS_CHOICES = [
        ('In Use', 'In Use'),
        ('Returned', 'Returned'),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default='In Use'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    
    # Digital Signature Fields
    signature = models.TextField(blank=True, null=True)
    is_signed = models.BooleanField(default=False)
    agreement_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.employee.name} - {self.asset.asset_id}"

