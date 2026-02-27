import asyncio
import logging
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

logger = logging.getLogger('stocks')

class NepseAlphaCalendarScraper:
    """Scrapes NepseAlpha calendar for upcoming events, dividends, and quarterly reports."""
    
    URL = 'https://nepsealpha.com/nepse-calendar'

    async def fetch_calendar_data(self):
        """Fetches and parses the calendar HTML using Playwright."""
        logger.info(f"Launching Playwright to fetch {self.URL}")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            try:
                # Wait for the network to be idle, then wait extra time for Vue.js to render the DataTables
                await page.goto(self.URL, wait_until='networkidle', timeout=60000)
                await page.wait_for_timeout(8000) 
                
                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')
                
                return self._parse_tables(soup)
                
            except Exception as e:
                logger.error(f"Playwright scraping failed: {e}")
                return {'events': [], 'reports': []}
            finally:
                await browser.close()
                
    def _parse_tables(self, soup):
        data = {'events': [], 'reports': [], 'holidays': []}
        
        # ─── Parse Corporate Events ───
        # In NepseAlpha, the 'Upcoming Events' are often inside list items in a specific card or table
        # Let's search inside the 'table' and 'v-list' classes for event nodes
        # Often it comes as a table with <th> elements for headers instead of <td>
        events_tables = soup.find_all('table')
        if len(events_tables) >= 1:
            events_table = events_tables[0]
            rows = events_table.find('tbody').find_all('tr') if events_table.find('tbody') else events_table.find_all('tr')
            for row in rows:
                cols = row.find_all(['td', 'th'])
                if len(cols) >= 4:
                    title = cols[0].get_text(" ", strip=True)
                    ev_type = cols[1].get_text(" ", strip=True)
                    data['events'].append({
                        'title': title,
                        'type': ev_type,
                        'start_date': cols[2].get_text(strip=True),
                        'end_date': cols[3].get_text(strip=True)
                    })

        # ─── Parse Market Holidays ───
        # Look for a table or Vue data-table wrapper containing holidays
        # The word 'Holiday' or 'Description' is a good hint for the holiday table headers
        holiday_table = None
        for tbl in soup.find_all('table'):
            headers = tbl.find_all('th')
            header_text = " ".join([h.get_text().lower() for h in headers])
            if 'holiday' in header_text or 'description' in header_text or 'days left' in header_text:
                holiday_table = tbl
                break
                
        # Fallback to index 1 if available and header matching failed
        if not holiday_table and len(events_tables) >= 2:
            holiday_table = events_tables[1]
            
        if holiday_table:
            rows = holiday_table.find('tbody').find_all('tr') if holiday_table.find('tbody') else holiday_table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 2:
                    date_raw = cols[0].get_text(strip=True)
                    # Extract date before the slash if it exists (e.g., "Mon, 02 Mar 2026 / फाल्गुन १८" -> "Mon, 02 Mar 2026")
                    date_str = date_raw.split('/')[0].strip() if '/' in date_raw else date_raw
                    desc_str = cols[1].get_text(" ", strip=True)
                    if date_str and desc_str and 'No data available' not in date_str:
                        data['holidays'].append({
                            'date': date_str,
                            'description': desc_str
                        })

        # ─── Parse Quarterly Reports ───
        # Usually the last table on the page with lots of EPS/Earnings columns
        report_table = None
        for tbl in soup.find_all('table'):
            headers = tbl.find_all('th')
            header_text = " ".join([h.get_text().lower() for h in headers])
            if 'eps' in header_text and 'earnings' in header_text:
                report_table = tbl
                break
                
        if not report_table and len(events_tables) >= 3:
            report_table = events_tables[2]
            
        if report_table:
            rows = report_table.find('tbody').find_all('tr') if report_table.find('tbody') else report_table.find_all('tr')
            for row in rows:
                cols = [td.get_text(" ", strip=True) for td in row.find_all('td')]
                if len(cols) >= 9:
                    raw_symbol = cols[0]
                    clean_symbol = raw_symbol.split()[-1] if raw_symbol else ""
                    
                    yoy_growth = cols[5].replace('%', '').replace(',', '').strip()
                    if yoy_growth == '' or yoy_growth == '-':
                        yoy_growth_float = None
                    else:
                        try:
                            yoy_growth_float = float(yoy_growth)
                        except ValueError:
                            yoy_growth_float = None

                    data['reports'].append({
                        'symbol': clean_symbol,
                        'sector': cols[1],
                        'prev_earnings': cols[2],
                        'reported_eps': cols[3],
                        'earnings': cols[4],
                        'yoy_growth': yoy_growth_float,
                        'ttm_eps': cols[6],
                        'surprise': cols[7],
                        'date': cols[8]
                    })
                    
        logger.info(f"Scraped {len(data['events'])} events, {len(data['reports'])} reports, and {len(data['holidays'])} holidays.")
        return data

    def save_to_db(self, data):
        """Save parsed calendar data into the database."""
        from stocks.models import CalendarEvent, QuarterlyReport, MarketHoliday
        
        events_created = 0
        reports_created = 0
        holidays_created = 0
        reports_skipped = 0
        
        # Save Events
        for event in data.get('events', []):
            obj, created = CalendarEvent.objects.get_or_create(
                title=event['title'],
                event_type=event['type'],
                start_date=event['start_date'],
                end_date=event['end_date']
            )
            if created:
                events_created += 1

        # Save Market Holidays
        for holiday in data.get('holidays', []):
            obj, created = MarketHoliday.objects.get_or_create(
                date=holiday['date'],
                description=holiday['description']
            )
            if created:
                holidays_created += 1

        # Save Quarterly Reports
        for report in data.get('reports', []):
            try:
                obj, created = QuarterlyReport.objects.get_or_create(
                    symbol=report['symbol'],
                    reported_eps=report['reported_eps'],
                    publish_date=report['date'],
                    defaults={
                        'sector': report['sector'],
                        'prev_earnings': report['prev_earnings'],
                        'earnings': report['earnings'],
                        'yoy_growth_percent': report['yoy_growth'],
                        'ttm_eps': report['ttm_eps'],
                        'surprise': report['surprise']
                    }
                )
                if created:
                    reports_created += 1
                else:
                    reports_skipped += 1
            except Exception as e:
                logger.error(f"Error saving report {report['symbol']}: {e}")

        logger.info(f"DB Update: {events_created} new events. {holidays_created} new holidays. {reports_created} new reports, {reports_skipped} existing.")
        return {'events_created': events_created, 'reports_created': reports_created, 'holidays_created': holidays_created}

