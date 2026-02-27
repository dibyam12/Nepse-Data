from django.contrib import admin
from .models import StockData, DownloadLog, ScraperLog, SiteVisit


@admin.register(StockData)
class StockDataAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'date', 'close', 'volume', 'category')
    list_filter = ('category', 'symbol')
    search_fields = ('symbol',)
    ordering = ('-date',)


@admin.register(DownloadLog)
class DownloadLogAdmin(admin.ModelAdmin):
    list_display = ('downloaded_at', 'symbols', 'record_count', 'ip_address')
    readonly_fields = ('downloaded_at', 'symbols', 'date_from', 'date_to', 'record_count', 'ip_address')


@admin.register(ScraperLog)
class ScraperLogAdmin(admin.ModelAdmin):
    list_display = ('started_at', 'status', 'records_added', 'symbols_processed')
    list_filter = ('status',)


@admin.register(SiteVisit)
class SiteVisitAdmin(admin.ModelAdmin):
    list_display = ('session_key', 'ip_address', 'path', 'visited_at')
    readonly_fields = ('session_key', 'ip_address', 'path', 'visited_at')
