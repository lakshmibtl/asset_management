from django.contrib import admin
from .models import Asset, Assignment, AssetRequest, Ticket


# ---- Asset Admin ----
@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ('asset_id', 'asset_type', 'name', 'company_name', 'status')
    search_fields = ('asset_id', 'name', 'company_name')
    list_filter = ('asset_type', 'status')


# ---- Assignment Admin ----
@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = (
        'asset',
        'get_employee_name',
        'get_employee_department',
        'status',
        'assigned_at',
    )

    list_filter = (
        'status',
        'employee__department',
    )

    search_fields = (
        'employee__name',
        'employee__employee_id',
        'asset__asset_id',
    )

    def get_employee_name(self, obj):
        return obj.employee.name
    get_employee_name.short_description = "Employee Name"

    def get_employee_department(self, obj):
        return obj.employee.department
    get_employee_department.short_description = "Department"


# ---- Asset Request Admin ----
@admin.register(AssetRequest)
class AssetRequestAdmin(admin.ModelAdmin):
    list_display = ('asset_type', 'requested_by', 'status', 'requested_at')
    list_filter = ('status', 'asset_type')
    search_fields = ('requested_by__username',)


# ---- Ticket Admin ----
@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('asset', 'subject', 'status', 'created_by', 'created_at')
    list_filter = ('status',)
    search_fields = ('subject', 'created_by__username')
