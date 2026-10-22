"""Webhook credentials live in the OS credential store, never diagnostic exports."""
from threading import RLock


class CredentialStore:
    def __init__(self, backend=None, service="PyWeatherAlert"):
        if backend is None:
            try:
                import keyring
                backend = keyring
            except ImportError:
                backend = None
        self.backend = backend
        self.service = service
        self._session = {}
        self._lock = RLock()

    def session_value(self, channel):
        with self._lock:
            return self._session.get(channel, "")

    def set_session(self, channel, value):
        with self._lock:
            self._session[channel] = value

    def get(self, channel):
        with self._lock:
            if channel in self._session:
                return self._session[channel]
            if self.backend is None:
                return ""
            try:
                return self.backend.get_password(self.service, channel) or ""
            except Exception:
                return ""

    def set(self, channel, value):
        """Return whether the value was securely persisted; retain session use on failure."""
        with self._lock:
            self._session[channel] = value
            if self.backend is None:
                return not value
            try:
                if value:
                    self.backend.set_password(self.service, channel, value)
                elif self.backend.get_password(self.service, channel):
                    self.backend.delete_password(self.service, channel)
                return True
            except Exception:
                return False

    def resolve(self, reference):
        if not reference.startswith("credential:"):
            raise ValueError("Expected an OS credential reference")
        value = self.get(reference.partition(":")[2])
        if not value:
            raise ValueError("Webhook credential unavailable; configure the channel in Preferences")
        return value
