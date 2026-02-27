import logging
import os
import re
from datetime import datetime, date
from django.core.management.base import BaseCommand
from stocks.models import MarketHoliday
from playwright.sync_api import sync_playwright

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Scrape market holidays from NepseLink'

    def handle(self, *args, **options):
        from stocks.models import MarketHoliday, ScraperLog
        from django.utils import timezone
        
        start_time = timezone.now()
        
        self.stdout.write("Starting NepseLink Holiday scraper...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            try:
                page.goto('https://nepselink.com/nepse-calendar', timeout=60000)
                # Wait for the specific holiday items provided in the screenshot reference
                page.wait_for_selector('.holiday-item', timeout=20000)
                
                holiday_items = page.locator('.holiday-item').all()
                created_count = 0
                
                # Clear existing upcoming holidays to avoid stale data (optional but good for syncing)
                MarketHoliday.objects.all().delete()
                
                current_month = datetime.now().month
                current_year = datetime.now().year
                
                for item in holiday_items:
                    text_content = item.inner_text().strip()
                    if not text_content:
                        continue
                        
                    # Example parsed string from Nepselink: "फाल्गुन ३ (आइत) महाशिवरात्री ( 15 2026, Sun )"
                    # Sometimes the month string is missing in English, so we extract day and year.
                    day = 1
                    year = current_year
                    month = current_month
                    
                    # Try to regex parse the date from inside the parentheses
                    match = re.search(r'\(\s*([A-Za-z]*)\s*(\d{1,2})\s*(\d{4})', text_content)
                    if match:
                        month_str = match.group(1)
                        day_str = match.group(2)
                        year_str = match.group(3)
                        day = int(day_str)
                        year = int(year_str)
                        
                        # Just in case month names are there
                        months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
                        if month_str and month_str.lower()[:3] in months:
                            month = months[month_str.lower()[:3]]
                    else:
                        # Fallback simple digit extraction
                        simple_match = re.search(r'\(\s*(\d{1,2})\s+(\d{4})', text_content)
                        if simple_match:
                            day = int(simple_match.group(1))
                            year = int(simple_match.group(2))
                    
                    try:
                        holiday_date = date(year, month, day)
                    except ValueError:
                        holiday_date = date.today()
                        
                    # If date already exists, append description
                    holiday, created = MarketHoliday.objects.get_or_create(
                        date=holiday_date,
                        defaults={'description': text_content}
                    )
                    
                    if not created:
                        holiday.description = f"{holiday.description} / {text_content}"
                        holiday.save()
                    else:
                        created_count += 1
                
                self.stdout.write(self.style.SUCCESS(f"Successfully scraped and synced {created_count} holidays."))
                end_time = timezone.now()
                
                ScraperLog.objects.create(
                    started_at=start_time,
                    finished_at=end_time,
                    status='success' if created_count > 0 else 'partial',
                    records_added=created_count,
                    symbols_processed=1, 
                    message="Holidays up to date" if created_count == 0 else ""
                )
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error scraping holidays: {e}"))
            finally:
                browser.close()
