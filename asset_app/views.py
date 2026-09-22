# assets/views.py
from io import BytesIO
import base64
import json
import socket
from datetime import datetime
from xhtml2pdf import pisa

from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.http import HttpResponse, JsonResponse
from django.urls import reverse, resolve
from django.utils import timezone
from django.utils.timezone import now
from django.db.models import Count, Q
from django.db import IntegrityError
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError

import qrcode

from .models import (
    Asset,
    AssetHistory,
    Assignment,
    AssetRequest,
    ProcurementRequestWorkflow,
    ProcurementRequestInitial,
    ProcurementRequest1,
    Ticket,
    Employee,
    ReturnRequest,
    Notification,
)
from .forms import (
    AssetForm,
    AssignmentForm,
    AssetRequestForm,
    AddUserForm,
    LoginForm,
    UpdateRequestForm,
    TicketForm,
)

User = get_user_model()


def _department_usernames(department):
    """Usernames of users who belong to a department, resolved via Employee
    records (username matches employee_id OR employee name) plus the user's
    own department field. Employee accounts may have a blank user.department."""
    if not department:
        return []
    employees = Employee.objects.filter(department__iexact=department)
    names = set()
    for emp in employees:
        if emp.employee_id:
            names.add(emp.employee_id)
        if emp.name:
            names.add(emp.name)
    return list(names)


def _department_user_q(department, user_field='created_by'):
    from django.db.models import Q as _Q
    names = _department_usernames(department)
    q = _Q()
    if names:
        sub = _Q()
        for n in names:
            sub |= _Q(**{f'{user_field}__username__iexact': n})
        q |= sub
    if department:
        q |= _Q(**{f'{user_field}__department__iexact': department})
    if not names and not department:
        q |= _Q(**{'pk': -1})  # matches nothing
    return q


def _employee_display_name(user):
    """Real employee name for a user (username matches employee_id or name),
    falling back to the username."""
    if user is None:
        return ''
    emp = Employee.objects.filter(employee_id__iexact=user.username).first()
    if not emp:
        emp = Employee.objects.filter(name__iexact=user.username).first()
    return emp.name if emp else user.username


def _notify_admins(notification_type, title, message='', link=''):
    """Create a notification for every admin/superadmin user."""
    admins = User.objects.filter(
        Q(is_staff=True)
        | Q(role__in=['superadmin', 'asset_admin'])
    )
    Notification.objects.bulk_create([
        Notification(recipient=u, notification_type=notification_type,
                     title=title, message=message, link=link)
        for u in admins
    ])


# ------------------- CSRF FAILURE HANDLER -------------------
from django.views.decorators.csrf import csrf_exempt
from django.template import loader as template_loader
from django.http import HttpResponseForbidden


@csrf_exempt
def csrf_failure_handler(request, reason=""):
    import logging
    logger = logging.getLogger('django.security.csrf')
    logger.warning(
        "CSRF 403 | path=%s method=%s reason=%r host=%s origin=%r referer=%r "
        "secure=%s csrf_cookie_present=%s token_sent=%s",
        request.path, request.method, reason, request.get_host(),
        request.headers.get('Origin'), request.headers.get('Referer'),
        request.is_secure(), bool(request.COOKIES.get('csrfCookie') or request.COOKIES.get('csrftoken')),
        bool(request.POST.get('csrfmiddlewaretoken')),
    )
    ctx = {
        'reason': reason,
        'request_path': request.path,
        'request_method': request.method,
        'request_host': request.get_host(),
        'request_is_secure': request.is_secure(),
        'origin': request.headers.get('Origin', ''),
        'referer': request.headers.get('Referer', ''),
    }
    template = template_loader.get_template('asset_app/403_csrf.html')
    return HttpResponseForbidden(template.render(ctx))


# ------------------- NOTIFICATIONS -------------------
@login_required
def notifications(request):
    per_page = 20
    page = request.GET.get('page', 1)
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    qs = request.user.notifications.all()
    total = qs.count()
    start = (page - 1) * per_page
    items = list(qs[start:start + per_page])
    has_next = start + per_page < total
    return render(request, 'asset_app/notifications.html', {
        'notifications': items,
        'page': page,
        'has_next': has_next,
        'total': total,
    })


def _notification_target_missing(nxt):
    """Return True if the notification link points to a deleted object."""
    if not (nxt and nxt.startswith('/')):
        return False
    try:
        match = resolve(nxt)
    except Exception:
        return False
    checks = {
        'ticket_detail': (Ticket, 'pk'),
        'asset_detail': (Asset, 'pk'),
        'request_detail': (AssetRequest, 'pk'),
        'return_requests': (ReturnRequest, None),
        'view_agreement': (None, None),
    }
    if match.url_name not in checks:
        return False
    model, fk = checks[match.url_name]
    if fk is None or model is None:
        return False
    return not model.objects.filter(pk=match.kwargs.get(fk)).exists()


@login_required
def mark_notifications_read(request):
    stale = [n for n in request.user.notifications.all() if _notification_target_missing(n.link)]
    if stale:
        Notification.objects.filter(pk__in=[n.pk for n in stale]).delete()
        messages.info(request, f"Removed {len(stale)} notification(s) pointing to deleted items.")
    request.user.notifications.filter(is_read=False).update(is_read=True)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({'status': 'ok'})
        
    nxt = request.GET.get('next', '')
    if nxt and nxt.startswith('/') and not _notification_target_missing(nxt):
        return redirect(nxt)
    return redirect('notifications')


@login_required
def mark_notification_read(request, pk):
    Notification.objects.filter(pk=pk, recipient=request.user).update(is_read=True)
    nxt = request.GET.get('next', '')
    if nxt and nxt.startswith('/') and not _notification_target_missing(nxt):
        return redirect(nxt)
    return redirect('notifications')


# ------------------- USERS -------------------
@login_required(login_url='/login/')
def view_users(request):
    from .sync_employees import sync_employees_from_api
    sync_employees_from_api()
    users = User.objects.all().order_by('-id')
    employees = Employee.objects.all().order_by('name')
    emp_name_map = {e.employee_id: e.name for e in employees}
    for u in users:
        u._display_name = u.first_name or emp_name_map.get(u.username) or u.username
    return render(request, 'asset_app/view_users.html', {'users': users, 'employees': employees})

@login_required(login_url='/login/')
def delete_user(request, pk):
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
    if not is_admin:
        messages.error(request, "Only Admins can delete users.")
        return redirect('view_users')
        
    user_to_delete = get_object_or_404(User, pk=pk)
    if user_to_delete.id == request.user.id:
        messages.error(request, "You cannot delete yourself.")
    else:
        username = user_to_delete.username
        user_to_delete.delete()
        messages.success(request, f"User '{username}' deleted successfully.")
        
    return redirect('view_users')

@login_required(login_url='/login/')
def edit_user(request, pk):
    if not (request.user.is_staff or getattr(request.user, 'role', None) in ['admin', 'superadmin']):
        messages.error(request, "You do not have permission to edit users.")
        return redirect('view_users')
        
    user_to_edit = get_object_or_404(User, pk=pk)
    
    if request.method == 'POST':
        user_to_edit.username = request.POST.get('username', user_to_edit.username)
        user_to_edit.email = request.POST.get('email', user_to_edit.email)
        
        # Only allow changing role/department if superadmin, or if it's not a superadmin user being edited by an admin
        role = request.POST.get('role')
        department = request.POST.get('department')
        
        if role and getattr(request.user, 'role', None) == 'superadmin':
            user_to_edit.role = role
        if department:
            user_to_edit.department = department
            
        user_to_edit.save()
        messages.success(request, f"User '{user_to_edit.username}' updated successfully.")
        return redirect('view_users')
        
    context = {
        'edit_user_obj': user_to_edit,
        'ROLES': User.ROLE_CHOICES if hasattr(User, 'ROLE_CHOICES') else [('superadmin', 'Super Admin'), ('admin', 'Admin'), ('manager', 'Manager'), ('user', 'User')],
        'DEPARTMENTS': [
            'IT Support',
            'Network',
            'Software',
            'Hardware',
            'HR',
            'Finance'
        ]
    }
    return render(request, 'asset_app/edit_user.html', context)


@login_required
def create_asset_user(request):
    # Only Asset Admin and Superusers should create Asset Users
    if getattr(request.user, 'role', None) != "asset_admin" and not request.user.is_superuser:
        messages.error(request, "You do not have permission to access this page.")
        return redirect("asset_dashboard")

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        email = (request.POST.get("email") or "").strip()
        role = request.POST.get("role", "asset_user")
        department = request.POST.get("department", "")
        first_name = request.POST.get("first_name", "").strip() or username

        redirect_url = request.POST.get('next') or 'view_users'

        errors = []

        if not username:
            errors.append("Username / Emp ID is required.")
        elif get_user_model().objects.filter(username__iexact=username).exists():
            errors.append(f"Username \"{username}\" is already taken.")

        if not email:
            errors.append("Email address is required.")
        else:
            try:
                validate_email(email)
            except DjangoValidationError:
                errors.append("Enter a valid email address.")

        if not password:
            errors.append("Password is required.")
        elif len(password) < 8:
            errors.append("Password must be at least 8 characters long.")

        valid_roles = ["superadmin", "asset_admin", "asset_user", "manager"]
        if role not in valid_roles:
            errors.append("Please select a valid role.")

        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect(redirect_url)

        # Create asset user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role=role,
            first_name=first_name,
            is_staff=True if "admin" in role or role == "superadmin" else False,
            is_superuser=True if role == "superadmin" else False
        )
        
        # Save department
        user.department = department
        user.save()

        messages.success(request, "Asset User Created Successfully!")
        
        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
        return redirect('view_users')

    return render(request, "asset_app/create_user.html")


def create_admin(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        User.objects.create_user(
            username=username,
            password=password,
            role="asset_admin"
        )
        return redirect("asset_dashboard")

    return render(request, "asset_app/create_admin.html")


@login_required
def change_password(request):
    if request.method == "POST":
        old_password = request.POST.get("old_password", "")
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if not request.user.check_password(old_password):
            messages.error(request, "Current password is incorrect.")
        elif len(new_password) < 6:
            messages.error(request, "New password must be at least 6 characters long.")
        elif new_password != confirm_password:
            messages.error(request, "New password and confirm password do not match.")
        else:
            request.user.set_password(new_password)
            request.user.save()
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, request.user)
            messages.success(request, "Your password has been changed successfully!")
            next_url = request.META.get('HTTP_REFERER') or reverse('asset_dashboard')
            return redirect(next_url)

    next_url = request.META.get('HTTP_REFERER') or reverse('asset_dashboard')
    return redirect(next_url)


@login_required(login_url='/login/')
def add_user(request):
    if request.method == 'POST':
        form = AddUserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=True)
            role = form.cleaned_data.get('role', '')

            # Success message
            if role.lower() == 'admin':
                messages.success(request, f'✅ Admin "{user.username}" created successfully!')
            else:
                messages.success(request, f'✅ User "{user.username}" created successfully!')

            return redirect('add_user')
    else:
        form = AddUserForm()

    return render(request, 'asset_app/add_user.html', {'form': form})


def logout_user(request):
    logout(request)
    return redirect('login_user')


# ------------------- DASHBOARD -------------------
def _month_start_end(dt):
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


@login_required
def dashboard(request):
    now_dt = now()
    this_start, this_end = _month_start_end(now_dt)

    is_staff = request.user.is_staff or getattr(request.user, 'role', '') in ('superadmin', 'admin', 'asset_admin')
    is_manager = getattr(request.user, 'role', '') == 'manager'
    is_employee = not (is_staff or is_manager)

    # Base Queries
    total_team_members = 0
    if is_staff:
        assets_q = Asset.objects.all()
        assignments_q = Assignment.objects.all()
        reqs_q_base = ProcurementRequestWorkflow.objects.all()
        tickets_q_base = Ticket.objects.all()
        total_team_members = get_user_model().objects.count()
    elif is_manager:
        department = request.user.department
        assigned_asset_ids = Assignment.objects.filter(employee__department__iexact=department).values_list('asset_id', flat=True)
        assets_q = Asset.objects.filter(id__in=assigned_asset_ids)
        assignments_q = Assignment.objects.filter(employee__department__iexact=department)
        reqs_q_base = ProcurementRequestWorkflow.objects.filter(_department_user_q(department, 'requested_by'))
        tickets_q_base = Ticket.objects.filter(_department_user_q(department))
        names = _department_usernames(department)
        team_q = Q()
        if names:
            sub = Q()
            for n in names:
                sub |= Q(username__iexact=n)
            team_q |= sub
        if department:
            team_q |= Q(department__iexact=department)
        if not names and not department:
            team_q |= Q(pk=-1)
        total_team_members = get_user_model().objects.filter(team_q).count()
    else:
        # Employee
        assignments_q = Assignment.objects.filter(
            employee__employee_id__iexact=request.user.username
        ) | Assignment.objects.filter(employee__name__iexact=request.user.username)
        assigned_asset_ids = assignments_q.values_list('asset_id', flat=True)
        assets_q = Asset.objects.filter(id__in=assigned_asset_ids)
        reqs_q_base = ProcurementRequestWorkflow.objects.filter(requested_by=request.user)
        tickets_q_base = Ticket.objects.filter(created_by=request.user)

    # TOP METRICS
    total_assets = assets_q.count()
    available_assets = assets_q.filter(status__iexact='Available').count()
    assigned_assets = assets_q.filter(status__in=['Assigned', 'In Use']).count()
    checked_out_assets = assets_q.filter(status__iexact='Checked Out').count()

    # WARRANTY METRICS
    today_local = timezone.localdate()
    expiring_soon_warranty = assets_q.filter(
        warranty_end_date__isnull=False,
        warranty_end_date__gte=today_local,
        warranty_end_date__lte=today_local + timezone.timedelta(days=60),
    ).count()
    expired_warranty = assets_q.filter(
        warranty_end_date__isnull=False,
        warranty_end_date__lt=today_local,
    ).count()

    # MONTHLY METRICS
    added_this_month = assets_q.filter(created_at__gte=this_start, created_at__lt=this_end).count()
    assigned_this_month = assignments_q.filter(assigned_at__gte=this_start, assigned_at__lt=this_end).count()

    # PROCUREMENT REQUESTS THIS MONTH
    reqs_q_month = (
        reqs_q_base
        .filter(request_date__gte=this_start, request_date__lt=this_end)
        .values('status')
        .annotate(c=Count('id'))
    )

    approved = pending = rejected = 0
    for r in reqs_q_month:
        status = (r['status'] or '').lower()
        if status == 'approved':
            approved += r['c']
        elif ('pending' in status or 'manager review' in status or 'review' in status
              or 'invoice pending' in status or 'payment pending' in status):
            pending += r['c']
        elif 'reject' in status:
            rejected += r['c']

    total_reqs = approved + pending + rejected
    approved_pct = int((approved / total_reqs) * 100) if total_reqs else 0
    pending_pct = int((pending / total_reqs) * 100) if total_reqs else 0
    rejected_pct = int((rejected / total_reqs) * 100) if total_reqs else 0

    # TICKETS THIS MONTH
    tickets_month_qs = (
        tickets_q_base
        .filter(created_at__gte=this_start, created_at__lt=this_end)
        .values('status')
        .annotate(c=Count('id'))
    )
    tickets_map = {r['status'].lower(): r['c'] for r in tickets_month_qs}
    tickets_pending = tickets_map.get('pending', 0)
    tickets_resolved = tickets_map.get('resolved', 0)
    total_tickets_month = tickets_q_base.filter(created_at__gte=this_start, created_at__lt=this_end).count()

    # ASSETS BY TYPE
    types_q = assets_q.values('asset_type').annotate(c=Count('id'))
    asset_types = [r['asset_type'] for r in types_q]
    asset_type_counts = [r['c'] for r in types_q]

    ASSET_TYPES = [r['asset_type'] for r in types_q if r['asset_type']]
    available_by_type = []
    assigned_by_type = []
    category_stats = []
    for t in ASSET_TYPES:
        av = assets_q.filter(asset_type__iexact=t, status__iexact='Available').count()
        ass = assets_q.filter(asset_type__iexact=t, status__in=['Assigned', 'In Use']).count()
        tot = assets_q.filter(asset_type__iexact=t).count()
        available_by_type.append(av)
        assigned_by_type.append(ass)
        if tot > 0:
            category_stats.append({
                'type': t,
                'available': av,
                'assigned': ass,
                'total': tot
            })

    requests_list = reqs_q_base.order_by('-request_date')[:30]

    # BRANCH WISE ASSETS
    branch_asset_counts_raw = (
        assignments_q.filter(status__in=['In Use'])
        .values('employee__branch', 'asset__asset_type')
        .annotate(c=Count('id'))
        .order_by('employee__branch', '-c')
    )
    branch_data = {}
    for row in branch_asset_counts_raw:
        branch_name = row['employee__branch']
        if not branch_name or branch_name.strip() == '':
            branch_name = "Unspecified Branch"
            
        asset_type = row['asset__asset_type'] or "Unknown"
        count = row['c']
        
        if branch_name not in branch_data:
            branch_data[branch_name] = {'total': 0, 'types': []}
            
        branch_data[branch_name]['total'] += count
        branch_data[branch_name]['types'].append({'type': asset_type, 'count': count})
        
    branch_counts = [{'branch': k, 'total': v['total'], 'types': v['types']} for k, v in branch_data.items()]
    branch_counts = sorted(branch_counts, key=lambda x: x['total'], reverse=True)

    # EMPLOYEE SPECIFIC DATA
    emp_my_assets = 0
    emp_pending_requests = 0
    emp_approved_requests = 0
    emp_returned_assets = 0
    emp_recent_assignments = []
    emp_recent_requests = []

    if is_employee:
        emp_my_assets = assignments_q.filter(status__iexact='In Use').count()
        emp_returned_assets = assignments_q.filter(status__icontains='Returned').values('asset').distinct().count()
        emp_recent_assignments = assignments_q.filter(status__iexact='In Use').order_by('-assigned_at')[:10]
        
        emp_pending_requests = reqs_q_base.filter(
            Q(status__icontains='Pending') | Q(status__icontains='Review')
        ).count()
        
        emp_approved_requests = reqs_q_base.filter(
            Q(status__icontains='Approved') | Q(status__icontains='Completed')
        ).count()
        
        emp_recent_requests = reqs_q_base.order_by('-request_date')[:5]

    # ADMIN MOCKUP SPECIFIC
    assets_maintenance = assets_q.filter(status__iexact='Maintenance').count()
    assets_in_use = assets_q.filter(status__in=['Assigned', 'In Use']).count()
    
    status_counts_q = assets_q.values('status').annotate(c=Count('id'))
    status_labels = []
    status_data = []
    for row in status_counts_q:
        status_labels.append(row['status'] or 'Unknown')
        status_data.append(row['c'])
    
    # Real line chart data for the "Requests Overview" (Last 6 Months)
    import calendar
    from datetime import date
    today_date = date.today()
    line_chart_labels = []
    line_chart_total = []
    line_chart_approved = []
    line_chart_pending = []
    line_chart_rejected = []
    
    for i in range(5, -1, -1):
        m = today_date.month - i
        y = today_date.year
        if m <= 0:
            m += 12
            y -= 1
        line_chart_labels.append(calendar.month_abbr[m])
        qs = reqs_q_base.filter(request_date__year=y, request_date__month=m)
        t_count = qs.count()
        a_count = qs.filter(status__icontains='Approved').count()
        r_count = qs.filter(status__icontains='Reject').count()
        p_count = t_count - a_count - r_count
        
        line_chart_total.append(t_count)
        line_chart_approved.append(a_count)
        line_chart_pending.append(p_count)
        line_chart_rejected.append(r_count)

    # Recent activity feeds
    recent_assigns = []
    recent_reqs_feed = []
    if is_staff:
        recent_assigns = Assignment.objects.all().order_by('-assigned_at')[:3]
        recent_reqs_feed = ProcurementRequestWorkflow.objects.all().order_by('-request_date')[:3]

    import shutil
    from django.contrib.sessions.models import Session
    
    active_sessions = Session.objects.filter(expire_date__gte=timezone.now()).count()
    disk = shutil.disk_usage('/')
    storage_percent = int((disk.used / disk.total) * 100)

    context = {
        'display_name': request.user.first_name or (
            Employee.objects.filter(employee_id__iexact=request.user.username).values_list('name', flat=True).first()
            or request.user.username
        ),
        'active_sessions': active_sessions,
        'storage_percent': storage_percent,
        'total_assets': total_assets,
        'available_assets': available_assets,
        'assigned_assets': assigned_assets,
        'checked_out_assets': checked_out_assets,
        'assets_in_use': assets_in_use,
        'assets_maintenance': assets_maintenance,
        'status_labels_json': json.dumps(status_labels),
        'status_data_json': json.dumps(status_data),
        
        'added_this_month': added_this_month,
        'assigned_this_month': assigned_this_month,
        'expiring_soon_warranty': expiring_soon_warranty,
        'expired_warranty': expired_warranty,
        'approved': approved,
        'pending': pending,
        'rejected': rejected,
        'total_reqs': total_reqs,
        
        'line_chart_labels': json.dumps(line_chart_labels),
        'line_chart_total': json.dumps(line_chart_total),
        'line_chart_approved': json.dumps(line_chart_approved),
        'line_chart_pending': json.dumps(line_chart_pending),
        'line_chart_rejected': json.dumps(line_chart_rejected),
        
        'recent_assigns': recent_assigns,
        'recent_reqs_feed': recent_reqs_feed,
        
        'approved_pct': approved_pct,
        'pending_pct': pending_pct,
        'rejected_pct': rejected_pct,
        'tickets_pending': tickets_pending,
        'tickets_resolved': tickets_resolved,
        'total_tickets_month': total_tickets_month,
        'asset_types_json': json.dumps(asset_types),
        'asset_type_counts_json': json.dumps(asset_type_counts),
        'asset_type_labels_json': json.dumps(ASSET_TYPES),
        'available_by_type_json': json.dumps(available_by_type),
        'assigned_by_type_json': json.dumps(assigned_by_type),
        'category_stats': category_stats,
        'requests_list': requests_list,
        'branch_counts': branch_counts,
        'total_team_members': total_team_members,
        'is_employee': is_employee,
        'is_manager': is_manager,
        'emp_my_assets': emp_my_assets,
        'emp_pending_requests': emp_pending_requests,
        'emp_approved_requests': emp_approved_requests,
        'emp_returned_assets': emp_returned_assets,
        'emp_recent_assignments': emp_recent_assignments,
        'emp_recent_requests': emp_recent_requests,
    }

    return render(request, 'asset_app/dashboard.html', context)


# ------------------- ASSET CRUD -------------------
@login_required
def add_asset(request):
    if request.method == 'POST':
        form = AssetForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                asset = form.save()
                if asset.status.lower() == "in use":
                    messages.info(request, "Asset added and marked as 'In Use'. Please assign it now.")
                    return redirect(f"{reverse('assign_asset')}?asset={asset.pk}")
                else:
                    messages.success(request, "Asset added successfully!")
                    return redirect('view_assets')
            except IntegrityError:
                messages.error(request, "Error: Asset ID must be unique.")
    else:
        form = AssetForm()

    return render(request, 'asset_app/add_asset.html', {'form': form})


@login_required
def bulk_upload_assets(request):
    if request.method == 'POST' and request.FILES.get('bulk_file'):
        uploaded_file = request.FILES['bulk_file']
        filename = uploaded_file.name.lower()
        
        import csv
        import io
        import random
        from datetime import datetime
        
        created_count = 0
        errors = []
        rows = []
        
        if filename.endswith('.csv'):
            try:
                decoded_file = uploaded_file.read().decode('utf-8-sig', errors='ignore')
                io_string = io.StringIO(decoded_file)
                reader = csv.DictReader(io_string)
                rows = list(reader)
            except Exception as e:
                messages.error(request, f"Error parsing CSV file: {str(e)}")
                return redirect('add_asset')
        elif filename.endswith('.xlsx') or filename.endswith('.xls'):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(uploaded_file, data_only=True)
                sheet = wb.active
                headers = [str(cell.value or '').strip() for cell in sheet[1]]
                for row in sheet.iter_rows(min_row=2, values_only=True):
                    if any(row):
                        row_dict = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
                        rows.append(row_dict)
            except ImportError:
                messages.error(request, "Excel (.xlsx) parsing requires openpyxl. Please upload a .csv file or install openpyxl.")
                return redirect('add_asset')
            except Exception as e:
                messages.error(request, f"Error parsing Excel file: {str(e)}")
                return redirect('add_asset')
        else:
            messages.error(request, "Unsupported file format. Please upload a .csv or .xlsx Excel file.")
            return redirect('add_asset')
            
        def parse_date(d_val):
            if not d_val:
                return None
            if hasattr(d_val, 'date'):
                return d_val.date()
            d_str = str(d_val).strip()
            if d_str.lower() == 'complete':
                return None
            for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%m/%d/%Y'):
                try:
                    return datetime.strptime(d_str, fmt).date()
                except ValueError:
                    pass
            return None

        for idx, row in enumerate(rows, start=2):
            clean_row = {str(k).strip().lower().replace(' ', '_').replace('/', '_'): v for k, v in row.items() if k}
            
            asset_type = clean_row.get('asset_type') or clean_row.get('type') or 'Laptop'
            company_name = clean_row.get('manufacturer_company') or clean_row.get('manufacturer') or clean_row.get('company_name') or clean_row.get('company') or 'N/A'
            model = clean_row.get('model_name') or clean_row.get('model') or 'N/A'
            series_number = clean_row.get('serial___series_number') or clean_row.get('serial_number') or clean_row.get('serial') or clean_row.get('series_number') or f"SN-{random.randint(100000, 999999)}"
            vendor_name = clean_row.get('vendor_name') or clean_row.get('vendor') or ''
            status = clean_row.get('status') or 'Available'
            ram = clean_row.get('ram') or ''
            storage = clean_row.get('storage') or ''
            purchase_date_str = clean_row.get('purchase___add_date') or clean_row.get('purchase_date') or ''
            cost_val = clean_row.get('cost') or 0
            warranty = clean_row.get('warranty') or ''
            warranty_end_date_str = clean_row.get('warranty_end_date') or ''
            
            try:
                cost_num = float(cost_val) if cost_val else 0.0
            except (ValueError, TypeError):
                cost_num = 0.0
                
            try:
                asset_id = clean_row.get('asset_id')
                if not asset_id or Asset.objects.filter(asset_id=asset_id).exists():
                    asset_id = f"AST-{random.randint(10000, 99999)}"
                    
                Asset.objects.create(
                    asset_id=asset_id,
                    asset_type=str(asset_type).strip(),
                    company_name=str(company_name).strip(),
                    model=str(model).strip(),
                    series_number=str(series_number).strip(),
                    vendor_name=str(vendor_name).strip() if vendor_name else None,
                    status=str(status).strip(),
                    ram=str(ram).strip() if ram else None,
                    storage=str(storage).strip() if storage else None,
                    purchase_date=parse_date(purchase_date_str),
                    cost=cost_num,
                    warranty=str(warranty).strip() if warranty else None,
                    warranty_end_date=parse_date(warranty_end_date_str)
                )
                created_count += 1
            except Exception as e:
                errors.append(f"Row {idx}: {str(e)}")
                
        if created_count > 0:
            messages.success(request, f"Successfully uploaded and imported {created_count} asset(s) from Excel/CSV!")
        if errors:
            messages.warning(request, f"Skipped {len(errors)} row(s): {', '.join(errors[:3])}")
            
        return redirect('view_assets')
        
    messages.error(request, "Please select a valid Excel or CSV file to upload.")
    return redirect('add_asset')


@login_required
def download_asset_template(request):
    import csv
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="bulk_asset_upload_template.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Asset Type', 'Manufacturer/Company', 'Model Name', 'Serial Number',
        'Vendor Name', 'Status', 'RAM', 'Storage', 'Purchase Date', 'Cost', 'Warranty', 'Warranty End Date'
    ])
    writer.writerow([
        'Laptop', 'Dell', 'Latitude 5420', 'SN-DELL12345',
        'ABC Infotech', 'Available', '16GB', '512GB', '15/01/2024', '75000', '1 Year', '15/01/2025'
    ])
    writer.writerow([
        'Desktop', 'HP', 'ProDesk 400', 'SN-HP98765',
        'XYZ Suppliers', 'Available', '8GB', '256GB', '20/02/2024', '45000', '3 Years', '20/02/2027'
    ])
    return response


@login_required
def edit_asset(request, pk):
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
    if not request.user.is_authenticated or not is_admin:
        messages.error(request, "Only an admin can edit assets.")
        return redirect("view_assets")

    asset = get_object_or_404(Asset, pk=pk)
    
    if request.method == 'POST':
        form = AssetForm(request.POST, request.FILES, instance=asset)
        if form.is_valid():
            try:
                if form.has_changed():
                    changed_fields = []
                    for field in form.changed_data:
                        old_val = form.initial.get(field, 'None')
                        new_val = form.cleaned_data.get(field)
                        changed_fields.append(f"{field.replace('_', ' ').title()}: '{old_val}' -> '{new_val}'")
                    changes_str = " | ".join(changed_fields)
                    form.save()
                    AssetHistory.objects.create(
                        asset=asset,
                        edited_by=request.user,
                        changes=changes_str
                    )
                else:
                    form.save()
                messages.success(request, "Asset updated successfully!")
                return redirect('asset_detail', pk=asset.pk)
            except IntegrityError:
                messages.error(request, "Error: Asset ID must be unique.")
    else:
        form = AssetForm(instance=asset)

    return render(request, 'asset_app/edit_asset.html', {'form': form, 'asset': asset})


def get_network_host(request):
    host = request.get_host()
    if host.startswith('127.0.0.1') or host.startswith('localhost'):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            if ':' in host:
                port = host.split(':')[1]
                return f"{ip}:{port}"
            return ip
        except Exception:
            return host
    return host

@login_required
def asset_detail(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    current_assignment = Assignment.objects.filter(asset=asset).select_related("employee").last()

    server_ip = get_network_host(request)
    qr_url = f"http://{server_ip}{reverse('asset_detail1', args=[asset.pk])}"

    qr = qrcode.QRCode(version=2, box_size=10, border=4)
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    current_assignment = Assignment.objects.filter(asset=asset, status='In Use').select_related("employee").last()
    
    # History of this specific asset
    assignments = list(Assignment.objects.filter(asset=asset).select_related("employee", "assigned_by").order_by("-assigned_at"))
    edits = list(AssetHistory.objects.filter(asset=asset).select_related("edited_by").order_by("-edited_at"))

    return render(request, "asset_app/asset_detail.html", {
        "asset": asset,
        "qr_base64": qr_base64,
        "current_assignment": current_assignment,
        "asset_history": assignments,
        "edit_history": edits,
    })


# ------------------- WARRANTY TRACKING -------------------
@login_required
def warranty_tracking(request):
    assets = Asset.objects.exclude(warranty="").exclude(warranty__isnull=True).order_by('warranty_end_date')

    now = timezone.localdate()
    ref_date = now + timezone.timedelta(days=60)

    expired = [a for a in assets if a.warranty_end_date and a.warranty_end_date < now]
    expiring = [a for a in assets if a.warranty_end_date and now <= a.warranty_end_date <= ref_date]
    active = [a for a in assets if a.warranty_end_date and a.warranty_end_date > ref_date]
    complete = [a for a in assets if a.warranty == 'Complete']

    context = {
        'expired': expired,
        'expiring': expiring,
        'active': active,
        'complete': complete,
        'today': now,
    }
    return render(request, 'asset_app/warranty_tracking.html', context)


# ------------------- ASSIGN ASSET -------------------
@login_required
def assign_asset(request):
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
    if not request.user.is_authenticated or not is_admin:
        messages.error(request, "Only an admin can assign assets.")
        return redirect("asset_dashboard")
    if request.method == "POST":
        assigned_date = request.POST.get('assigned_date')
        assigned_date_obj = None
        if assigned_date:
            for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
                try:
                    assigned_date_obj = datetime.strptime(str(assigned_date).strip(), fmt).date()
                    break
                except (TypeError, ValueError):
                    continue

        if assigned_date_obj and assigned_date_obj > timezone.now().date():
            messages.error(request, "Assignment date cannot be in the future.")
            next_url = request.POST.get('next')
            if next_url:
                return redirect(next_url)
            return redirect(reverse('assign_asset'))

        post_data = request.POST.copy()
        status = post_data.get('status', '')
        search_input = (request.POST.get('emp_search') or '').strip()
        manual_name = (post_data.get('emp_name') or search_input or '').strip()
        manual_dept = (post_data.get('emp_dept') or '').strip()
        manual_branch = (post_data.get('emp_branch') or post_data.get('branch') or '').strip()

        # Handle manual user entry (only permitted for Temporary Use status)
        if not emp_id:
            if 'temporary' in status.lower():
                name_to_use = manual_name if manual_name else "Temporary User"
                emp_obj = Employee.objects.filter(name__iexact=name_to_use).first()
                if not emp_obj:
                    import random
                    rand_num = random.randint(1000, 9999)
                    emp_obj = Employee.objects.create(
                        name=name_to_use,
                        employee_id=f"TEMP-{rand_num}",
                        department=manual_dept or 'Temporary',
                        branch=manual_branch or ''
                    )
                post_data['employee'] = emp_obj.id
            else:
                messages.error(request, "Please select a registered employee for 'In Use' assignments.")
                next_url = request.POST.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect('view_assets')

        form = AssignmentForm(post_data)
        if form.is_valid():
            assignment = form.save(commit=False)
            assignment.assigned_by = request.user
            if assigned_date_obj:
                assignment.assigned_date = assigned_date_obj

            # Close out any previous active assignments for this asset so it's not assigned twice
            Assignment.objects.filter(
                asset=assignment.asset,
                status__in=['In Use', 'Temporary', 'Temporary Use']
            ).update(
                status='Returned',
                returned_at=timezone.now()
            )

            assignment.save()
            
            # Update employee department and branch if provided/edited manually
            employee = assignment.employee
            emp_updated = False
            if manual_dept and employee.department != manual_dept:
                employee.department = manual_dept
                emp_updated = True
            if manual_branch and employee.branch != manual_branch:
                employee.branch = manual_branch
                emp_updated = True
            if emp_updated:
                employee.save()
                
            asset = assignment.asset
            if assignment.status and 'temporary' in assignment.status.lower():
                asset.status = "Temporary"
            else:
                asset.status = "In Use"
            asset.save()

            next_url = request.POST.get('next')
            if next_url:
                return redirect(next_url)
            messages.success(request, "Asset assigned successfully!")
            return redirect('view_assets')
        else:
            messages.error(request, f"Assignment failed: {form.errors.as_text()}")
            next_url = request.POST.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('view_assets')
    else:
        from .sync_employees import sync_employees_from_api
        sync_employees_from_api()
        form = AssignmentForm()

    pre_selected_asset_id = request.GET.get('asset', '')
    from django.db.models import Q
    if pre_selected_asset_id:
        assets_query = Asset.objects.filter(Q(status__iexact="Available") | Q(pk=pre_selected_asset_id)).order_by('asset_id')
    else:
        assets_query = Asset.objects.filter(status__iexact="Available").order_by('asset_id')

    employees = Employee.objects.all().order_by('name')
    employees_json = json.dumps([
        {
            'id': emp.id,
            'emp_id': emp.employee_id,
            'name': emp.name,
            'dept': emp.department or '',
            'branch': emp.branch or '',
        }
        for emp in employees
    ])
    context = {
        "employees": employees,
        "employees_json": employees_json,
        "assets": assets_query,
        "pre_selected_asset": pre_selected_asset_id,
        "today_date": timezone.now().date().isoformat(),
        "today_date_display": timezone.now().date().strftime('%d/%m/%Y'),
        "form": form,
    }
    return render(request, "asset_app/assign_asset.html", context)


# ------------------- DIGITAL SIGNATURE / AGREEMENT -------------------
@login_required
def sign_agreement(request, assignment_id):
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    
    if request.method == 'POST':
        signature_data = request.POST.get('signature_data')
        if signature_data:
            assignment.signature = signature_data
            assignment.is_signed = True
            assignment.agreement_date = timezone.now()
            assignment.save()
            messages.success(request, f"Agreement signed successfully for {assignment.asset.asset_id}!")
            return redirect('assigned_employees')
            
    return render(request, 'asset_app/sign_agreement.html', {
        'assignment': assignment,
        'today_date': timezone.now().date()
    })

@login_required
def view_agreement(request, assignment_id):
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    return render(request, 'asset_app/view_agreement.html', {
        'assignment': assignment
    })

@login_required
@login_required
def return_asset(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        assign = Assignment.objects.filter(asset=asset, status='In Use').last()
        if not assign:
            messages.error(request, f"No active assignment found for {asset.asset_id}.")
            return redirect('view_assets')

        is_staff = request.user.is_staff or getattr(request.user, 'role', '') in ('superadmin', 'admin', 'asset_admin')
        is_manager = getattr(request.user, 'role', '') == 'manager'
        is_owner = (
            str(assign.employee.employee_id) == str(request.user.username)
            or str(assign.employee.name) == str(request.user.username)
        )
        if not (is_staff or is_manager or is_owner):
            messages.error(request, "You can only return your own assigned asset.")
            return redirect('view_assets')

        reason = (request.POST.get('reason') or '').strip()
        if not reason:
            messages.error(request, f"Please write a reason to return {asset.asset_id}.")
            return redirect('view_assets')

        assign.status = 'Returned'
        assign.return_reason = reason
        assign.returned_at = timezone.now()
        assign.save()
        asset.status = 'Available'
        asset.save()
        messages.success(request, f"Asset {asset.asset_id} returned successfully.")
    return redirect('view_assets')


@login_required
def request_return_asset(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        assign = Assignment.objects.filter(asset=asset, status='In Use').last()
        if not assign:
            messages.error(request, f"No active assignment found for {asset.asset_id}.")
            return redirect('view_assets')

        is_staff = request.user.is_staff or getattr(request.user, 'role', '') in ('superadmin', 'admin', 'asset_admin')
        is_manager = getattr(request.user, 'role', '') == 'manager'
        is_owner = (
            str(assign.employee.employee_id) == str(request.user.username)
            or str(assign.employee.name) == str(request.user.username)
        )
        if not (is_staff or is_manager or is_owner):
            messages.error(request, "You can only request a return for your own assigned asset.")
            return redirect('view_assets')

        reason = (request.POST.get('reason') or '').strip()
        if not reason:
            messages.error(request, f"Please write a reason to return {asset.asset_id}.")
            return redirect('view_assets')

        if ReturnRequest.objects.filter(asset=asset, status='Pending').exists():
            messages.error(request, f"A return request for {asset.asset_id} is already pending approval.")
            return redirect('view_assets')

        ReturnRequest.objects.create(
            asset=asset,
            assignment=assign,
            employee=assign.employee,
            reason=reason,
            status='Pending',
        )
        _notify_admins(
            'return_request',
            f"New return request for {asset.asset_id}",
            f"{assign.employee.name} requested to return {asset.asset_id}.",
            reverse('return_requests'),
        )
        messages.success(request, f"Return request submitted for {asset.asset_id}. Awaiting admin approval.")
    return redirect('view_assets')


@login_required
def process_return(request, pk):
    rq = get_object_or_404(ReturnRequest, pk=pk)
    is_staff = request.user.is_staff or getattr(request.user, 'role', '') in ('superadmin', 'admin', 'asset_admin')
    is_manager = getattr(request.user, 'role', '') == 'manager'
    if not (is_staff or is_manager):
        messages.error(request, "Only an admin or manager can process return requests.")
        return redirect('return_requests')

    if rq.status not in ['Pending', 'Manager_Approved', 'Admin_Approved']:
        messages.error(request, f"Return request for {rq.asset.asset_id} was already processed.")
        return redirect('return_requests')

    action = request.POST.get('action', 'accept')

    if action == 'reject':
        rq.status = 'Rejected'
        rq.processed_by = request.user
        rq.processed_at = timezone.now()
        rq.save()
        messages.info(request, f"Return request for {rq.asset.asset_id} was declined. Asset stays with {rq.employee.name}.")
    else:
        is_admin = getattr(request.user, 'role', '') == 'admin' or (request.user.is_staff and getattr(request.user, 'role', '') != 'superadmin')
        is_superadmin = getattr(request.user, 'role', '') == 'superadmin'

        if is_superadmin:
            assign = rq.assignment
            if assign.status == 'In Use':
                assign.status = 'Returned'
                assign.return_reason = rq.reason
                assign.returned_at = timezone.now()
                assign.save()
                rq.asset.status = 'Available'
                rq.asset.save()

            rq.status = 'Accepted'
            rq.processed_by = request.user
            rq.processed_at = timezone.now()
            rq.save()
            messages.success(request, f"Return request for {rq.asset.asset_id} accepted. Asset is now available.")
        elif is_admin:
            if rq.status in ['Pending', 'Manager_Approved']:
                rq.status = 'Admin_Approved'
                rq.save()
                messages.success(request, f"Return request for {rq.asset.asset_id} approved. Forwarded to Super Admin for final processing.")
            else:
                messages.error(request, "Invalid action or permission denied.")
        elif is_manager:
            if rq.status == 'Pending':
                rq.status = 'Manager_Approved'
                rq.save()
                messages.success(request, f"Return request for {rq.asset.asset_id} approved. Forwarded to Admin.")
            else:
                messages.error(request, "Invalid action or permission denied.")
        else:
            messages.error(request, "Invalid action or permission denied.")

    nxt = request.POST.get('next', '')
    if nxt and nxt.startswith('/'):
        return redirect(nxt)
    return redirect('return_requests')

@login_required
def transfer_asset(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        new_emp_id = request.POST.get('employee')
        if not new_emp_id:
            messages.error(request, "Please select an employee.")
            return redirect('view_assets')
            
        # Close out any previous active assignments for this asset
        Assignment.objects.filter(
            asset=asset,
            status__in=['In Use', 'Temporary', 'Temporary Use']
        ).update(
            status='Returned',
            returned_at=timezone.now()
        )
            
        new_emp = get_object_or_404(Employee, id=new_emp_id)
        new_assignment = Assignment.objects.create(
            asset=asset,
            employee=new_emp,
            status='In Use'
        )
        asset.status = 'In Use'
        asset.save()
        asset_type_clean = str(asset.asset_type).strip().lower() if asset.asset_type else ''
        messages.success(request, f"Asset {asset.asset_id} transferred to {new_emp.name}. (DEBUG: asset type is '{asset_type_clean}')")
        
        # We do not automatically redirect to the signature page because the admin does not sign it.
        # The employee will sign it later via the button on the list views.
            
    return redirect('view_assets')


def get_employee_details(request):
    emp_id = request.GET.get("emp_id")
    if not emp_id:
        return JsonResponse({"error": "emp_id missing"}, status=400)
    try:
        emp = Employee.objects.get(id=int(emp_id))
    except (Employee.DoesNotExist, ValueError):
        return JsonResponse({"error": "Employee not found"}, status=404)

    return JsonResponse({
        "name": emp.name,
        "department": emp.department,
        "branch": emp.branch,
    })


# ------------------- RETURN REQUESTS (dedicated admin page) -------------------
@login_required
def return_requests(request):
    is_staff = request.user.is_staff or getattr(request.user, 'role', '') in ('superadmin', 'admin', 'asset_admin')
    is_manager = getattr(request.user, 'role', '') == 'manager'
    if not (is_staff or is_manager):
        return redirect('asset_dashboard')

    if is_manager:
        # Managers only see 'Pending' requests for their department
        pending_returns = (
            ReturnRequest.objects.filter(status='Pending', employee__department__iexact=request.user.department)
            .select_related('asset', 'employee')
            .order_by('-created_at')
        )
        processed_returns = (
            ReturnRequest.objects.filter(employee__department__iexact=request.user.department)
            .exclude(status='Pending')
            .select_related('asset', 'employee', 'processed_by')
            .order_by('-processed_at')[:30]
        )
        pending_count = ReturnRequest.objects.filter(status='Pending', employee__department__iexact=request.user.department).count()
        accepted_count = ReturnRequest.objects.filter(status='Accepted', employee__department__iexact=request.user.department).count()
        rejected_count = ReturnRequest.objects.filter(status='Rejected', employee__department__iexact=request.user.department).count()
    elif getattr(request.user, 'role', '') == 'superadmin':
        # Super Admins see 'Admin_Approved' requests
        pending_returns = (
            ReturnRequest.objects.filter(status__in=['Pending', 'Manager_Approved', 'Admin_Approved'])
            .select_related('asset', 'employee')
            .order_by('-created_at')
        )
        processed_returns = (
            ReturnRequest.objects.exclude(status__in=['Pending', 'Manager_Approved', 'Admin_Approved'])
            .select_related('asset', 'employee', 'processed_by')
            .order_by('-processed_at')[:30]
        )
        pending_count = ReturnRequest.objects.filter(status='Admin_Approved').count()
        accepted_count = ReturnRequest.objects.filter(status='Accepted').count()
        rejected_count = ReturnRequest.objects.filter(status='Rejected').count()
    else:
        # Admins see 'Manager_Approved' requests
        pending_returns = (
            ReturnRequest.objects.filter(status__in=['Pending', 'Manager_Approved'])
            .select_related('asset', 'employee')
            .order_by('-created_at')
        )
        processed_returns = (
            ReturnRequest.objects.exclude(status__in=['Pending', 'Manager_Approved'])
            .select_related('asset', 'employee', 'processed_by')
            .order_by('-processed_at')[:30]
        )
        pending_count = ReturnRequest.objects.filter(status='Manager_Approved').count()
        accepted_count = ReturnRequest.objects.filter(status='Accepted').count()
        rejected_count = ReturnRequest.objects.filter(status='Rejected').count()

    for pr in processed_returns:
        if pr.processed_by:
            pr.processed_by_name = _employee_display_name(pr.processed_by)

    return render(request, 'asset_app/return_requests.html', {
        'pending_returns': pending_returns,
        'processed_returns': processed_returns,
        'pending_count': pending_count,
        'accepted_count': accepted_count,
        'rejected_count': rejected_count,
    })


# ------------------- VIEW ASSETS (fixed) -------------------
@login_required
def view_assets(request):
    is_staff = request.user.is_staff or getattr(request.user, 'role', '') in ('superadmin', 'admin', 'asset_admin')
    is_manager = getattr(request.user, 'role', '') == 'manager'
        
    active_statuses = ['In Use', 'Temporary', 'Temporary Use']
    if is_staff:
        raw_assignments = Assignment.objects.select_related("asset", "employee").filter(status__in=active_statuses).order_by('asset_id', '-id')
    elif is_manager:
        raw_assignments = Assignment.objects.select_related("asset", "employee").filter(
            employee__department__iexact=request.user.department,
            status__in=active_statuses
        ).order_by('asset_id', '-id')
    else:
        # Employee - only show their own assets
        raw_assignments = Assignment.objects.select_related("asset", "employee").filter(
            Q(employee__employee_id__iexact=request.user.username) | Q(employee__name__iexact=request.user.username),
            status__in=active_statuses
        ).order_by('asset_id', '-id')

    seen_assets = set()
    assignments = []
    for a in raw_assignments:
        if a.asset_id not in seen_assets:
            seen_assets.add(a.asset_id)
            assignments.append(a)

    # Unassigned assets (only truly Available / Under Repair assets, excluding all currently assigned assets)
    if is_staff:
        assigned_asset_ids = set(Assignment.objects.filter(status__in=active_statuses).values_list('asset_id', flat=True))

        # Available Stock (Available / Under Repair assets that are not assigned)
        unassigned_assets = Asset.objects.exclude(
            id__in=assigned_asset_ids
        ).filter(
            Q(status__iexact='Available') | Q(status__iexact='Under Repair')
        )

        # Temporary Assets section: Only unassigned stock assets marked with Status='Temporary' or 'Temporary Use'
        temporary_assets = Asset.objects.exclude(
            id__in=assigned_asset_ids
        ).filter(
            Q(status__iexact='Temporary') | Q(status__iexact='Temporary Use')
        )

        dead_assets = Asset.objects.filter(status__iexact='Dead')
    else:
        unassigned_assets = []
        dead_assets = []
        temporary_assets = []

    # Calculate asset stats
    if is_staff:
        asset_stats = Asset.objects.values('asset_type').annotate(
            total=Count('id'),
            in_use=Count('id', filter=Q(status__iexact='In Use')),
            available=Count('id', filter=Q(status__iexact='Available')),
            dead=Count('id', filter=Q(status__iexact='Dead')),
            temporary=Count('id', filter=Q(status__iexact='Temporary')),
            other=Count('id', filter=~Q(status__iexact='In Use') & ~Q(status__iexact='Available') & ~Q(status__iexact='Dead') & ~Q(status__iexact='Temporary'))
        ).order_by('asset_type')
    else:
        assigned_asset_ids = assignments.values_list('asset_id', flat=True)
        asset_stats = Asset.objects.filter(id__in=assigned_asset_ids).values('asset_type').annotate(
            total=Count('id'),
            in_use=Count('id'),
            available=Count('id', filter=Q(status__iexact='Available')),
            dead=Count('id', filter=Q(status__iexact='Dead')),
            temporary=Count('id', filter=Q(status__iexact='Temporary')),
            other=Count('id', filter=~Q(status__iexact='In Use') & ~Q(status__iexact='Available') & ~Q(status__iexact='Dead') & ~Q(status__iexact='Temporary'))
        ).order_by('asset_type')

    # Employees see all assets; requests they have made
    employee_requested = []
    if not (is_staff or is_manager):
        employee_requested = AssetRequest.objects.filter(requested_by=request.user).values_list('pk', flat=True)

    # Sub-types dropdown data: main_type -> list of {name, pk}
    type_dropdowns = []
    for t in sorted(Asset.objects.exclude(asset_type='').values_list('asset_type', flat=True).distinct()):
        sub_assets = Asset.objects.filter(asset_type__iexact=t).exclude(name='').order_by('name')
        if sub_assets.exists():
            type_dropdowns.append({
                'type': t,
                'subtypes': [{'name': a.name, 'pk': a.pk} for a in sub_assets],
            })

    if is_manager:
        pending_return_requests = ReturnRequest.objects.filter(status='Pending', employee__department__iexact=request.user.department).select_related('asset', 'employee').order_by('-created_at')
    elif is_staff:
        pending_return_requests = ReturnRequest.objects.filter(status__in=['Pending', 'Manager_Approved']).select_related('asset', 'employee').order_by('-created_at')
    else:
        pending_return_requests = []

    pending_return_asset_pks = list(
        ReturnRequest.objects.filter(employee__employee_id__iexact=request.user.username, status__in=['Pending', 'Manager_Approved']).values_list('asset_id', flat=True)
    )

    employees = Employee.objects.all().order_by('name')
    employees_json = json.dumps([
        {
            'id': emp.id,
            'emp_id': emp.employee_id,
            'name': emp.name,
            'dept': emp.department or '',
            'branch': emp.branch or '',
        }
        for emp in employees
    ])

    return render(request, 'asset_app/view_assets.html', {
        'assignments': assignments,
        'unassigned_assets': unassigned_assets,
        'dead_assets': dead_assets,
        'temporary_assets': temporary_assets,
        'asset_stats': asset_stats,
        'employees': employees,
        'employees_json': employees_json,
        'today_date': timezone.now().date().isoformat(),
        'today_date_display': timezone.now().date().strftime('%d/%m/%Y'),
        'is_employee': not (is_staff or is_manager),
        'type_dropdowns': type_dropdowns,
        'employee_requested': employee_requested,
        'pending_return_requests': pending_return_requests,
        'pending_return_asset_pks': pending_return_asset_pks,
    })


# ------------------- ASSIGNED EMPLOYEES -------------------
@login_required
def assigned_employees(request):
    is_staff = request.user.is_staff or getattr(request.user, 'role', '') in ('superadmin', 'admin', 'asset_admin')
    is_manager = getattr(request.user, 'role', '') == 'manager'
    
    if not (is_staff or is_manager):
        return redirect('asset_dashboard')
        
    if is_staff:
        assignments = Assignment.objects.select_related("asset", "employee").filter(status__iexact='In Use')
    else:
        assignments = Assignment.objects.select_related("asset", "employee").filter(
            employee__department__iexact=request.user.department,
            status__iexact='In Use'
        )

    # Build map: key = Employee object, value = list of dicts
    employee_asset_map = {}
    for assign in assignments:
        emp = assign.employee
        if emp not in employee_asset_map:
            employee_asset_map[emp] = []
        employee_asset_map[emp].append({
            'asset': assign.asset,
            'assignment': assign
        })

    return render(request, 'asset_app/assigned_employees.html', {
        'employee_asset_map': employee_asset_map,
    })


# ------------------- QR / PDF / Download -------------------
def download_qr(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    server_ip = get_network_host(request)
    qr_url = f"http://{server_ip}{reverse('asset_detail1', args=[asset.pk])}"

    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    response = HttpResponse(buffer, content_type="image/png")
    response["Content-Disposition"] = f'attachment; filename="asset_{asset.pk}_qr.png"'
    return response


def asset_pdf(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    assignments = Assignment.objects.filter(asset=asset)
    template_path = 'asset_app/asset_pdf.html'
    context = {'asset': asset, 'assignments': assignments}

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="asset_{asset.asset_id}.pdf"'

    template = render(request, template_path, context)
    pisa_status = pisa.CreatePDF(template.content, dest=response)
    if pisa_status.err:
        return HttpResponse('Error generating PDF')
    return response


# ------------------- REQUEST / PROCUREMENT -------------------
@login_required
def create_procurement_request(request):
    if request.method == 'POST':
        asset_type = request.POST.get('asset_type')
        description = request.POST.get('description')

        ProcurementRequestWorkflow.objects.create(
            asset_type=asset_type,
            description=description,
            requested_by=request.user,
            status="Pending Manager Approval"
        )

        requester = _employee_display_name(request.user)
        _notify_admins(
            'procurement',
            f"New procurement request: {asset_type}",
            f"{requester} raised a procurement request for {asset_type}.",
            reverse('procurement_list'),
        )

        messages.success(request, "Procurement request submitted!")
        return redirect('procurement_list')

    return render(request, 'asset_app/create_procurement.html')


@login_required
def manager_approve(request, pk):
    req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
    if not (request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin', 'manager')):
        messages.error(request, "Only a manager or admin can approve requests.")
        return redirect("procurement_list")
    if req.status != "Pending Manager Approval":
        messages.error(request, f"Request {req.asset_type} is not waiting for manager approval.")
        return redirect("procurement_list")
    req.status = "Pending Admin Approval"
    req.save()
    messages.success(request, f"Request {req.asset_type} approved by manager. Awaiting admin approval.")
    return redirect("procurement_list")


@login_required
def manager_reject(request, pk):
    req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
    if not (request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin', 'manager')):
        messages.error(request, "Only a manager or admin can reject requests.")
        return redirect("procurement_list")
    if req.status != "Pending Manager Approval":
        messages.error(request, f"Request {req.asset_type} is not waiting for manager approval.")
        return redirect("procurement_list")
    req.status = "Rejected by Manager"
    req.save()
    messages.info(request, f"Request {req.asset_type} rejected by manager.")
    return redirect("procurement_list")


@login_required
def admin_approve(request, pk):
    req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
    if not (request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')):
        messages.error(request, "Only an admin can approve requests.")
        return redirect("procurement_list")
    if req.status != "Pending Admin Approval":
        messages.error(request, f"Request {req.asset_type} is not waiting for admin approval.")
        return redirect("procurement_list")
    req.status = "Pending Super Admin Approval"
    req.save()
    messages.success(request, f"Request {req.asset_type} approved by admin. Awaiting super admin approval.")
    return redirect("procurement_list")


@login_required
def admin_reject(request, pk):
    req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
    if not (request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')):
        messages.error(request, "Only an admin can reject requests.")
        return redirect("procurement_list")
    if req.status != "Pending Admin Approval":
        messages.error(request, f"Request {req.asset_type} is not waiting for admin approval.")
        return redirect("procurement_list")
    req.status = "Rejected by Admin"
    req.save()
    messages.info(request, f"Request {req.asset_type} rejected by admin.")
    return redirect("procurement_list")


@login_required
def superadmin_approve(request, pk):
    req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
    if not (getattr(request.user, 'role', '') == 'superadmin'):
        messages.error(request, "Only a super admin can finalize this approval.")
        return redirect("procurement_list")
    if req.status != "Pending Super Admin Approval":
        messages.error(request, f"Request {req.asset_type} is not waiting for super admin approval.")
        return redirect("procurement_list")
    req.status = "Completed"
    req.completed_date = timezone.now()
    req.save()
    messages.success(request, f"Request {req.asset_type} finally approved by Super Admin and completed.")
    return redirect("procurement_list")


@login_required
def superadmin_reject(request, pk):
    req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
    if not (getattr(request.user, 'role', '') == 'superadmin'):
        messages.error(request, "Only a super admin can reject at this stage.")
        return redirect("procurement_list")
    if req.status != "Pending Super Admin Approval":
        messages.error(request, f"Request {req.asset_type} is not waiting for super admin approval.")
        return redirect("procurement_list")
    req.status = "Rejected by Super Admin"
    req.save()
    messages.info(request, f"Request {req.asset_type} rejected by Super Admin.")
    return redirect("procurement_list")


@login_required
def purchase_approve(request, pk):
    req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
    req.status = "Invoice Pending"
    req.save()
    return redirect("procurement_list")


@login_required
def purchase_reject(request, pk):
    req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
    req.status = "Rejected by Purchase Manager"
    req.save()
    return redirect("procurement_list")


@login_required
def accounts_approve(request, pk):
    req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
    req.status = "Completed"
    req.payment_status = "Paid"
    req.completed_date = timezone.now()
    req.save()
    return redirect('procurement_list')


@login_required
def accounts_reject(request, pk):
    req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
    req.status = "Rejected by Accounts Manager"
    req.save()
    return redirect("procurement_list")


@login_required
def payment_done(request, pk):
    req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
    req.payment_status = "Paid"
    req.status = "Completed"
    req.save()
    messages.success(request, "Payment completed!")
    return redirect('procurement_list')


@login_required
def upload_invoice(request, pk):
    req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
    if request.method == "POST":
        if request.FILES.get("invoice_file1"):
            req.invoice_file1 = request.FILES["invoice_file1"]
        if request.FILES.get("invoice_file2"):
            req.invoice_file2 = request.FILES["invoice_file2"]
        if request.FILES.get("invoice_file3"):
            req.invoice_file3 = request.FILES["invoice_file3"]

        req.status = "Payment Pending"
        req.save()
        return redirect("procurement_list")

    return render(request, "asset_app/upload_invoice.html", {"req": req})


@login_required
def procurement_list(request):
    user = request.user

    if user.is_staff or getattr(user, 'role', None) in ('admin', 'superadmin', 'asset_admin'):
        requests = ProcurementRequestWorkflow.objects.all().order_by('-id')
    elif getattr(user, 'role', None) == "manager":
        requests = ProcurementRequestWorkflow.objects.filter(
            _department_user_q(user.department, 'requested_by'),
            status__in=[
                "Pending Manager Approval",
                "Pending Admin Approval",
                "Rejected by Manager",
                "Rejected by Admin",
                "Completed",
            ]
        ).order_by('-id')
    else:
        requests = ProcurementRequestWorkflow.objects.filter(requested_by=user).order_by('-id')

    return render(request, "asset_app/procurement_list.html", {"requests": requests})

@login_required
def delete_procurement(request, pk):
    if request.user.is_superuser or request.user.is_staff or getattr(request.user, 'role', '') in ['admin', 'asset_admin']:
        req = get_object_or_404(ProcurementRequestWorkflow, pk=pk)
        req.delete()
        messages.success(request, "Procurement request deleted successfully.")
    else:
        messages.error(request, "You do not have permission to delete this request.")
    return redirect("procurement_list")


# ------------------- ASSET REQUESTS -------------------
@login_required
def request_asset(request):
    if request.method == 'POST':
        form = AssetRequestForm(request.POST)
        if form.is_valid():
            asset_request = form.save(commit=False)
            asset_request.requested_by = request.user
            asset_request.save()

            requester = _employee_display_name(request.user)
            _notify_admins(
                'asset_request',
                f"New asset request #{asset_request.id}",
                f"{requester} requested {asset_request.quantity} x {asset_request.asset_category}.",
                reverse('view_request', args=[asset_request.id]),
            )

            return redirect('asset_dashboard')
    else:
        form = AssetRequestForm()
    return render(request, 'asset_app/request_asset.html', {'form': form})


def request_detail(request, pk):
    asset_request = get_object_or_404(AssetRequest, pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        asset_request.status = new_status
        asset_request.save()
        return redirect('asset_dashboard')
    return render(request, 'asset_app/request_detail.html', {'asset_request': asset_request})


@login_required
def view_requests_list(request):
    if request.user.is_staff or getattr(request.user, 'role', '') == 'superadmin':
        requests = AssetRequest.objects.select_related('requested_by').all()
    elif getattr(request.user, 'role', '') == 'manager':
        requests = AssetRequest.objects.select_related('requested_by').filter(
            _department_user_q(request.user.department, 'requested_by')
        )
    else:
        requests = AssetRequest.objects.select_related('requested_by').filter(requested_by=request.user)

    status_counts = {
        'total': requests.count(),
        'pending': requests.filter(status__iexact='Pending').count(),
        'approved': requests.filter(status__iexact='Approved').count(),
        'rejected': requests.filter(status__iexact='Rejected').count(),
    }
    return render(request, 'asset_app/view_requests_list.html', {
        'requests': requests,
        'status_counts': status_counts,
    })


def view_request(request, pk):
    asset_request = get_object_or_404(AssetRequest, pk=pk)
    # Get available assets matching the requested category
    available_assets = Asset.objects.filter(
        asset_type=asset_request.asset_category, 
        status__iexact='Available'
    )
    return render(request, 'asset_app/view_request.html', {
        'asset_request': asset_request,
        'available_assets': available_assets
    })


def update_request_status(request, pk):
    asset_request = get_object_or_404(AssetRequest, pk=pk)
    if request.method == "POST":
        new_status = request.POST.get("status")
        
        if new_status == "Approved":
            assigned_asset_ids = request.POST.getlist("assigned_assets")
            if not assigned_asset_ids:
                messages.error(request, "You must select an asset to approve the request.")
                return redirect('view_request', pk=pk)
                
            # Find the Employee profile for this user by name matching username
            emp = Employee.objects.filter(name__iexact=asset_request.requested_by.username).first()
            if not emp:
                messages.error(request, "Employee profile not found for this user. Please ensure an Employee with this username exists.")
                return redirect('view_request', pk=pk)
                
            # Assign assets
            for asset_id in assigned_asset_ids:
                asset = get_object_or_404(Asset, id=asset_id)
                Assignment.objects.create(asset=asset, employee=emp, status='In Use')
                asset.status = 'In Use'
                asset.save()
                
        asset_request.status = new_status
        asset_request.save()
        messages.success(request, f"Request {asset_request.id} marked as {new_status}.")
        return redirect('view_requests_list')
        
    return redirect('view_request', pk=pk)


# ------------------- DELETE / PUBLIC -------------------
@login_required
def delete_asset(request, pk):
    is_admin = request.user.is_staff or request.user.is_superuser or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
    if not is_admin:
        messages.error(request, "Only Admins and Super Admins can delete assets.")
        return redirect('view_assets')
        
    asset = get_object_or_404(Asset, pk=pk)
    asset_id_display = asset.asset_id
    
    try:
        from django.db import transaction
        with transaction.atomic():
            # Delete related records via Django ORM
            Assignment.objects.filter(asset=asset).delete()
            ReturnRequest.objects.filter(asset=asset).delete()
            Ticket.objects.filter(asset=asset).delete()
            AssetHistory.objects.filter(asset=asset).delete()

            # Dynamically delete maintenance records if models exist
            try:
                from .models import MaintenancePlan
                MaintenancePlan.objects.filter(asset=asset).delete()
            except (ImportError, Exception):
                pass

            try:
                from .models import MaintenanceRecord
                MaintenanceRecord.objects.filter(asset=asset).delete()
            except (ImportError, Exception):
                pass

            # Log asset deletion before removing from database
            try:
                from .models import AssetDeletionLog
                AssetDeletionLog.objects.create(
                    asset_id=asset.asset_id,
                    asset_type=asset.asset_type,
                    asset_name=asset.name,
                    deleted_by=request.user,
                )
            except Exception:
                pass

            asset.delete()
        messages.success(request, f"Asset {asset_id_display} deleted successfully.")
    except Exception as e:
        messages.error(request, f"Could not delete asset {asset_id_display}: {e}")
        
    return redirect('view_assets')


def public_asset_detail(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    assignments = Assignment.objects.filter(asset=asset).select_related("employee")
    return render(request, 'asset_app/public_asset_detail.html', {
        'asset': asset,
        'assignments': assignments,
        'qr_base64': None,
    })


# ------------------- TICKETS -------------------
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone

# -------------------
# VIEW ALL TICKETS
# -------------------
@login_required
def view_tickets(request):
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
    is_manager = getattr(request.user, 'role', '') == 'manager'
    is_network_support = request.user.groups.filter(name='Network Support').exists() or 'Network' in (request.user.department or '')

    if is_admin:
        tickets = Ticket.objects.all().order_by('-created_at')
    elif is_manager:
        tickets = Ticket.objects.filter(
            _department_user_q(request.user.department)
        ).order_by('-created_at')
    elif is_network_support:
        tickets = Ticket.objects.filter(
            Q(assigned_to=request.user) |
            (Q(department__icontains='Network') & Q(assigned_to__isnull=True)) |
            Q(created_by=request.user)
        ).distinct().order_by('-created_at')
    else:
        tickets = Ticket.objects.filter(created_by=request.user).order_by('-created_at')

    form = TicketForm()

    # Limit assets user can select
    if 'asset' in form.fields:
        if request.user.is_staff or getattr(request.user, 'role', '') == 'superadmin':
            form.fields['asset'].queryset = Asset.objects.all()
        elif getattr(request.user, 'role', '') == 'manager':
            assigned_asset_ids = Assignment.objects.filter(
                employee__department__iexact=request.user.department
            ).values_list('asset_id', flat=True)
            form.fields['asset'].queryset = Asset.objects.filter(id__in=assigned_asset_ids)
        else:
            assigned_asset_ids = Assignment.objects.filter(
                Q(employee__employee_id__iexact=request.user.username) | Q(employee__name__iexact=request.user.username),
                status__iexact='In Use'
            ).values_list('asset_id', flat=True)
            form.fields['asset'].queryset = Asset.objects.filter(id__in=assigned_asset_ids)

    # Map each ticket creator to their real employee name (fall back to username)
    tickets = list(tickets)
    for t in tickets:
        t.display_name = _employee_display_name(t.created_by)

    status_counts = {'total': len(tickets), 'open': 0, 'pending': 0, 'resolved': 0, 'closed': 0}
    for t in tickets:
        key = (t.status or '').strip().lower()
        if key in status_counts:
            status_counts[key] += 1

    return render(request, 'asset_app/view_tickets.html', {
        'tickets': tickets,
        'form': form,
        'is_network_support': is_network_support,
        'is_admin': is_admin,
        'status_counts': status_counts,
    })

@login_required
def download_ticket_report(request):
    import csv
    from django.http import HttpResponse
    
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
    is_manager = getattr(request.user, 'role', '') == 'manager'
    is_network_support = request.user.groups.filter(name='Network Support').exists() or 'Network' in (request.user.department or '')

    if is_admin:
        tickets = Ticket.objects.all().order_by('-created_at')
    elif is_manager:
        tickets = Ticket.objects.filter(
            _department_user_q(request.user.department)
        ).order_by('-created_at')
    elif is_network_support:
        tickets = Ticket.objects.filter(
            Q(assigned_to=request.user) |
            (Q(department__icontains='Network') & Q(assigned_to__isnull=True)) |
            Q(created_by=request.user)
        ).distinct().order_by('-created_at')
    else:
        tickets = Ticket.objects.filter(created_by=request.user).order_by('-created_at')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="ticket_report.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Ticket ID', 'Subject', 'Status', 'Department', 'Raised By', 'Created On', 'Solver (Assigned To)'])
    
    for ticket in tickets:
        raised_by = _employee_display_name(ticket.created_by) if ticket.created_by else 'System'
        assigned_to = ticket.assigned_to.display_name if ticket.assigned_to else 'Unassigned'
        created_on = ticket.created_at.strftime('%b %d, %Y') if ticket.created_at else ''
        
        writer.writerow([
            f'#{ticket.id}',
            ticket.subject,
            ticket.status,
            ticket.department,
            raised_by,
            created_on,
            assigned_to
        ])
        
    return response


# -------------------
# RAISE NEW TICKET  whatapp
# -------------------
def _send_whatsapp_notification(ticket):
    """
    Sends a WhatsApp message when a ticket is created using the Infinity API.
    """
    from .whatsapp_utils import send_whatsapp_message
    from .views import _employee_display_name
    
    # User requested a specific phone number to be provided later.
    # For now, we will use a dummy number or can read from settings if available.
    contact_numbers = ["919666516314", "917396758875"]
    
    template_id = "1802469"
    
    # Format the 6 variables exactly as requested:
    # {1} Ticket ID
    # {2} Asset ID
    # {3} Issue Description
    # {4} Raised By
    # {5} Department
    
    
    raised_by = _employee_display_name(ticket.created_by) if ticket.created_by else "System"
    
    template_params = [
        f"TKT-{ticket.id:03d}",
        ticket.asset.asset_id if ticket.asset else "N/A",
        ticket.subject[:50], # Shorten subject if it's too long
        raised_by,
        ticket.department or "IT Support",
        "Open"
    ]
    
    for number in contact_numbers:
        try:
            send_whatsapp_message(number, template_id, template_params)
        except Exception as e:
            print(f"Failed to send WhatsApp message to {number}: {e}")

def raise_ticket(request):
    # Determine which assets user can see
    if request.user.is_staff or getattr(request.user, 'role', '') == 'superadmin':
        user_assets = Asset.objects.all()
    elif getattr(request.user, 'role', '') == 'manager':
        assigned_asset_ids = Assignment.objects.filter(
            employee__department__iexact=request.user.department
        ).values_list('asset_id', flat=True)
        user_assets = Asset.objects.filter(id__in=assigned_asset_ids)
    else:
        assigned_asset_ids = Assignment.objects.filter(
            Q(employee__employee_id__iexact=request.user.username) | Q(employee__name__iexact=request.user.username),
            status__iexact='In Use'
        ).values_list('asset_id', flat=True)
        user_assets = Asset.objects.filter(id__in=assigned_asset_ids)

    if request.method == 'POST':
        form = TicketForm(request.POST)
        form.fields['asset'].queryset = user_assets

        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.created_by = request.user
            if not getattr(ticket, 'created_at', None):
                ticket.created_at = timezone.now()
            if not getattr(ticket, 'status', None):
                ticket.status = "Open"
            
            ticket.save()

            requester = _employee_display_name(request.user)
            _notify_admins(
                'ticket',
                f"New ticket: {ticket.subject}",
                f"{requester} raised a ticket for {ticket.asset.asset_id}.",
                reverse('ticket_detail', args=[ticket.id]),
            )
            
            # TRIGGER WHATSAPP MESSAGE
            _send_whatsapp_notification(ticket)

            messages.success(request, "✅ Ticket raised successfully!")
            return redirect('view_tickets')   # 🔁 SIMPLE REDIRECT
        else:
            messages.error(request, f"❌ Failed to raise ticket. Please check your inputs: {form.errors.as_text()}")

    return redirect('view_tickets')


# -------------------
# UPDATE TICKET STATUS
# -------------------
@login_required
def update_ticket_status(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
    is_manager = getattr(request.user, 'role', '') == 'manager'
    if not (is_admin or is_manager):
        messages.error(request, "Only an admin or manager can update ticket status.")
        return redirect('view_tickets')

    if ticket.status.lower() == "pending":
        ticket.status = "Resolved"
    elif ticket.status.lower() == "resolved":
        ticket.status = "Closed"
    else:
        ticket.status = "Pending"

    ticket.save()
    messages.success(request, f"Ticket status updated to {ticket.status}.")
    return redirect('view_tickets')


# -------------------
# EMPLOYEE CONFIRM: TICKET IS SOLVED
# -------------------
@login_required
def ticket_confirm_solved(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
    is_owner = ticket.created_by == request.user

    if not (is_admin or is_owner):
        messages.error(request, "Only the employee who raised the ticket or an admin can confirm it.")
        return redirect('ticket_detail', pk=ticket.pk)

    if ticket.status.lower() != "resolved":
        messages.info(request, "This ticket is not awaiting employee confirmation.")
        return redirect('ticket_detail', pk=ticket.pk)

    ticket.status = "Closed"
    ticket.save()

    requester = _employee_display_name(
        request.user if is_owner else ticket.created_by
    )
    if is_owner:
        _notify_admins(
            'ticket',
            f"Ticket closed: {ticket.subject}",
            f"{requester} confirmed the issue is solved.",
            reverse('ticket_detail', args=[ticket.id]),
        )
        messages.success(request, "✅ Confirmed! Ticket is now Closed.")
    else:
        messages.success(request, f"✅ Ticket marked as Closed (confirmed by admin for {requester}).")
    return redirect('ticket_detail', pk=ticket.pk)

@login_required
def delete_ticket(request, pk):
    is_superadmin = getattr(request.user, 'role', '') == 'superadmin'
    if not is_superadmin:
        messages.error(request, "Only Super Admin can delete tickets.")
        return redirect('view_tickets')
        
    ticket = get_object_or_404(Ticket, pk=pk)
    
    if request.method == 'POST':
        ticket_id = ticket.id
        ticket.delete()
        messages.success(request, f"Ticket #{ticket_id} deleted successfully.")
        return redirect('view_tickets')
        
    return redirect('ticket_detail', pk=pk)


# -------------------
# EMPLOYEE REOPEN: TICKET NOT SOLVED
# -------------------
@login_required
def ticket_reopen(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
    is_owner = ticket.created_by == request.user

    if not (is_admin or is_owner):
        messages.error(request, "Only the employee who raised the ticket or an admin can reopen it.")
        return redirect('ticket_detail', pk=ticket.pk)

    if ticket.status.lower() != "resolved":
        messages.info(request, "Only a Resolved ticket can be reopened.")
        return redirect('ticket_detail', pk=ticket.pk)

    reopen_note = request.POST.get('reopen_note', '').strip()
    
    if not reopen_note:
        messages.error(request, "A reason for reopening is required.")
        return redirect('ticket_detail', pk=ticket.pk)
        
    ticket.status = "Pending"
    existing_msg = ticket.resolution_message or ""
    ticket.resolution_message = f"{existing_msg}\n\n--- Ticket Reopened ---\nReason: {reopen_note}".strip()
    ticket.save()

    requester = _employee_display_name(
        request.user if is_owner else ticket.created_by
    )
    if is_owner:
        notify_text = f"{requester} reported the issue is NOT yet solved."
        if reopen_note:
            notify_text += f"\nReason: {reopen_note}"
            
        _notify_admins(
            'ticket',
            f"Ticket reopened: {ticket.subject}",
            notify_text,
            reverse('ticket_detail', args=[ticket.id]),
        )
        messages.warning(request, "↩️ Ticket reopened as Pending. The admin team has been notified.")
    else:
        messages.warning(request, f"↩️ Ticket reopened as Pending on behalf of {requester}.")
    return redirect('ticket_detail', pk=ticket.pk)


# -------------------
# TICKET DETAIL PAGE
# -------------------
@login_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)

    if request.method == 'POST':
        # Check if the user is accepting the ticket
        if request.POST.get('action') == 'accept':
            is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
            ticket_dept = ticket.department or 'Network'
            is_network_support = request.user.groups.filter(name='Network Support').exists() or ticket_dept in (request.user.department or '')
            
            if (is_network_support or is_admin) and not ticket.assigned_to:
                ticket.assigned_to = request.user
                if ticket.status.lower() == 'open':
                    ticket.status = 'Pending'
                ticket.save()
                messages.success(request, f'✅ You have accepted this ticket!')
            else:
                messages.error(request, 'You cannot accept this ticket.')
            return redirect(request.META.get('HTTP_REFERER', reverse('ticket_detail', args=[ticket.pk])))

        # Handle feedback submission
        feedback = request.POST.get('feedback')
        if feedback and ticket.status.lower() == 'closed' and request.user == ticket.created_by:
            ticket.feedback = feedback
            ticket.save()
            messages.success(request, '✅ Thank you! Your feedback has been submitted successfully.')
            return redirect(request.META.get('HTTP_REFERER', reverse('ticket_detail', args=[ticket.pk])))

        # Handle status update
        is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
        is_manager = getattr(request.user, 'role', '') == 'manager'
        # The user is considered network support if they are in the group or match department
        ticket_dept = ticket.department or 'Network'
        is_network_support = request.user.groups.filter(name='Network Support').exists() or ticket_dept in (request.user.department or '')
        
        # Determine if they have permission to update THIS ticket
        can_update = False
        if is_admin or is_manager:
            can_update = True
        elif is_network_support:
            # Network support can only update if they accepted/are assigned to the ticket
            if ticket.assigned_to == request.user:
                can_update = True
                
        if not can_update:
            messages.error(request, "Only the person who accepted the ticket (or an admin) can update its status.")
            return redirect(request.META.get('HTTP_REFERER', reverse('ticket_detail', args=[ticket.pk])))
            
        new_status = request.POST.get('status')
        resolution_message = request.POST.get('resolution_message')
        assigned_to_id = request.POST.get('assigned_to')

        if new_status:
            # Capitalize to match backend conventions (Pending, Resolved, Closed, Open)
            new_status = new_status.capitalize()
            
            status_changed = (new_status != ticket.status)
            res_changed = (resolution_message is not None and resolution_message.strip() != (ticket.resolution_message or ""))
            
            assigned_to_compare = 'unassigned' if assigned_to_id == 'unassigned' else str(assigned_to_id)
            current_assigned = str(ticket.assigned_to_id) if ticket.assigned_to_id else 'unassigned'
            assigned_changed = (assigned_to_id and assigned_to_compare != current_assigned)

            if status_changed or res_changed or assigned_changed:
                if status_changed:
                    ticket.status = new_status
                if res_changed and resolution_message and resolution_message.strip():
                    new_note = resolution_message.strip()
                    existing_msg = (ticket.resolution_message or "").strip()
                    if existing_msg:
                        if new_note not in existing_msg:
                            ticket.resolution_message = f"{existing_msg}\n\n--- Resolution Update ---\n{new_note}"
                    else:
                        ticket.resolution_message = new_note
                if assigned_changed:
                    ticket.assigned_to_id = assigned_to_id if assigned_to_id != 'unassigned' else None
                
                ticket.save()
                messages.success(request, '✅ Ticket updated successfully!')
            else:
                messages.info(request, f'No changes made to the ticket.')
            return redirect(request.META.get('HTTP_REFERER', reverse('ticket_detail', args=[ticket.pk])))

    from django.contrib.auth import get_user_model
    User = get_user_model()
    from django.db.models import Q
    
    # Filter assignable users based on the ticket's department, falling back/including Network
    ticket_dept = ticket.department or 'Network'
    from asset_app.models import Employee
    network_employee_ids = Employee.objects.filter(department__icontains=ticket_dept).values_list('employee_id', flat=True)
    fallback_network_ids = Employee.objects.filter(department__icontains='Network').values_list('employee_id', flat=True)
    
    admin_users = User.objects.filter(
        Q(groups__name='Network Support') | 
        Q(department__icontains=ticket_dept) |
        Q(department__icontains='Network') |
        Q(username__in=network_employee_ids) |
        Q(username__in=fallback_network_ids)
    ).distinct()
    
    is_network_support = request.user.groups.filter(name='Network Support').exists() or ticket_dept in (request.user.department or '')
    
    base_template = 'asset_app/ajax_base.html' if request.headers.get('x-requested-with') == 'XMLHttpRequest' else 'asset_app/base.html'

    context = {
        'ticket': ticket, 
        'display_name': _employee_display_name(ticket.created_by),
        'admin_users': admin_users,
        'is_network_support': is_network_support,
        'base_template': base_template,
        'is_ajax': request.headers.get('x-requested-with') == 'XMLHttpRequest'
    }
    return render(request, 'asset_app/ticket_detail.html', context)


@login_required
def network_support_team(request):
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
    if not is_admin:
        messages.error(request, "Access denied.")
        return redirect('asset_dashboard')
        
    from django.contrib.auth.models import Group
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    group, created = Group.objects.get_or_create(name='Network Support')
    if created:
        for username in ['1032', '339', '1004']:
            try:
                user = User.objects.get(username=username)
                user.groups.add(group)
            except User.DoesNotExist:
                pass

    if request.method == 'POST':
        action = request.POST.get('action')
        user_id = request.POST.get('user_id')
        if user_id:
            try:
                target_user = User.objects.get(id=user_id)
                if action == 'add':
                    target_user.groups.add(group)
                    messages.success(request, f'Added {target_user.display_name} to Network Support.')
                elif action == 'remove':
                    target_user.groups.remove(group)
                    messages.success(request, f'Removed {target_user.display_name} from Network Support.')
            except User.DoesNotExist:
                messages.error(request, 'User not found.')
        return redirect('network_support_team')

    team_members = group.user_set.all()
    all_users = User.objects.exclude(id__in=team_members.values_list('id', flat=True)).filter(department__icontains='Network')
    
    return render(request, 'asset_app/network_support_team.html', {
        'team_members': team_members,
        'all_users': all_users
    })



@login_required
def support_reports(request):
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin', 'manager')
    is_network = request.user.groups.filter(name='Network Support').exists() or 'Network' in (request.user.department or '')
    
    if not (is_admin or is_network):
        messages.error(request, "Access denied.")
        return redirect('asset_dashboard')
        
    from django.db.models import Count, Q, Prefetch
    from django.contrib.auth import get_user_model
    from .models import Ticket, Employee, Notification
    
    User = get_user_model()
    
    # Fetch tickets that are resolved or closed
    resolved_tickets = Ticket.objects.filter(Q(status__icontains='resolv') | Q(status__icontains='clos'))
    
    # Fetch manual work reports
    manual_reports = Notification.objects.filter(notification_type='work_report').filter(
            Q(recipient__groups__name__icontains='Network') |
            Q(recipient__username__in=Employee.objects.filter(department__icontains='Network').values_list('employee_id', flat=True))
        ).order_by('-created_at')
    
    # Only fetch users who are in the Network department or Network Support group, excluding superadmins and staff
    team_members = User.objects.filter(
        Q(groups__name__icontains='Network') |
        Q(department__icontains='Network') |
        Q(username__in=Employee.objects.filter(department__icontains='Network').values('employee_id'))
    ).exclude(
        Q(role__in=['superadmin', 'admin', 'manager']) | Q(is_superuser=True) | Q(is_staff=True)
    ).distinct().annotate(
        resolved_count=Count('assigned_tickets', filter=Q(assigned_tickets__status__icontains='resolv') | Q(assigned_tickets__status__icontains='clos')),
        manual_report_count=Count('notifications', filter=Q(notifications__notification_type='work_report'))
    ).prefetch_related(
        Prefetch('assigned_tickets', queryset=resolved_tickets, to_attr='resolved_ticket_list'),
        Prefetch('notifications', queryset=manual_reports, to_attr='manual_report_list')
    )
        
    if not is_admin:
        team_members = team_members.filter(id=request.user.id)
        
    return render(request, 'asset_app/support_reports.html', {'team_members': team_members, 'is_admin': is_admin})

@login_required
def download_support_report(request):
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin', 'manager')
    if not is_admin:
        messages.error(request, "Access denied.")
        return redirect('asset_dashboard')
        
    import csv
    from django.http import HttpResponse
    from django.db.models import Q
    from django.contrib.auth.models import Group
    from .models import Ticket

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="network_support_report.csv"'

    writer = csv.writer(response)
    writer.writerow(['Ticket ID', 'Subject', 'Status', 'Reported On', 'Assigned To', 'Resolution Notes'])

    group = Group.objects.filter(name='Network Support').first()
    if group:
        team_members = group.user_set.all()
        for member in team_members:
            resolved_tickets = Ticket.objects.filter(
                assigned_to=member
            ).filter(Q(status__icontains='resolv') | Q(status__icontains='clos'))
            
            for ticket in resolved_tickets:
                writer.writerow([
                    ticket.id,
                    ticket.subject,
                    ticket.status,
                    ticket.created_at.strftime("%Y-%m-%d %H:%M"),
                    member.display_name,
                    ticket.resolution_message or 'None'
                ])

    return response

# ------------------- PUBLIC ASSET DETAIdef asset_detail1(request, pk):-------
def asset_detail1(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    asset_history = Assignment.objects.filter(asset=asset).select_related("employee").order_by("-id")

    return render(request, "asset_app/asset_detail1.html", {
        "asset": asset,
        "asset_history": asset_history,
    })
@login_required
def activity_log(request):
    is_superadmin = getattr(request.user, 'role', '') == 'superadmin'
    if not is_superadmin:
        messages.error(request, "Access denied. Only Super Admin can view the Activity Log.")
        return redirect('asset_dashboard')
        
    from .models import Assignment, ReturnRequest, ProcurementRequestWorkflow, Notification
    
    # Gather recent activities
    recent_assignments = Assignment.objects.all().select_related('asset', 'employee', 'assigned_by').order_by('-assigned_at')[:30]
    recent_returns = ReturnRequest.objects.exclude(status='Pending').select_related('asset', 'employee', 'processed_by').order_by('-processed_at')[:30]
    recent_procurements = ProcurementRequestWorkflow.objects.exclude(status='Pending Manager Approval').select_related('requested_by').order_by('-created_at')[:30]
    recent_reports = Notification.objects.filter(notification_type='work_report').select_related('recipient').order_by('-created_at')[:30]
    
    # Combine and sort them
    activities = []
    
    for a in recent_assignments:
        activities.append({
            'type': 'Assignment',
            'icon': 'bi-person-plus',
            'color': '#0d6efd',
            'bg': 'rgba(13,110,253,.12)',
            'title': f"Asset Assigned: {a.asset.asset_id}",
            'message': f"Assigned to {a.employee.name} by {a.assigned_by.username if a.assigned_by else 'System'}.",
            'timestamp': a.assigned_at
        })
        
    for r in recent_returns:
        if r.processed_at:
            activities.append({
                'type': 'Return',
                'icon': 'bi-arrow-return-left',
                'color': '#198754',
                'bg': 'rgba(25,135,84,.12)',
                'title': f"Return {r.get_status_display()}: {r.asset.asset_id}",
                'message': f"Processed by {r.processed_by.username if r.processed_by else 'System'}.",
                'timestamp': r.processed_at
            })
            
    for p in recent_procurements:
        timestamp = p.completed_date if p.completed_date else p.created_at
        activities.append({
            'type': 'Procurement',
            'icon': 'bi-cart-check',
            'color': '#6f42c1',
            'bg': 'rgba(111,66,193,.12)',
            'title': f"Procurement: {p.asset_type}",
            'message': f"Status: {p.status}. Requested by {p.requested_by.username}.",
            'timestamp': timestamp
        })
        
    for w in recent_reports:
        activities.append({
            'type': 'Work Report',
            'icon': 'bi-journal-check',
            'color': '#0dcaf0',
            'bg': 'rgba(13,202,240,.12)',
            'title': f"Work Report: {w.title}",
            'message': f"Submitted by {w.recipient.username if w.recipient else 'Unknown'}.",
            'timestamp': w.created_at
        })
        
    activities.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return render(request, 'asset_app/activity_log.html', {
        'activities': activities[:50]
    })


def is_network_member(user):
    from asset_app.models import Employee
        
    # Check if they are in the Network Support group
    if user.groups.filter(name__icontains='Network').exists():
        return True
        
    # Check if their employee record is in the Network department
    if Employee.objects.filter(employee_id=user.username, department__icontains='Network').exists():
        return True
        
    # Everyone else (including superadmin, admin, manager, user) gets denied
    return False

@login_required
def submit_work_report(request):
    if not is_network_member(request.user):
        messages.error(request, "Access Denied: Only Network Department can submit work reports.")
        return redirect('asset_dashboard')
        
    if request.method == 'POST':
        title = request.POST.get('title', 'Work Report')
        description = request.POST.get('description', '')
        
        file_url = ""
        if 'excel_file' in request.FILES:
            from django.core.files.storage import default_storage
            excel_file = request.FILES['excel_file']
            file_name = default_storage.save(f"work_reports/{excel_file.name}", excel_file)
            file_url = default_storage.url(file_name)
        
        # Save as a Notification to avoid DB migration errors
        from .models import Notification
        Notification.objects.create(
            recipient=request.user,
            notification_type='work_report',
            title=title,
            message=description,
            link=file_url,
            is_read=True  # Mark true so it doesn't clutter their real notifications
        )
        messages.success(request, 'Work report submitted successfully!')
        return redirect('my_work_reports')
        
    return redirect('my_work_reports')


@login_required
def my_work_reports(request):
    if not is_network_member(request.user):
        messages.error(request, "Access Denied: Only Network Department can view work reports.")
        return redirect('asset_dashboard')
        
    from .models import Notification
    
    # Superadmins can see all reports, others see their own
    if request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin'):
        reports = Notification.objects.filter(notification_type='work_report').filter(
            Q(recipient__groups__name__icontains='Network') |
            Q(recipient__username__in=Employee.objects.filter(department__icontains='Network').values_list('employee_id', flat=True))
        ).order_by('-created_at')
    else:
        reports = Notification.objects.filter(
            recipient=request.user,
            notification_type='work_report'
        ).order_by('-created_at')

    now = timezone.now()
    stats = {
        'total': reports.count(),
        'this_month': reports.filter(created_at__year=now.year, created_at__month=now.month).count(),
        'with_files': reports.exclude(link='').exclude(link__isnull=True).count(),
    }

    return render(request, 'asset_app/my_work_reports.html', {'reports': reports, 'stats': stats})

@login_required
def download_manual_reports(request):
    if not is_network_member(request.user):
        messages.error(request, "Access Denied.")
        return redirect('asset_dashboard')
        
    import csv
    from django.http import HttpResponse
    from .models import Notification
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="manual_work_reports.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Date', 'Submitted By', 'Title', 'Description'])
    
    if request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin'):
        reports = Notification.objects.filter(notification_type='work_report').filter(
            Q(recipient__groups__name__icontains='Network') |
            Q(recipient__username__in=Employee.objects.filter(department__icontains='Network').values_list('employee_id', flat=True))
        ).order_by('-created_at')
    else:
        reports = Notification.objects.filter(recipient=request.user, notification_type='work_report').order_by('-created_at')
        
    for report in reports:
        writer.writerow([
            report.created_at.strftime("%Y-%m-%d %H:%M"),
            report.recipient.username if report.recipient else 'Unknown',
            report.title,
            report.message
        ])
        
    return response

@login_required
def edit_return_request(request, pk):
    is_superadmin = getattr(request.user, 'role', '') == 'superadmin'
    if not is_superadmin:
        messages.error(request, "Only Super Admin can edit return requests.")
        return redirect('return_requests')
        
    from .models import ReturnRequest
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    if request.method == 'POST':
        status = request.POST.get('status')
        reason = request.POST.get('reason')
        
        if status:
            return_request.status = status
    return response

# ------------------- PUBLIC ASSET DETAIdef asset_detail1(request, pk):-------
def asset_detail1(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    asset_history = Assignment.objects.filter(asset=asset).select_related("employee").order_by("-id")

    return render(request, "asset_app/asset_detail1.html", {
        "asset": asset,
        "asset_history": asset_history,
    })
@login_required
def activity_log(request):
    is_superadmin = getattr(request.user, 'role', '') == 'superadmin'
    if not is_superadmin:
        messages.error(request, "Access denied. Only Super Admin can view the Activity Log.")
        return redirect('asset_dashboard')
        
    from .models import Assignment, ReturnRequest, ProcurementRequestWorkflow, Notification, Asset, AssetHistory, AssetDeletionLog
    
    # Gather recent activities
    recent_assignments = Assignment.objects.all().select_related('asset', 'employee', 'assigned_by').order_by('-assigned_at')[:30]
    recent_returns = ReturnRequest.objects.exclude(status='Pending').select_related('asset', 'employee', 'processed_by').order_by('-processed_at')[:30]
    recent_procurements = ProcurementRequestWorkflow.objects.exclude(status='Pending Manager Approval').select_related('requested_by').order_by('-created_at')[:30]
    recent_reports = Notification.objects.filter(notification_type='work_report').select_related('recipient').order_by('-created_at')[:30]
    recent_assets = Asset.objects.all().order_by('-created_at')[:30]
    recent_edits = AssetHistory.objects.select_related('asset', 'edited_by').order_by('-edited_at')[:30]
    recent_deletions = AssetDeletionLog.objects.select_related('deleted_by').order_by('-deleted_at')[:30]
    
    # Combine and sort them
    activities = []
    
    for a in recent_assignments:
        user_name = (a.assigned_by.get_full_name() or a.assigned_by.username) if a.assigned_by else 'System'
        activities.append({
            'type': 'Assignment',
            'icon': 'bi-person-plus',
            'color': '#0d6efd',
            'bg': 'rgba(13,110,253,.12)',
            'title': f"Asset Assigned: {a.asset.asset_id}",
            'message': f"Assigned to {a.employee.name} by {user_name}.",
            'timestamp': a.assigned_at
        })
        
    for r in recent_returns:
        if r.processed_at:
            user_name = (r.processed_by.get_full_name() or r.processed_by.username) if r.processed_by else 'System'
            activities.append({
                'type': 'Return',
                'icon': 'bi-arrow-return-left',
                'color': '#198754',
                'bg': 'rgba(25,135,84,.12)',
                'title': f"Return {r.get_status_display()}: {r.asset.asset_id}",
                'message': f"Processed by {user_name}.",
                'timestamp': r.processed_at
            })
            
    for p in recent_procurements:
        timestamp = p.completed_date if p.completed_date else p.created_at
        user_name = (p.requested_by.get_full_name() or p.requested_by.username) if p.requested_by else 'System'
        activities.append({
            'type': 'Procurement',
            'icon': 'bi-cart-check',
            'color': '#6f42c1',
            'bg': 'rgba(111,66,193,.12)',
            'title': f"Procurement: {p.asset_type}",
            'message': f"Status: {p.status}. Requested by {user_name}.",
            'timestamp': timestamp
        })
        
    for w in recent_reports:
        user_name = (w.recipient.get_full_name() or w.recipient.username) if w.recipient else 'System'
        activities.append({
            'type': 'Work Report',
            'icon': 'bi-journal-check',
            'color': '#0dcaf0',
            'bg': 'rgba(13,202,240,.12)',
            'title': f"Work Report: {w.title}",
            'message': f"Submitted by {user_name}.",
            'timestamp': w.created_at
        })

    for a in recent_assets:
        activities.append({
            'type': 'Asset Created',
            'icon': 'bi-plus-circle',
            'color': '#10b981',  # green color for additions
            'bg': 'rgba(16,185,129,.12)',
            'title': f"New Asset Added: {a.asset_id}",
            'message': f"Type: {a.asset_type}. Added by System.",
            'timestamp': a.created_at
        })
        
    for h in recent_edits:
        user_name = (h.edited_by.get_full_name() or h.edited_by.username) if h.edited_by else 'System'
        activities.append({
            'type': 'Asset Edited',
            'icon': 'bi-pencil-square',
            'color': '#f59e0b',  # warning/amber color for edits
            'bg': 'rgba(245,158,11,.12)',
            'title': f"Asset Details Edited: {h.asset.asset_id}",
            'message': f"Modified by {user_name}.",
            'timestamp': h.edited_at
        })

    for d in recent_deletions:
        user_name = (d.deleted_by.get_full_name() or d.deleted_by.username) if d.deleted_by else 'System'
        activities.append({
            'type': 'Asset Deleted',
            'icon': 'bi-trash3-fill',
            'color': '#ef4444',  # red color for deletion
            'bg': 'rgba(239,68,68,.12)',
            'title': f"Asset Deleted: {d.asset_id}",
            'message': f"Type: {d.asset_type or 'N/A'}. Deleted by {user_name}.",
            'timestamp': d.deleted_at
        })
        
    activities.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return render(request, 'asset_app/activity_log.html', {
        'activities': activities[:50]
    })


def is_network_member(user):
    from asset_app.models import Employee
        
    # Check if they are in the Network Support group
    if user.groups.filter(name__icontains='Network').exists():
        return True
        
    # Check if their employee record is in the Network department
    if Employee.objects.filter(employee_id=user.username, department__icontains='Network').exists():
        return True
        
    # Everyone else (including superadmin, admin, manager, user) gets denied
    return False

@login_required
def submit_work_report(request):
    if not is_network_member(request.user):
        messages.error(request, "Access Denied: Only Network Department can submit work reports.")
        return redirect('asset_dashboard')
        
    if request.method == 'POST':
        title = request.POST.get('title', 'Work Report')
        description = request.POST.get('description', '')
        
        file_url = ""
        if 'excel_file' in request.FILES:
            from django.core.files.storage import default_storage
            excel_file = request.FILES['excel_file']
            file_name = default_storage.save(f"work_reports/{excel_file.name}", excel_file)
            file_url = default_storage.url(file_name)
        
        # Save as a Notification to avoid DB migration errors
        from .models import Notification
        Notification.objects.create(
            recipient=request.user,
            notification_type='work_report',
            title=title,
            message=description,
            link=file_url,
            is_read=True  # Mark true so it doesn't clutter their real notifications
        )
        messages.success(request, 'Work report submitted successfully!')
        return redirect('my_work_reports')
        
    return redirect('my_work_reports')

@login_required
def edit_work_report(request, pk):
    if not is_network_member(request.user):
        messages.error(request, "Access Denied.")
        return redirect('asset_dashboard')
        
    from .models import Notification
    report = get_object_or_404(Notification, pk=pk, recipient=request.user, notification_type='work_report')
    
    if request.method == 'POST':
        title = request.POST.get('title', '')
        description = request.POST.get('description', '')
        
        if title:
            report.title = title
            report.message = description
            
            if 'excel_file' in request.FILES:
                from django.core.files.storage import default_storage
                excel_file = request.FILES['excel_file']
                file_name = default_storage.save(f"work_reports/{excel_file.name}", excel_file)
                report.link = default_storage.url(file_name)
                
            report.save()
            messages.success(request, 'Work report updated successfully!')
            
    return redirect('my_work_reports')

@login_required
def delete_work_report(request, pk):
    from .models import Notification
    report = get_object_or_404(Notification, pk=pk, notification_type='work_report')
    
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'manager')
    
    if report.recipient == request.user or is_admin:
        report.delete()
        messages.success(request, 'Work report deleted successfully!')
    else:
        messages.error(request, 'You do not have permission to delete this report.')
        
    return redirect(request.META.get('HTTP_REFERER', 'my_work_reports'))


@login_required
def my_work_reports(request):
    if not is_network_member(request.user):
        messages.error(request, "Access Denied: Only Network Department can view work reports.")
        return redirect('asset_dashboard')
        
    from .models import Notification
    
    # Superadmins can see all reports, others see their own
    if request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin'):
        reports = Notification.objects.filter(notification_type='work_report').filter(
            Q(recipient__groups__name__icontains='Network') |
            Q(recipient__username__in=Employee.objects.filter(department__icontains='Network').values_list('employee_id', flat=True))
        ).order_by('-created_at')
    else:
        reports = Notification.objects.filter(
            recipient=request.user,
            notification_type='work_report'
        ).order_by('-created_at')

    now = timezone.now()
    stats = {
        'total': reports.count(),
        'this_month': reports.filter(created_at__year=now.year, created_at__month=now.month).count(),
        'with_files': reports.exclude(link='').exclude(link__isnull=True).count(),
    }

    return render(request, 'asset_app/my_work_reports.html', {'reports': reports, 'stats': stats})

@login_required
def download_manual_reports(request):
    if not is_network_member(request.user):
        messages.error(request, "Access Denied.")
        return redirect('asset_dashboard')
        
    import csv
    from django.http import HttpResponse
    from .models import Notification
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="manual_work_reports.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Date', 'Submitted By', 'Title', 'Description'])
    
    if request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin'):
        reports = Notification.objects.filter(notification_type='work_report').filter(
            Q(recipient__groups__name__icontains='Network') |
            Q(recipient__username__in=Employee.objects.filter(department__icontains='Network').values_list('employee_id', flat=True))
        ).order_by('-created_at')
    else:
        reports = Notification.objects.filter(recipient=request.user, notification_type='work_report').order_by('-created_at')
        
    for report in reports:
        writer.writerow([
            report.created_at.strftime("%Y-%m-%d %H:%M"),
            report.recipient.username if report.recipient else 'Unknown',
            report.title,
            report.message
        ])
        
    return response


@login_required
def edit_return_request(request, pk):
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin')
    if not is_admin:
        messages.error(request, "Only Admins and Super Admins can edit return requests.")
        return redirect('return_requests')
        
    from .models import ReturnRequest
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    if request.method == 'POST':
        status = request.POST.get('status')
        reason = request.POST.get('reason')
        
        if status:
            return_request.status = status
        if reason:
            return_request.reason = reason
            
        return_request.save()
        messages.success(request, f"Return request for {return_request.asset.asset_id} updated successfully.")
        return redirect('return_requests')
        
    return redirect('return_requests')

@login_required
def delete_return_request(request, pk):
    is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
    if not is_admin:
        messages.error(request, "Only Admins can delete return requests.")
        return redirect('return_requests')
        
    from .models import ReturnRequest
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    if request.method == 'POST':
        asset_id = return_request.asset.asset_id
        return_request.delete()
        messages.success(request, f"Return request for {asset_id} deleted successfully.")
        return redirect('return_requests')
        
    return redirect('return_requests')
    return redirect('return_requests')
