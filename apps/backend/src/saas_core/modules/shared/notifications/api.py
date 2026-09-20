"""Public use-case API of the Notifications module.

A vertical sends its own e-mails through core's outbox: it registers its
templates and attachment resolvers from its `AppConfig.ready` and queues
messages with `queue_email` — never through the private models.
"""

from .attachments import Attachment, register_attachment_resolver
from .services import notify_in_app, queue_email
from .templates import EmailTemplate, register_email_template

__all__ = [
    "Attachment",
    "EmailTemplate",
    "notify_in_app",
    "queue_email",
    "register_attachment_resolver",
    "register_email_template",
]
