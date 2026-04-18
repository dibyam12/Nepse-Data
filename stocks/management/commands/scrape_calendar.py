from django.core.management.base import BaseCommand
import asyncio
from playwright.async_api import async_playwright
from datetime import datetime
import re
from stocks.models import CalendarEvent

def clean_event_type(title, current_type):
    title = title.lower()
    t = current_type.lower()
    t = re.sub(r'<[^>]+>', '', t).strip()
    
    if 'agm' in title or 'sgm' in title or 'agm' in t or 'sgm' in t:
        return 'AGM/SGM'
    elif 'ipo' in title or 'ipo' in t or 'initial public offering' in title:
        return 'IPO'
    elif 'fpo' in title or 'fpo' in t or 'further public offering' in title:
        return 'FPO'
    elif 'dividend' in title or 'dividend' in t or 'bonus' in title or 'cash' in title:
        return 'Dividend'
    elif 'right' in title or 'right' in t:
        return 'Right Share'
    elif 'auction' in title or 'auction' in t:
        return 'Auction'
    elif 'book closure' in title or 'book closure' in t or 'closure' in title:
        return 'Book Closure'
    elif 'bond' in title or 'bond' in t or 'debenture' in title:
        return 'Bond / Debenture'
    elif 'mutual fund' in title or 'mutual fund' in t:
        return 'Mutual Fund'
    elif 'special' in title or 'special' in t:
        return 'Special'
    else:
        if any(c.isdigit() for c in t) and len(t) < 10:
            return 'Other'
        return current_type.title()

class Command(BaseCommand):
    help = 'Fetches and seeds the NepaliPaisa Stock Calendar.'

    def handle(self, *args, **options):
        from stocks.models import ScraperLog
        from django.utils import timezone
        
        start_time = timezone.now()
        
        self.stdout.write(self.style.SUCCESS('Starting NepaliPaisa Calendar Scraper...'))
        
        # Delete past events to keep DB clean
        from datetime import date
        deleted_count, _ = CalendarEvent.objects.filter(start_date__lt=date.today()).delete()
        if deleted_count > 0:
            self.stdout.write(f"Deleted {deleted_count} past calendar events.")
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            events_created = loop.run_until_complete(self.scrape_nepalipaisa())
            end_time = timezone.now()
            
            ScraperLog.objects.create(
                started_at=start_time,
                finished_at=end_time,
                status='success' if events_created > 0 else 'partial',
                records_added=events_created,
                symbols_processed=1, 
                message="Events up to date" if events_created == 0 else ""
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Command failed: {e}"))

    async def scrape_nepalipaisa(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            self.stdout.write("Navigating to NepaliPaisa...")
            await page.goto("https://nepalipaisa.com/stock-calendar", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000) # give time for JS tables to render
            
            tables = await page.locator("table").all()
            self.stdout.write(f"Found {len(tables)} tables on the calendar page.")
            
            events_created = 0
            
            for i, table in enumerate(tables):
                rows = await table.locator("tbody tr").all()
                for row in rows:
                    cols = await row.locator("td").all_inner_texts()
                    if len(cols) >= 4:
                        date_str = cols[0].strip()
                        company = cols[1].strip()
                        event_main = cols[2].strip()
                        event_sub = cols[3].strip()
                        
                        # Parse Date
                        start_date = None
                        end_date = None
                        
                        if 'to' in date_str.lower() or '-' in date_str and len(date_str) > 10:
                            parts = date_str.replace('to', '-').split('-')
                            if len(parts) >= 2:
                                s_str = parts[0].strip()
                                e_str = parts[1].strip()
                                try:
                                    start_date = datetime.strptime(s_str, '%Y-%m-%d').date()
                                    end_date = datetime.strptime(e_str, '%Y-%m-%d').date()
                                except ValueError:
                                    pass
                        else:
                            try:
                                start_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                            except ValueError:
                                pass
                                
                        # Construct Title
                        title = f"{company} - {event_main} ({event_sub})"
                        event_type = clean_event_type(title, event_main)
                        
                        if start_date:
                            from datetime import date
                            if start_date < date.today():
                                continue # Skip events that have already passed
                                
                            start_date_str = start_date.strftime('%Y-%m-%d')
                            end_date_str = end_date.strftime('%Y-%m-%d') if end_date else ""
                            
                            obj, created = await CalendarEvent.objects.aget_or_create(
                                title=title,
                                event_type=event_type,
                                start_date=start_date_str,
                                defaults={'end_date': end_date_str}
                            )
                            if created:
                                events_created += 1

            await browser.close()
            
            self.stdout.write(self.style.SUCCESS(f"Done! Calendar Events Created: {events_created}."))
            return events_created
