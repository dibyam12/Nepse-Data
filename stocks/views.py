"""
Web dashboard views for NEPSE Data.
"""
import csv
import json
from datetime import datetime

from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from django.db.models import Max, Min, Count, Sum
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required

from .models import StockData, DownloadLog


def dashboard_view(request):
    """Main dashboard page — shows market overview with paginated stock list."""
    latest_date = StockData.objects.aggregate(Max('date'))['date__max']
    search_query = request.GET.get('q', '').strip()

    # Get latest data for all stocks
    stocks = StockData.objects.none()
    if latest_date:
        stocks = StockData.objects.filter(date=latest_date, category='stock')
        if search_query:
            stocks = stocks.filter(symbol__icontains=search_query)
        stocks = stocks.order_by('symbol')

    # Pagination — 25 stocks per page
    paginator = Paginator(stocks, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # NEPSE index
    nepse = StockData.objects.filter(
        symbol='NEPSE'
    ).order_by('-date').first()

    # Stats
    total_symbols = StockData.objects.values('symbol').distinct().count()
    total_records = StockData.objects.count()
    date_range = StockData.objects.aggregate(
        earliest=Min('date'), latest=Max('date')
    )

    context = {
        'stocks': page_obj,
        'page_obj': page_obj,
        'nepse': nepse,
        'latest_date': latest_date,
        'total_symbols': total_symbols,
        'total_records': total_records,
        'date_range': date_range,
        'search_query': search_query,
    }
    return render(request, 'stocks/dashboard.html', context)


def stock_detail_view(request, symbol):
    """Detail page for a single stock — shows historical chart + CSV download."""
    from .models import CalendarEvent, QuarterlyReport
    symbol = symbol.upper()
    
    # ─── Stock Data ───
    all_records = StockData.objects.filter(symbol=symbol).order_by('-date')
    latest = all_records.first() if all_records.exists() else None

    # Pagination for table
    paginator = Paginator(all_records, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Date range & count
    stock_date_range = all_records.aggregate(
        earliest=Min('date'), latest=Max('date')
    )
    total_count = all_records.count()

    # Chart data
    chart_qs = all_records[:30]
    chart_data = [
        {
            'date': str(r.date),
            'open': float(r.open),
            'high': float(r.high),
            'low': float(r.low),
            'close': float(r.close),
            'volume': r.volume,
        }
        for r in reversed(chart_qs)
    ]

    # ─── Calendar Data ───
    events = CalendarEvent.objects.filter(title__icontains=symbol).order_by('-start_date')
    reports = QuarterlyReport.objects.filter(symbol=symbol).order_by('-publish_date')

    # Event Page
    events_paginator = Paginator(events, 10)
    events_page_number = request.GET.get('events_page', 1)
    events_page_obj = events_paginator.get_page(events_page_number)

    # Report Page
    reports_paginator = Paginator(reports, 10)
    reports_page_number = request.GET.get('reports_page', 1)
    reports_page_obj = reports_paginator.get_page(reports_page_number)

    context = {
        'symbol': symbol,
        'latest': latest,
        'records': page_obj.object_list,
        'page_obj': page_obj,
        'chart_data_json': json.dumps(chart_data),
        'stock_date_range': stock_date_range,
        'total_count': total_count,
        # Calendar Context
        'events': events_page_obj.object_list,
        'events_page_obj': events_page_obj,
        'reports': reports_page_obj.object_list,
        'reports_page_obj': reports_page_obj,
    }
    return render(request, 'stocks/stock_detail.html', context)


def api_docs_view(request):
    """API documentation page."""
    return render(request, 'stocks/api_docs.html')


# ─── CSV Download ─────────────────────────────────────────────────────────

def download_page_view(request):
    """Render the CSV download page with stock selector and date pickers."""
    symbols = (
        StockData.objects
        .values_list('symbol', flat=True)
        .distinct()
        .order_by('symbol')
    )
    # Use stock-only date range (exclude NEPSE index which goes back to 1997)
    date_range = StockData.objects.filter(category='stock').aggregate(
        earliest=Min('date'), latest=Max('date')
    )
    context = {
        'symbols': list(symbols),
        'date_range': date_range,
    }
    return render(request, 'stocks/download.html', context)


def download_csv_view(request):
    """Generate and return a CSV file of stock data based on filters."""
    # Parse parameters
    mode = request.GET.get('mode', 'all')  # 'all' or 'selected'
    selected_symbols = request.GET.getlist('symbols')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    # Build queryset
    qs = StockData.objects.all().order_by('symbol', 'date')

    if mode == 'selected' and selected_symbols:
        qs = qs.filter(symbol__in=selected_symbols)

    if date_from:
        try:
            qs = qs.filter(date__gte=datetime.strptime(date_from, '%Y-%m-%d').date())
        except ValueError:
            pass

    if date_to:
        try:
            qs = qs.filter(date__lte=datetime.strptime(date_to, '%Y-%m-%d').date())
        except ValueError:
            pass

    record_count = qs.count()

    # Build filename
    if mode == 'selected' and selected_symbols:
        sym_part = '_'.join(selected_symbols[:3])
        if len(selected_symbols) > 3:
            sym_part += f'_and_{len(selected_symbols) - 3}_more'
    else:
        sym_part = 'all_stocks'

    date_part = ''
    if date_from:
        date_part += f'_from_{date_from}'
    if date_to:
        date_part += f'_to_{date_to}'

    filename = f'nepse_{sym_part}{date_part}.csv'

    # Log the download
    ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
    if not ip:
        ip = request.META.get('REMOTE_ADDR')

    DownloadLog.objects.create(
        symbols=','.join(selected_symbols) if selected_symbols else 'ALL',
        date_from=datetime.strptime(date_from, '%Y-%m-%d').date() if date_from else None,
        date_to=datetime.strptime(date_to, '%Y-%m-%d').date() if date_to else None,
        record_count=record_count,
        ip_address=ip,
    )

    # Generate CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(['Symbol', 'Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Category'])

    for record in qs.iterator():
        writer.writerow([
            record.symbol,
            record.date,
            record.open,
            record.high,
            record.low,
            record.close,
            record.volume,
            record.category,
        ])

    return response


# ─── Authentication ───────────────────────────────────────────────────────

def login_view(request):
    """Admin login page."""
    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_staff:
            login(request, user)
            next_url = request.GET.get('next', '/analytics/')
            return redirect(next_url)
        else:
            error = 'Invalid credentials or insufficient permissions.'
    return render(request, 'stocks/login.html', {'error': error})


def logout_view(request):
    """Log out and redirect to dashboard."""
    logout(request)
    return redirect('dashboard')


# ─── Admin Analytics Dashboard ────────────────────────────────────────────

@login_required(login_url='/login/')
def admin_dashboard_view(request):
    """Admin analytics dashboard — scraper logs, user stats, download stats."""
    from .models import ScraperLog, SiteVisit, DownloadLog
    from datetime import timedelta
    from django.core.management import call_command
    from django.contrib import messages
    import subprocess
    import sys
    import os
    from django.core.paginator import Paginator
    from django.http import JsonResponse

    # Global dictionary to track active scraper processes across requests
    # format: {'job_name': <Popen object>}
    if not hasattr(admin_dashboard_view, 'active_jobs'):
        admin_dashboard_view.active_jobs = {}
    active_jobs = admin_dashboard_view.active_jobs
    
    # Ensure logs directory exists for subprocess stdout
    os.makedirs('logs', exist_ok=True)

    if request.method == 'POST':
        action = request.POST.get('action')
        
        # AJAX Endpoint for Live Logs
        if action == 'get_live_log':
            job_name = request.POST.get('job_name')
            if not job_name:
                return JsonResponse({'log_content': 'Error: No job name', 'is_completed': True})
                
            log_file_path = f"logs/{job_name.replace(' ', '_')}.log"
            log_content = ""
            is_completed = False
            
            if os.path.exists(log_file_path):
                with open(log_file_path, 'r', encoding='utf-8') as f:
                    log_content = f.read()
                    
            if job_name not in active_jobs or active_jobs[job_name].poll() is not None:
                is_completed = True
                
            return JsonResponse({
                'log_content': log_content,
                'is_completed': is_completed
            })
        
        # Scraper Actions
        def start_job(job_name, cmd_name, success_msg):
            if job_name in active_jobs and active_jobs[job_name].poll() is None:
                messages.error(request, f"{job_name} is already running!")
            else:
                log_file_path = f"logs/{job_name.replace(' ', '_')}.log"
                f = open(log_file_path, 'w', encoding='utf-8')
                
                p = subprocess.Popen(
                    [sys.executable, '-u', 'manage.py', cmd_name], 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                active_jobs[job_name] = p
                
                import threading
                def tee_output(proc, file_obj):
                    # Read line-by-line as it comes in
                    for line in iter(proc.stdout.readline, ''):
                        sys.stdout.write(line)
                        sys.stdout.flush()
                        file_obj.write(line)
                        file_obj.flush()
                    # Clean up file pointers when process finishes
                    proc.stdout.close()
                    file_obj.close()
                    
                threading.Thread(target=tee_output, args=(p, f), daemon=True).start()
                messages.success(request, success_msg)

        if action == 'run_daily':
            start_job('Daily Scraper', 'scrape', 'Daily Scraper (ShareSansar) started in background.')
        elif action == 'run_holidays':
            start_job('Holidays Scraper', 'scrape_holidays', 'NepseLink Holidays Scraper started in background.')
        elif action == 'run_events':
            start_job('Events Scraper', 'scrape_calendar', 'NepaliPaisa Events Scraper started in background.')
        elif action == 'run_reports':
            start_job('Reports Scraper', 'scrape_quarterly_reports', 'Merolagani Quarterly Reports Scraper started in background.')
        elif action == 'run_agm':
            start_job('Historic AGM Scraper', 'scrape_agm', 'ShareSansar Historic AGM Scraper started in background.')
            
        # Cancel Job Action
        elif action == 'cancel_job':
            job_to_cancel = request.POST.get('job_name')
            if job_to_cancel in active_jobs:
                p = active_jobs[job_to_cancel]
                if p.poll() is None:
                    p.terminate()
                    messages.success(request, f"Successfully cancelled {job_to_cancel}.")
                else:
                    messages.error(request, f"{job_to_cancel} had already finished.")
                del active_jobs[job_to_cancel]
            
        # Log Clearing Actions
        elif action == 'clear_scraper_logs':
            count, _ = ScraperLog.objects.all().delete()
            messages.success(request, f"Cleared {count} scraper logs.")
        elif action == 'clear_download_logs':
            count, _ = DownloadLog.objects.all().delete()
            messages.success(request, f"Cleared {count} download logs.")
            
        # Specific Log Deletion
        elif action == 'delete_download':
            log_id = request.POST.get('log_id')
            if log_id:
                DownloadLog.objects.filter(id=log_id).delete()
                messages.success(request, "Download log deleted successfully.")
                
        return redirect('admin-dashboard')

    now = timezone.now()
    
    # Cleanup finished jobs from tracker before passing to context
    finished_jobs = []
    for j_name, proc in active_jobs.items():
        if proc.poll() is not None:
            finished_jobs.append(j_name)
    for j_name in finished_jobs:
        del active_jobs[j_name]
        
    running_jobs = list(active_jobs.keys())

    # Scraper logs Pagination
    scraper_qs = ScraperLog.objects.all().order_by('-started_at')
    scraper_paginator = Paginator(scraper_qs, 15)
    scraper_page_num = request.GET.get('scraper_page', 1)
    scraper_logs = scraper_paginator.get_page(scraper_page_num)

    # Download stats & Pagination
    total_downloads = DownloadLog.objects.count()
    total_records_downloaded = DownloadLog.objects.aggregate(
        total=Sum('record_count')
    )['total'] or 0
    
    download_qs = DownloadLog.objects.all().order_by('-downloaded_at')
    download_paginator = Paginator(download_qs, 10)
    download_page_num = request.GET.get('download_page', 1)
    recent_downloads = download_paginator.get_page(download_page_num)

    # User stats
    live_cutoff = now - timedelta(minutes=15)
    live_users = (
        SiteVisit.objects
        .filter(visited_at__gte=live_cutoff)
        .values('session_key')
        .distinct()
        .count()
    )

    total_users = (
        SiteVisit.objects
        .values('session_key')
        .distinct()
        .count()
    )

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_users = (
        SiteVisit.objects
        .filter(visited_at__gte=today_start)
        .values('session_key')
        .distinct()
        .count()
    )

    total_page_views = SiteVisit.objects.count()

    context = {
        'running_jobs': running_jobs,
        'scraper_logs': scraper_logs,
        'total_downloads': total_downloads,
        'total_records_downloaded': total_records_downloaded,
        'recent_downloads': recent_downloads,
        'live_users': live_users,
        'total_users': total_users,
        'today_users': today_users,
        'total_page_views': total_page_views,
    }
    return render(request, 'stocks/admin_dashboard.html', context)


def calendar_view(request):
    """View to display Nepse Investment Calendar, Quarterly Reports, and Holidays."""
    from .models import CalendarEvent, QuarterlyReport, MarketHoliday
    from django.core.paginator import Paginator
    
    search_query = request.GET.get('q', '').strip()
    event_type_filter = request.GET.get('event_type', '').strip()
    
    events_qs = CalendarEvent.objects.all().order_by('-start_date')
    reports_qs = QuarterlyReport.objects.all().order_by('-publish_date')
    holidays_qs = MarketHoliday.objects.all().order_by('-date')
    
    # Get distinct event types for the frontend dropdown filter
    event_types = CalendarEvent.objects.values_list('event_type', flat=True).distinct().order_by('event_type')
    
    # Apply Filters
    if search_query:
        events_qs = events_qs.filter(title__icontains=search_query)
        reports_qs = reports_qs.filter(symbol__icontains=search_query)

    if event_type_filter:
        events_qs = events_qs.filter(event_type__iexact=event_type_filter)
    
    # Events Pagination
    events_paginator = Paginator(events_qs, 25)
    events_page_num = request.GET.get('events_page', 1)
    events_page = events_paginator.get_page(events_page_num)
    
    # Reports Pagination
    reports_paginator = Paginator(reports_qs, 25)
    reports_page_num = request.GET.get('reports_page', 1)
    reports_page = reports_paginator.get_page(reports_page_num)
    
    # Holidays Pagination
    holidays_paginator = Paginator(holidays_qs, 25)
    holidays_page_num = request.GET.get('holidays_page', 1)
    holidays_page = holidays_paginator.get_page(holidays_page_num)
    
    context = {
        'events': events_page.object_list,
        'events_page': events_page,
        'event_types': event_types,
        'event_type_filter': event_type_filter,
        'reports': reports_page.object_list,
        'reports_page': reports_page,
        'holidays': holidays_page.object_list,
        'holidays_page': holidays_page,
        'search_query': search_query,
    }
    return render(request, 'stocks/calendar.html', context)

