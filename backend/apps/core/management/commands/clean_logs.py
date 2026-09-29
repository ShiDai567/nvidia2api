"""Delete old request logs to keep the SQLite database small.

Usage:
    python manage.py clean_logs --days 30        # delete logs older than 30 days
    python manage.py clean_logs --keep 100000    # keep newest 100000 rows
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import RequestLog


class Command(BaseCommand):
    help = "Clean old request logs"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30,
                            help="delete logs older than this many days (default 30)")
        parser.add_argument("--keep", type=int, default=0,
                            help="alternatively keep only the newest N rows")

    def handle(self, *args, **options):
        days = options["days"]
        keep = options["keep"]
        if keep:
            cutoff_id = (RequestLog.objects.order_by("-id")
                         .values_list("id", flat=True)[min(keep - 1, 0)] if keep else 0)
            total = RequestLog.objects.count()
            if keep < total:
                threshold = list(RequestLog.objects.order_by("-id")
                                 .values_list("id", flat=True)[keep - 1:keep])
                if threshold:
                    deleted, _ = RequestLog.objects.filter(id__lt=threshold[0]).delete()
                    self.stdout.write(self.style.SUCCESS(
                        f"deleted {deleted} logs (kept newest {keep})"))
                    return
            self.stdout.write("nothing to delete")
            return

        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = RequestLog.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"deleted {deleted} logs older than {days} days"))
