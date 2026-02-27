from django.core.management.base import BaseCommand
import asyncio
from playwright.async_api import async_playwright
import re
from stocks.models import QuarterlyReport

class Command(BaseCommand):
    help = 'Fetches and seeds Quarterly Reports from Merolagani.'

    def handle(self, *args, **options):
        from stocks.models import QuarterlyReport, ScraperLog
        from django.utils import timezone
        
        start_time = timezone.now()
        
        self.stdout.write(self.style.SUCCESS('Starting Merolagani Quarterly Reports Scraper...'))
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            reports_created = loop.run_until_complete(self.scrape_reports())
            
            end_time = timezone.now()
            
            ScraperLog.objects.create(
                started_at=start_time,
                finished_at=end_time,
                status='success' if reports_created > 0 else 'partial',
                records_added=reports_created,
                symbols_processed=1, 
                message="Reports up to date" if reports_created == 0 else ""
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Command failed: {e}"))

    async def scrape_reports(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            self.stdout.write("Navigating to Merolagani Company Reports...")
            await page.goto("https://www.merolagani.com/CompanyReports.aspx?type=QUARTERLY", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
            
            reports_created = 0
            has_next = True
            page_num = 1
            
            while has_next:
                self.stdout.write(f"Scraping page {page_num}...")
                
                reports = await page.locator("div.media").all()
                for report in reports:
                    body_a = report.locator("div.media-body a")
                    if await body_a.count() == 0:
                        continue
                        
                    summary = await body_a.inner_text()
                    summary = summary.strip()
                    
                    publish_date = ""
                    date_elem = report.locator("small.text-muted").first
                    if await date_elem.count() > 0:
                        publish_date = await date_elem.inner_text()
                        publish_date = publish_date.strip()
                        
                    # Extract symbol if possible (e.g., "(RIDI)")
                    symbol = ""
                    match = re.search(r'\(([A-Z0-9]{2,8})\)', summary)
                    if match:
                        symbol = match.group(1).strip()
                    else:
                        # Sometimes it's missing, we cannot properly link it
                        continue
                        
                    sector = ""
                    reported_eps = ""
                    ttm_eps = ""
                    yoy_growth_percent = None
                    surprise = ""
                    prev_earnings = ""
                    
                    eps_match = re.search(r'EPS of Rs\.? ?([\d\.]+)', summary, re.IGNORECASE)
                    if eps_match:
                        reported_eps = eps_match.group(1)
                        
                    grow_match = re.search(r'(increased|decreased|growth) (?:by )?([\d\.]+)%', summary, re.IGNORECASE)
                    if grow_match:
                        try:
                            val = float(grow_match.group(2))
                            if 'decreased' in grow_match.group(1).lower():
                                yoy_growth_percent = -val
                            else:
                                yoy_growth_percent = val
                        except:
                            pass
                            
                    obj, created = await QuarterlyReport.objects.aget_or_create(
                        symbol=symbol,
                        reported_eps=reported_eps,
                        publish_date=publish_date,
                        defaults={
                            'sector': sector,
                            'prev_earnings': prev_earnings,
                            'earnings': summary,
                            'yoy_growth_percent': yoy_growth_percent,
                            'ttm_eps': ttm_eps,
                            'surprise': surprise
                        }
                    )
                    if created:
                        reports_created += 1

                # Check Next Button
                next_btn = page.locator("a[title='Next Page']")
                if await next_btn.count() > 0 and await next_btn.is_visible():
                    has_next = True
                    page_num += 1
                    await next_btn.click()
                    await page.wait_for_timeout(3000)
                else:
                    has_next = False
                    
                # The user requested to stop when final page processed. If we reach here, loop ends.
                # To prevent endless loop on bugged sites:
                if page_num > 50: 
                    self.stdout.write("Reached page limit (50). Stopping.")
                    break

            await browser.close()
            self.stdout.write(self.style.SUCCESS(f"Done! Quarterly Reports Created: {reports_created}."))
            return reports_created
