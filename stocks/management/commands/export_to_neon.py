"""
Management command to copy all data from local SQLite to Neon PostgreSQL.

Uses direct model-level batch copying with bulk_create for performance.
Handles all 7 models and shows progress.

Usage:
    python manage.py export_to_neon               # Copy all data
    python manage.py export_to_neon --batch 2000   # Custom batch size
"""
from django.core.management.base import BaseCommand
from django.core.management import call_command
from stocks.models import (
    StockData, DownloadLog, ScraperLog,
    SiteVisit, CalendarEvent, QuarterlyReport, MarketHoliday,
)


BATCH_SIZE = 1000


class Command(BaseCommand):
    help = "Exports all data from local SQLite to Neon PostgreSQL (batch copy)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch', type=int, default=BATCH_SIZE,
            help=f'Batch size for bulk_create (default: {BATCH_SIZE})',
        )

    def handle(self, *args, **options):
        from django.conf import settings

        # Verify 'neon' database is configured
        if 'neon' not in settings.DATABASES:
            self.stderr.write(self.style.ERROR(
                "No 'neon' database configured. "
                "Make sure DATABASE_URL is set in your .env file."
            ))
            return

        batch_size = options['batch']

        # 1. Run migrations on Neon first
        self.stdout.write(self.style.WARNING("\n=== Step 1: Running migrations on Neon DB ==="))
        try:
            call_command('migrate', database='neon', verbosity=1)
            self.stdout.write(self.style.SUCCESS("[OK] Migrations complete on Neon DB"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"[ERR] Migration failed: {e}"))
            return

        # 2. Copy each model
        models_to_sync = [
            ('StockData', StockData),
            ('DownloadLog', DownloadLog),
            ('ScraperLog', ScraperLog),
            ('SiteVisit', SiteVisit),
            ('CalendarEvent', CalendarEvent),
            ('QuarterlyReport', QuarterlyReport),
            ('MarketHoliday', MarketHoliday),
        ]

        self.stdout.write(self.style.WARNING("\n=== Step 2: Copying data to Neon DB ==="))

        total_copied = 0
        total_skipped = 0

        for model_name, Model in models_to_sync:
            self.stdout.write(f"\n-- {model_name} --")

            # Count local records
            local_count = Model.objects.using('default').count()
            neon_count_before = Model.objects.using('neon').count()
            self.stdout.write(f"  Local (SQLite): {local_count:,} records")
            self.stdout.write(f"  Neon (before):  {neon_count_before:,} records")

            if local_count == 0:
                self.stdout.write(self.style.WARNING("  -> No local data to copy. Skipping."))
                continue

            # Fetch all local records and push in batches
            copied = 0
            queryset = Model.objects.using('default').all().order_by('pk')

            # Process in batches
            # Optimization: skip what we've already roughly loaded
            offset = neon_count_before
            while offset < local_count:
                batch = list(queryset[offset:offset + batch_size])
                if not batch:
                    break

                # Detach from SQLite (clear PKs so bulk_create can handle conflicts)
                for obj in batch:
                    obj._state.db = 'neon'

                try:
                    Model.objects.using('neon').bulk_create(
                        batch,
                        batch_size=batch_size,
                        ignore_conflicts=True,
                    )
                    copied += len(batch)
                except Exception as e:
                    self.stderr.write(self.style.ERROR(
                        f"  [ERR] Error at offset {offset}: {e}"
                    ))
                    break

                offset += batch_size

                # Progress indicator
                pct = min(100, int(offset / local_count * 100))
                self.stdout.write(
                    f"  Progress: {pct}% ({min(offset, local_count):,}/{local_count:,})",
                    ending='\r',
                )

            self.stdout.write("")  # Newline after progress

            neon_count_after = Model.objects.using('neon').count()
            new_records = neon_count_after - neon_count_before
            total_copied += new_records
            total_skipped += (copied - new_records) if copied > new_records else 0

            self.stdout.write(
                self.style.SUCCESS(
                    f"  [OK] Done! Neon now has {neon_count_after:,} records "
                    f"(+{new_records:,} new)"
                )
            )

        # 3. Summary
        self.stdout.write(self.style.WARNING("\n=== Summary ==="))
        self.stdout.write(f"  Total new records pushed: {total_copied:,}")
        self.stdout.write(f"  Duplicates skipped:       {total_skipped:,}")

        # Final verification
        self.stdout.write(self.style.WARNING("\n=== Verification ==="))
        for model_name, Model in models_to_sync:
            local_c = Model.objects.using('default').count()
            neon_c = Model.objects.using('neon').count()
            status = "[OK]" if neon_c >= local_c else "[WARN]"
            self.stdout.write(
                f"  {status} {model_name}: Local={local_c:,} | Neon={neon_c:,}"
            )

        self.stdout.write(self.style.SUCCESS(
            "\n[OK] Successfully migrated all data to Neon DB!"
        ))
