from django.apps import AppConfig
from django.utils.translation import gettext_lazy

from . import __version__


class PluginApp(AppConfig):
    name = "pretalx_rt"
    verbose_name = "pretalx RT"

    class PretalxPluginMeta:
        name = "pretalx RT"
        author = "Florian Mösch"
        description = gettext_lazy(
            "This plugin allows you to use the RT issue tracker for communication with speakers. pretalx RT will be "
            "used to send out all notifications that would normally be sent out as mail via RT instead of SMTP - with "
            "the exception of mails that will be sent out to reset passwords. Those will still be sent out via SMTP "
            "directly."
            "\n"
            "Information regarding the corresponding RT ticket will be included in the submission and speaker forms "
            "in the pretalx orga interface. The plugin will keep track of the RT ticket related to each submission "
            "and will reuse that ticket for all notifications that are sent out to the speakers."
            "\n"
            "New tickets will be automatically created when a new submission is created or for notifications that "
            "are not related to a submission but directly adressed to a person instead."
        )
        visible = True
        version = __version__
        category = "INTEGRATION"

    def ready(self):
        from . import sync_signals  # NOQA
        from . import ui_signals  # NOQA
