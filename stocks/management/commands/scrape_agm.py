from django.core.management.base import BaseCommand
import asyncio
from playwright.async_api import async_playwright
from datetime import datetime
from stocks.models import CalendarEvent

def clean_event_type(title, current_type):
    title = title.lower()
    t = current_type.lower()
    
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
    help = 'Fetches and seeds the ShareSansar AGM/SGM List.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting ShareSansar AGM Scraper...'))
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(self.scrape_agm())
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Command failed: {e}"))

    async def scrape_agm(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            self.stdout.write("Navigating to ShareSansar AGM List...")
            await page.goto("https://www.sharesansar.com/agm-list", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
            
            events_created = 0
            
            # Find year options
            year_select = page.locator("select[name='year']")
            await year_select.wait_for()
            options = await page.locator("select[name='year'] option").all()
            values_to_check = []
            for opt in options:
                val = await opt.get_attribute("value")
                text = await opt.inner_text()
                if val:
                    values_to_check.append((val, text.strip()))
            
            self.stdout.write(f"Found {len(values_to_check)} fiscal years.")
            
            # Limit to recent 3 years for performance unless requested otherwise, but the user requested "all available fiscal years"
            # However doing 10+ years takes a long time. Let's do all.
            for val, text in values_to_check:
                self.stdout.write(f"Fetching for FY: {text}")
                await year_select.select_option(val)
                # Need to click search button to load table
                search_btn = page.locator("button#btn_agmlist_submit")
                if await search_btn.count() > 0:
                    await search_btn.click()
                else:
                    search_btn2 = page.locator("button:has-text('Search')")
                    if await search_btn2.count() > 0:
                        await search_btn2.click()
                        
                await page.wait_for_timeout(3000) # wait for data table to load
                
                # Check for pagination or single page table. It uses DataTables usually, often "Load More" or "Next" or just showing all.
                # Just change length to 500 if select exists
                length_select = page.locator("select[name='myTableC_length']")
                if await length_select.count() > 0:
                    try:
                        await length_select.select_option(label="500", timeout=2000)
                    except:
                        try:
                            await length_select.select_option(label="All", timeout=2000)
                        except:
                            pass
                    await page.wait_for_timeout(2000)
                
                rows = await page.locator("table tbody tr").all()
                for row in rows:
                    cols = await row.locator("td").all_inner_texts()
                    if len(cols) >= 8:
                        # Headers: S.N., Symbol, Company, AGM, Venue / Time, Book Closure Date, AGM Date, Agenda
                        symbol = cols[1].strip()
                        company = cols[2].strip()
                        agm_type = cols[3].strip() # AGM or SGM
                        book_closure_str = cols[5].strip()
                        agm_date_str = cols[6].strip()
                        
                        start_date = ""
                        end_date = ""
                        
                        if agm_date_str and agm_date_str != "-":
                            try:
                                start_date = datetime.strptime(agm_date_str, '%Y-%m-%d').strftime('%Y-%m-%d')
                            except ValueError:
                                start_date = agm_date_str
                                
                        if book_closure_str and book_closure_str != "-":
                            try:
                                end_date = datetime.strptime(book_closure_str, '%Y-%m-%d').strftime('%Y-%m-%d')
                            except ValueError:
                                end_date = book_closure_str
                                
                        title = f"{company} ({symbol}) {agm_type} - FY {text}"
                        event_type = agm_type if agm_type else "AGM/SGM"
                        event_type = clean_event_type(title, event_type)
                        
                        if start_date:
                            obj, created = await CalendarEvent.objects.aget_or_create(
                                title=title,
                                event_type=event_type,
                                start_date=start_date,
                                defaults={'end_date': end_date}
                            )
                            if created:
                                events_created += 1

            await browser.close()
            self.stdout.write(self.style.SUCCESS(f"Done! AGM/SGM Events Created: {events_created}."))
            return events_created
