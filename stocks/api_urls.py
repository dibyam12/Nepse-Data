"""API URL routing."""
from django.urls import path
from . import api_views

urlpatterns = [
    path("", api_views.api_overview, name="api-overview"),
    path("stocks/", api_views.stock_list, name="api-stock-list"),
    path("stocks/<path:symbol>/", api_views.StockHistoryView.as_view(), name="api-stock-history"),
    path("stocks/<path:symbol>/latest/", api_views.stock_latest, name="api-stock-latest"),
    path("latest/", api_views.all_latest, name="api-all-latest"),
    path("index/", api_views.nepse_index, name="api-nepse-index"),
    path("calendar/events/", api_views.CalendarEventListView.as_view(), name="api-calendar-events"),
    path("calendar/reports/", api_views.QuarterlyReportListView.as_view(), name="api-calendar-reports"),
]
