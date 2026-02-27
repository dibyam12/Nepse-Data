from django.core.management.base import BaseCommand
import asyncio
from stocks.calendar_scraper import NepseAlphaCalendarScraper

class Command(BaseCommand):
    help = 'Fetches and seeds the NepseAlpha Investment Calendar and Quarterly Reports.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting NepseAlpha Calendar Scraper with Playwright...'))
        
        scraper = NepseAlphaCalendarScraper()
        
        # Async invocation inside Django synchronous command
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            data = loop.run_until_complete(scraper.fetch_calendar_data())
            
            if not data['events'] and not data['reports']:
                self.stdout.write(self.style.ERROR('No data retrieved from NepseAlpha.'))
                return
                
            self.stdout.write(f"Scraped {len(data['events'])} events and {len(data['reports'])} reports.")
            
            # Save to Database
            self.stdout.write("Saving to database...")
            stats = scraper.save_to_db(data)
            
            self.stdout.write(self.style.SUCCESS(
                f"Done! Calendar Events Created: {stats['events_created']}. "
                f"Quarterly Reports Created: {stats['reports_created']}."
            ))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Command failed: {e}"))
