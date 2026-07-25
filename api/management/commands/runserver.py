from django.core.management.commands.runserver import Command as DjangoRunserverCommand
from django.core.servers import basehttp


class HardenedWSGIRequestHandler(basehttp.WSGIRequestHandler):
    server_version = ""
    sys_version = ""

    def send_header(self, keyword, value):
        if keyword.lower() == "server":
            return
        super().send_header(keyword, value)


class Command(DjangoRunserverCommand):
    def inner_run(self, *args, **options):
        original_handler = basehttp.WSGIRequestHandler
        basehttp.WSGIRequestHandler = HardenedWSGIRequestHandler
        try:
            return super().inner_run(*args, **options)
        finally:
            basehttp.WSGIRequestHandler = original_handler