import logging

log = logging.getLogger("tenmina.messaging")


class ConsoleMessaging:
    """Logs SMS, WhatsApp and email instead of sending them (dev and tests)."""

    def send(self, message) -> bool:
        log.info("[%s] to %s: %s", message.channel, message.person or message.to_address, message.body[:200])
        return True


class ConsolePush(ConsoleMessaging):
    pass
