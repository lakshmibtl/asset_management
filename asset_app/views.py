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
from django.urls import reverse
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


@login_required
def mark_notifications_read(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    nxt = request.GET.get('next', '')
    if nxt and nxt.startswith('/'):
        return redirect(nxt)
    return redirect('notifications')


@login_required
def mark_notification_read(request, pk):
    Notification.objects.filter(pk=pk, recipient=request.user).update(is_read=True)
    nxt = request.GET.get('next', '')
    if nxt and nxt.startswith('/'):
        return redirect(nxt)
    return redirect('notifications')


# ------------------- USERS -------------------
@login_required(login_url='/login/')
def view_users(request):
    users = User.objects.all().order_by('-id')
    employees = Employee.objects.all().order_by('name')
    emp_name_map = {e.employee_id: e.name for e in employees}
    for u in users:
        u.display_name = u.first_name or emp_name_map.get(u.username) or u.username
    return render(request, 'asset_app/view_users.html', {'users': users, 'employees': employees})

@login_required(login_url='/login/')
def delete_user(request, pk):
    if not (request.user.is_staff or getattr(request.user, 'role', None) == 'superadmin'):
        messages.error(request, "You do not have permission to delete users.")
        return redirect('view_users')
        
    user_to_delete = get_object_or_404(User, pk=pk)
    if user_to_delete.id == request.user.id:
        messages.error(request, "You cannot delete yourself.")
    else:
        username = user_to_delete.username
        user_to_delete.delete()
        messages.success(request, f"User '{username}' deleted successfully.")
        
    return redirect('view_users')


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

    is_staff = request.user.is_staff or getattr(request.user, 'role', '') == 'superadmin'
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
        available_by_type.append(av)
        assigned_by_type.append(ass)
        if av > 0 or ass > 0:
            category_stats.append({
                'type': t,
                'available': av,
                'assigned': ass,
                'total': av + ass
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
    from django.utils import timezone
    
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
        
        'added_this_month': added_this_month,
        'assigned_this_month': assigned_this_month,
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
                    return redirect('assign_asset')
                else:
                    messages.success(request, "Asset added successfully!")
                    return redirect('view_assets')
            except IntegrityError:
                messages.error(request, "Error: Asset ID must be unique.")
    else:
        form = AssetForm()

    return render(request, 'asset_app/add_asset.html', {'form': form})


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
    asset_history = Assignment.objects.filter(asset=asset).select_related("employee").order_by("-id")

    return render(request, "asset_app/asset_detail.html", {
        "asset": asset,
        "qr_base64": qr_base64,
        "current_assignment": current_assignment,
        "asset_history": asset_history,
    })


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
        try:
            assigned_date_obj = datetime.strptime(assigned_date, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            pass
        if assigned_date_obj and assigned_date_obj > timezone.now().date():
            messages.error(request, "Assignment date cannot be in the future.")
            next_url = request.POST.get('next')
            if next_url:
                return redirect(next_url)
            return redirect(reverse('assign_asset'))

        form = AssignmentForm(request.POST)
        if form.is_valid():
            assignment = form.save()
            
            # Update employee branch if provided manually
            manual_branch = request.POST.get('branch')
            if manual_branch and manual_branch.strip():
                employee = assignment.employee
                employee.branch = manual_branch.strip()
                employee.save()
                
            asset = assignment.asset
            asset.status = "In Use"
            asset.save()
            
            # We do not automatically redirect to the signature page because the admin does not sign it.
            # The employee will sign it later via the button on the list views.

            next_url = request.POST.get('next')
            if next_url:
                return redirect(next_url)
            return redirect(reverse('assign_asset'))
    else:
        from .sync_employees import sync_employees_from_api
        sync_employees_from_api()
        form = AssignmentForm()

    context = {
        "employees": Employee.objects.all().order_by('name'),
        "assets": Asset.objects.filter(status__iexact="Available").order_by('asset_id'),
        "today_date": timezone.now().date().isoformat(),
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

        is_staff = request.user.is_staff or getattr(request.user, 'role', '') in ('superadmin', 'admin')
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

        is_staff = request.user.is_staff or getattr(request.user, 'role', '') in ('superadmin', 'admin')
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
    is_staff = request.user.is_staff or getattr(request.user, 'role', '') in ('superadmin', 'admin')
    is_manager = getattr(request.user, 'role', '') == 'manager'
    if not (is_staff or is_manager):
        messages.error(request, "Only an admin or manager can process return requests.")
        return redirect('return_requests')

    if rq.status != 'Pending':
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
            
        old_assign = Assignment.objects.filter(asset=asset, status='In Use').last()
        if old_assign:
            old_assign.status = 'Returned'
            old_assign.save()
            
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
    is_staff = request.user.is_staff or getattr(request.user, 'role', '') in ('superadmin', 'admin')
    is_manager = getattr(request.user, 'role', '') == 'manager'
    if not (is_staff or is_manager):
        return redirect('asset_dashboard')

    pending_returns = (
        ReturnRequest.objects.filter(status='Pending')
        .select_related('asset', 'employee')
        .order_by('-created_at')
    )
    processed_returns = (
        ReturnRequest.objects.exclude(status='Pending')
        .select_related('asset', 'employee', 'processed_by')
        .order_by('-processed_at')[:30]
    )
    pending_count = ReturnRequest.objects.filter(status='Pending').count()
    accepted_count = ReturnRequest.objects.filter(status='Accepted').count()
    rejected_count = ReturnRequest.objects.filter(status='Rejected').count()
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
    is_staff = request.user.is_staff or getattr(request.user, 'role', '') == 'superadmin'
    is_manager = getattr(request.user, 'role', '') == 'manager'
        
    if is_staff:
        assignments = Assignment.objects.select_related("asset", "employee").filter(status__iexact='In Use')
    elif is_manager:
        assignments = Assignment.objects.select_related("asset", "employee").filter(
            employee__department__iexact=request.user.department,
            status__iexact='In Use'
        )
    else:
        # Employee - only show their own assets
        assignments = Assignment.objects.select_related("asset", "employee").filter(
            Q(employee__employee_id__iexact=request.user.username) | Q(employee__name__iexact=request.user.username),
            status__iexact='In Use'
        )

    # Unassigned assets
    unassigned_assets = Asset.objects.filter(status__iexact='Available')

    # Calculate asset stats
    asset_stats = Asset.objects.values('asset_type').annotate(
        total=Count('id'),
        in_use=Count('id', filter=Q(status__iexact='In Use')),
        available=Count('id', filter=Q(status__iexact='Available'))
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

    return render(request, 'asset_app/view_assets.html', {
        'assignments': assignments,
        'unassigned_assets': unassigned_assets,
        'asset_stats': asset_stats,
        'employees': Employee.objects.all().order_by('name'),
        'today_date': timezone.now().date().isoformat(),
        'is_employee': not (is_staff or is_manager),
        'type_dropdowns': type_dropdowns,
        'employee_requested': employee_requested,
        'pending_return_requests': ReturnRequest.objects.filter(status='Pending').select_related('asset', 'employee').order_by('-created_at'),
        'pending_return_asset_pks': list(
            ReturnRequest.objects.filter(status='Pending').values_list('asset_id', flat=True)
        ),
    })


# ------------------- ASSIGNED EMPLOYEES -------------------
@login_required
def assigned_employees(request):
    is_staff = request.user.is_staff or getattr(request.user, 'role', '') == 'superadmin'
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
    req.status = "Completed"
    req.completed_date = timezone.now()
    req.save()
    messages.success(request, f"Request {req.asset_type} approved and completed.")
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
    return render(request, 'asset_app/view_requests_list.html', {'requests': requests})


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
    asset = get_object_or_404(Asset, pk=pk)
    asset.delete()
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
    if request.user.is_staff or getattr(request.user, 'role', '') == 'superadmin':
        tickets = Ticket.objects.all().order_by('-created_at')
    elif getattr(request.user, 'role', '') == 'manager':
        tickets = Ticket.objects.filter(
            _department_user_q(request.user.department)
        ).order_by('-created_at')
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

    return render(request, 'asset_app/view_tickets.html', {
        'tickets': tickets,
        'form': form,
    })


# -------------------
# RAISE NEW TICKET
# -------------------
@login_required
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
# TICKET DETAIL PAGE
# -------------------
@login_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)

    if request.method == 'POST':
        is_admin = request.user.is_staff or getattr(request.user, 'role', '') in ('admin', 'superadmin', 'asset_admin')
        is_manager = getattr(request.user, 'role', '') == 'manager'
        if not (is_admin or is_manager):
            messages.error(request, "Only an admin or manager can update ticket status.")
            return redirect('view_tickets')
        new_status = request.POST.get('status')
        if new_status:
            # Capitalize to match backend conventions (Pending, Resolved, Closed, Open)
            new_status = new_status.capitalize()
            if new_status != ticket.status:
                ticket.status = new_status
                ticket.save()
                messages.success(request, '✅ Ticket status updated successfully!')
            else:
                messages.info(request, f'Ticket is already marked as {new_status}.')
            return redirect('view_tickets')

    return render(request, 'asset_app/ticket_detail.html', {'ticket': ticket, 'display_name': _employee_display_name(ticket.created_by)})



# ------------------- PUBLIC ASSET DETAIL (alternate) -------------------
def asset_detail1(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    asset_history = Assignment.objects.filter(asset=asset).select_related("employee").order_by("-id")

    return render(request, "asset_app/asset_detail1.html", {
        "asset": asset,
        "asset_history": asset_history,
    })
