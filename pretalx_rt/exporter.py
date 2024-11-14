from pretalx.common.exporter import BaseExporter, CSVExporterMixin

from .models import Ticket


class Exporter(CSVExporterMixin, BaseExporter):
    identifier = "rt.csv"
    public = False
    icon = "fa-fa-check-square-o"
    cors = "*"

    @property
    def verbose_name(self):
        return "Request Tracker Data"

    @property
    def filename(self):
        return f"{self.event.slug}-rt.csv"

    def get_data(self, **kwargs):
        field_names = [
            "rt ticket",
            "rt subject",
            "rt status",
            "rt queue",
            "pretalx code",
            "pretalx title",
        ]
        data = []
        qs = Ticket.objects.all()
        for ticket in qs:
            code = None
            title = None
            if ticket.submission is not None:
                code = ticket.submission.code
                title = ticket.submission.title
            data.append(
                {
                    "rt ticket": ticket.id,
                    "rt subject": ticket.subject,
                    "rt status": ticket.status,
                    "rt queue": ticket.queue,
                    "pretalx code": code,
                    "pretalx title": title,
                }
            )
        return field_names, data
