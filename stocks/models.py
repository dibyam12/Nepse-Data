from django.db import models


class StockData(models.Model):
    """
    Daily OHLCV data for NEPSE-listed stocks and indices.
    Scraped from ShareSansar.
    """
    CATEGORY_CHOICES = [
        ('stock', 'Stock'),
        ('index', 'Index'),
    ]

    symbol = models.CharField(max_length=20, db_index=True)
    date = models.DateField(db_index=True)
    open = models.FloatField()
    high = models.FloatField()
    low = models.FloatField()
    close = models.FloatField()
    volume = models.BigIntegerField(default=0)
    category = models.CharField(
        max_length=10, choices=CATEGORY_CHOICES, default='stock'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('symbol', 'date')
        indexes = [
            models.Index(fields=['symbol', 'date']),
            models.Index(fields=['symbol', '-date']),
            models.Index(fields=['-date']),
        ]
        ordering = ['-date']

    def __str__(self):
        return f"{self.symbol} | {self.date} | Close: {self.close}"

    @property
    def change(self):
        """Daily price change (close - open)."""
        return round(self.close - self.open, 2)

    @property
    def change_percent(self):
        """Daily price change percentage."""
        if self.open == 0:
            return 0.0
        return round((self.close - self.open) / self.open * 100, 2)


class DownloadLog(models.Model):
    """Tracks CSV downloads for analytics."""
    downloaded_at = models.DateTimeField(auto_now_add=True)
    symbols = models.TextField(help_text="Comma-separated symbols or 'ALL'")
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    record_count = models.IntegerField(default=0)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-downloaded_at']

    def __str__(self):
        return f"Download at {self.downloaded_at} — {self.record_count} records"


class ScraperLog(models.Model):
    """Logs each scraper run for the admin dashboard."""
    STATUS_CHOICES = [
        ('success', 'Success'),
        ('partial', 'Partial'),
        ('failed', 'Failed'),
    ]

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='success')
    records_added = models.IntegerField(default=0)
    records_updated = models.IntegerField(default=0)
    symbols_processed = models.IntegerField(default=0)
    message = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Scrape {self.started_at:%Y-%m-%d %H:%M} — {self.status}"


class SiteVisit(models.Model):
    """Tracks page visits for live/total user analytics."""
    session_key = models.CharField(max_length=40, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    path = models.CharField(max_length=500, default='/')
    visited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-visited_at']

    def __str__(self):
        return f"{self.session_key[:8]}… — {self.path} at {self.visited_at:%H:%M}"


class CalendarEvent(models.Model):
    """Upcoming events like Dividends, AGM, Book Closures (scraped from NepseAlpha)."""
    title = models.CharField(max_length=255)
    event_type = models.CharField(max_length=100)
    start_date = models.CharField(max_length=50, blank=True)
    end_date = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.event_type}: {self.title}"


class QuarterlyReport(models.Model):
    """Quarterly Earnings data scraped from NepseAlpha."""
    symbol = models.CharField(max_length=20, db_index=True)
    sector = models.CharField(max_length=100)
    prev_earnings = models.CharField(max_length=50, blank=True)
    reported_eps = models.CharField(max_length=50, blank=True)
    earnings = models.TextField(blank=True)
    yoy_growth_percent = models.FloatField(null=True, blank=True)
    ttm_eps = models.CharField(max_length=50, blank=True)
    surprise = models.TextField(blank=True)
    publish_date = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('symbol', 'reported_eps', 'publish_date')

    def __str__(self):
        return f"{self.symbol} | EPS: {self.reported_eps} | Growth: {self.yoy_growth_percent}%"


class MarketHoliday(models.Model):
    """Upcoming stock market holidays scraped from NepseAlpha."""
    date = models.CharField(max_length=100)
    description = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']
        unique_together = ('date', 'description')

    def __str__(self):
        return f"{self.date} - {self.description}"

