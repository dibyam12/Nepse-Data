"""
NEPSE Data API — URL Configuration
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("stocks.api_urls")),
    path("", include("stocks.urls")),
]
