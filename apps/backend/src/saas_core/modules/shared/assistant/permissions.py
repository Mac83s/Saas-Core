from typing import Final

#: Talk to the assistant. It never widens what the person may do: every
#: command it proposes is checked against the person's own permissions.
ASSISTANT_USE: Final = "assistant.use"
#: The plan feature of the text chat (ADR-076 §8; billing 0026).
TEXT_FEATURE: Final = "assistant.text.enabled"
#: One turn of the daily assistant (billing 0016).
CREDIT_OPERATION: Final = "assistant.conversation_turn"
#: The model port task a conversation calls (ADR-068).
TASK: Final = "assistant.conversation"
