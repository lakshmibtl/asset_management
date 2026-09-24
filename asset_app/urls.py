from django.urls import path
from django.contrib.auth import views as auth_views 
from . import views
from django.shortcuts import redirect
from django.contrib import admin
from .views import (
    create_procurement_request,
    manager_approve,
    purchase_approve,
    upload_invoice,
    payment_done
)
from asset_app.views import procurement_list

urlpatterns = [

    # Admin
    #path('admin/', admin.site.urls),

    # Login / Logout
   # path('', lambda request: redirect('login_user')),
    #path('login/', views.login_user, name='login_user'),
    #path('logout/', views.logout_user, name='logout_user'),
  
     path("dashboard/", views.dashboard, name="asset_dashboard"),

   path("create-user/", views.create_asset_user, name="create_asset_user"),

    # Change Password
    path("change-password/", views.change_password, name="change_password"),

    # Dashboard
   

    # Add User
    path('add-user/', views.add_user, name='add_user'),

    # Asset CRUD
    path('add/', views.add_asset, name='add_asset'),
    path('bulk-upload/', views.bulk_upload_assets, name='bulk_upload_assets'),
    path('download-template/', views.download_asset_template, name='download_asset_template'),
    path('<int:pk>/edit/', views.edit_asset, name='edit_asset'),
    path('warranty-tracking/', views.warranty_tracking, name='warranty_tracking'),
    path('view/', views.view_assets, name='view_assets'),
    path('assigned-employees/', views.assigned_employees, name='assigned_employees'),
    path('edit-employee/<int:emp_id>/', views.edit_employee, name='edit_employee'),
    path('delete/<int:pk>/', views.delete_asset, name='delete_asset'),
    path('view-request/<int:pk>/', views.view_request, name='view_request'),

    # PDF
    path('asset/<int:pk>/pdf/', views.asset_pdf, name='asset_pdf'),

    # QR Download
    path('download-qr/<int:pk>/', views.download_qr, name='download_qr'),

    # Assignment
    path('assign/', views.assign_asset, name='assign_asset'),
    path('assign/<int:pk>/edit/', views.edit_assignment, name='edit_assignment'),
    path('assign/<int:pk>/api/edit/', views.edit_assignment_api, name='edit_assignment_api'),
    path('return-asset/<int:pk>/', views.return_asset, name='return_asset'),
    path('request-return/<int:pk>/', views.request_return_asset, name='request_return_asset'),
    path('process-return/<int:pk>/', views.process_return, name='process_return'),
    path('return-requests/', views.return_requests, name='return_requests'),
    path('return-requests/edit/<int:pk>/', views.edit_return_request, name='edit_return_request'),
    path('return-requests/delete/<int:pk>/', views.delete_return_request, name='delete_return_request'),
    path('transfer-asset/<int:pk>/', views.transfer_asset, name='transfer_asset'),
    
    # Digital Signature
    path('sign-agreement/<int:assignment_id>/', views.sign_agreement, name='sign_agreement'),
    path('view-agreement/<int:assignment_id>/', views.view_agreement, name='view_agreement'),

    # Requests
    path('request-asset/', views.request_asset, name='request_asset'),
    path('request/<int:pk>/', views.request_detail, name='request_detail'),
    path('requests/', views.view_requests_list, name='view_requests_list'),

    # ⚠️ IMPORTANT FIX – PLACE THIS BEFORE `asset/<pk>/`
    path('asset-detail1/<int:pk>/', views.asset_detail1, name='asset_detail1'),

    # Normal Asset Detail
    path('asset/<int:pk>/', views.asset_detail, name='asset_detail'),

    # Public
    path('asset/public/<int:pk>/', views.public_asset_detail, name='public_asset_detail'),
path('update-request-status/<int:pk>/', views.update_request_status, name='update_request_status'),

    # Tickets
    path('view_tickets/', views.view_tickets, name='view_tickets'),
    path('download_ticket_report/', views.download_ticket_report, name='download_ticket_report'),
    path('raise_ticket/', views.raise_ticket, name='raise_ticket'),
    path('update_status/<int:pk>/', views.update_ticket_status, name='update_ticket_status'),
    path('ticket/<int:pk>/', views.ticket_detail, name='ticket_detail'),
    path('ticket/<int:pk>/confirm-solved/', views.ticket_confirm_solved, name='ticket_confirm_solved'),
    path('ticket/<int:pk>/reopen/', views.ticket_reopen, name='ticket_reopen'),
    path('ticket/<int:pk>/delete/', views.delete_ticket, name='delete_ticket'),

    # View Users
    path('view-users/', views.view_users, name='view_users'),
    path('delete-user/<int:pk>/', views.delete_user, name='delete_user'),
    path('edit-user/<int:pk>/', views.edit_user, name='edit_user'),



path('procurement/manager-approve/<int:pk>/', views.manager_approve, name='manager_approve'),
path('procurement/manager-reject/<int:pk>/', views.manager_reject, name='manager_reject'),

path('procurement/admin-approve/<int:pk>/', views.admin_approve, name='admin_approve'),
path('procurement/admin-reject/<int:pk>/', views.admin_reject, name='admin_reject'),
path('procurement/superadmin-approve/<int:pk>/', views.superadmin_approve, name='superadmin_approve'),
path('procurement/superadmin-reject/<int:pk>/', views.superadmin_reject, name='superadmin_reject'),

    path('procurement/', views.procurement_list, name='procurement_list'),
    path('procurement/create/', views.create_procurement_request, name='create_procurement'),
    path('procurement/delete/<int:pk>/', views.delete_procurement, name='delete_procurement'),

    path("ajax/get-employee/", views.get_employee_details, name="get_employee_details"),

    # Notifications
    path('notifications/', views.notifications, name='notifications'),
    path('notifications/mark-all-read/', views.mark_notifications_read, name='mark_notifications_read'),
    path('notifications/mark-read/<int:pk>/', views.mark_notification_read, name='mark_notification_read'),

    path('network-support-team/', views.network_support_team, name='network_support_team'),
    path('support-reports/', views.support_reports, name='support_reports'),
    path('support-reports/download/', views.download_support_report, name='download_support_report'),
    path('activity-log/', views.activity_log, name='activity_log'),
    path('submit-work-report/', views.submit_work_report, name='submit_work_report'),
    path('my-work-reports/', views.my_work_reports, name='my_work_reports'),
    path('work-reports/edit/<int:pk>/', views.edit_work_report, name='edit_work_report'),
    path('work-reports/delete/<int:pk>/', views.delete_work_report, name='delete_work_report'),
    path('my-work-reports/download/', views.download_manual_reports, name='download_manual_reports'),
]



 




