from typing import Final

#: Ask for a quote and order a translation (ADR-069 pkt 1).
TRANSLATION_REQUEST: Final = "translation.request"
#: The company's translation settings, its glossary and consent to the automation.
TRANSLATION_MANAGE: Final = "translation.manage"
#: 1,000 visible source characters × one target language (ADR-069 pkt 23).
CREDIT_OPERATION: Final = "translation.characters"
