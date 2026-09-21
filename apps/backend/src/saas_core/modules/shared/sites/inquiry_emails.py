from saas_core.modules.shared.notifications.api import EmailTemplate, register_email_template


def register_inquiry_email() -> None:
    register_email_template(
        EmailTemplate(
            key="sites.inquiry_received",
            version=1,
            category="required",
            subjects={"pl": "Nowe zapytanie ze strony", "en": "New website inquiry"},
            bodies={
                "pl": (
                    "<p>Na stronie {site_name} otrzymano nowe zapytanie.</p>"
                    "<p>Nadawca: {name}<br>E-mail: {email}<br>Telefon: {phone}</p>"
                    "<p>{message}</p><p>Numer zgłoszenia: {reference}</p>"
                    "<p>Zgłoszenie jest również dostępne w panelu strony.</p>"
                ),
                "en": (
                    "<p>A new inquiry was received on {site_name}.</p>"
                    "<p>Sender: {name}<br>Email: {email}<br>Phone: {phone}</p>"
                    "<p>{message}</p><p>Reference: {reference}</p>"
                    "<p>The inquiry is also available in the website panel.</p>"
                ),
            },
            allowed_context=frozenset({
                "site_name",
                "name",
                "email",
                "phone",
                "message",
                "reference",
            }),
        )
    )
