"""Delete old request logs to keep the SQLite database small.

Usage:
    python manage.py clean_logs --days 30        # delete logs older than 30 days
    python manage.py clean_logs --keep 100000    # keep newest 100000 rows
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import RequestLog
from services import sysconfig
from services.request_logs import delete_expired


class Command(BaseCommand):
    help = "Clean old request logs"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, help="保留天数，默认使用面板设置，0 表示全部保存")
        parser.add_argument("--keep", type=int, default=0,
                            help="alternatively keep only the newest N rows")

    def handle(self, *args, **options):
        days = options["days"]
        keep = options["keep"]
        if keep < 0 or (days is not None and days < 0):
            raise CommandError("天数和条数必须为非负整数")
        if keep:
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

        if days is None:
            days = sysconfig.get("log_retention_days")
        deleted = delete_expired(days)
        self.stdout.write(self.style.SUCCESS(f"deleted {deleted} logs older than {days} days"))
