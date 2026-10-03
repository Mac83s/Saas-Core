"""Public use-case API of the Notifications module.

A vertical sends its own e-mails through core's outbox: it registers its
templates and attachment resolvers from its `AppConfig.ready` and queues
messages with `queue_email` — never through the private models.
"""

from .attachments import Attachment, register_attachment_resolver
from .customer_mail import public_url, register_customer_sender
from .retention_notice import announce_retention, scrub_messages
from .services import notify_in_app, queue_email, staff_locale
from .templates import (
    AUDIENCE_CUSTOMER,
    AUDIENCE_STAFF,
    TEMPLATES,
    EmailTemplate,
    register_email_template,
    resolve_template_locale,
)

__all__ = [
    "AUDIENCE_CUSTOMER",
    "AUDIENCE_STAFF",
    "TEMPLATES",
    "Attachment",
    "announce_retention",
    "scrub_messages",
    "EmailTemplate",
    "notify_in_app",
    "queue_email",
    "register_attachment_resolver",
    "public_url",
    "register_customer_sender",
    "register_email_template",
    "resolve_template_locale",
    "staff_locale",
]
