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

    # Dashboard
   

    # Add User
    path('add-user/', views.add_user, name='add_user'),

    # Asset CRUD
    path('add/', views.add_asset, name='add_asset'),
    path('view/', views.view_assets, name='view_assets'),
    path('assigned-employees/', views.assigned_employees, name='assigned_employees'),
    path('delete/<int:pk>/', views.delete_asset, name='delete_asset'),
    path('view-request/<int:pk>/', views.view_request, name='view_request'),

    # PDF
    path('asset/<int:pk>/pdf/', views.asset_pdf, name='asset_pdf'),

    # QR Download
    path('download-qr/<int:pk>/', views.download_qr, name='download_qr'),

    # Assignment
    path('assign/', views.assign_asset, name='assign_asset'),
    path('return-asset/<int:pk>/', views.return_asset, name='return_asset'),
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
    path('raise_ticket/', views.raise_ticket, name='raise_ticket'),
    path('view_tickets/', views.view_tickets, name='view_tickets'),
    path('update_status/<int:pk>/', views.update_ticket_status, name='update_ticket_status'),
    path('ticket/<int:pk>/', views.ticket_detail, name='ticket_detail'),

    # View Users
    path('view-users/', views.view_users, name='view_users'),



path('procurement/manager-approve/<int:pk>/', views.manager_approve, name='manager_approve'),
path('procurement/manager-reject/<int:pk>/', views.manager_reject, name='manager_reject'),

path('procurement/purchase-approve/<int:pk>/', views.purchase_approve, name='purchase_approve'),
path('procurement/purchase-reject/<int:pk>/', views.purchase_reject, name='purchase_reject'),

path('procurement/accounts-approve/<int:pk>/', views.accounts_approve, name='accounts_approve'),
path('procurement/accounts-reject/<int:pk>/', views.accounts_reject, name='accounts_reject'),

path('procurement/upload-invoice/<int:pk>/', views.upload_invoice, name='upload_invoice'),
path('procurement/payment-done/<int:pk>/', views.payment_done, name='payment_done'),

    path('procurement/', views.procurement_list, name='procurement_list'),
    path('procurement/create/', views.create_procurement_request, name='create_procurement'),
    path('procurement/delete/<int:pk>/', views.delete_procurement, name='delete_procurement'),

    path("ajax/get-employee/", views.get_employee_details, name="get_employee_details"),

]



 




