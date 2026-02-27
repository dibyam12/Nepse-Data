"""Web dashboard URL routing."""
from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("stock/<path:symbol>/", views.stock_detail_view, name="stock-detail"),
    path("docs/", views.api_docs_view, name="api-docs"),
    path("download/", views.download_page_view, name="download"),
    path("download/csv/", views.download_csv_view, name="download-csv"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("analytics/", views.admin_dashboard_view, name="admin-dashboard"),
    path("calendar/", views.calendar_view, name="calendar"),
]
