"""Only operating-system vaults; no plaintext fallback or implicit env scan."""
from __future__ import annotations


class SystemCredentials:
    service_name = "ScientificDataflowInspector"
    supported = {"keyring.backends.Windows", "keyring.backends.macOS", "keyring.backends.SecretService", "keyring.backends.kwallet"}

    def _backend(self):
        try:
            import keyring
            backend = keyring.get_keyring()
            candidates = getattr(backend, "backends", (backend,))
            for candidate in candidates:
                if type(candidate).__module__ in self.supported and candidate.priority > 0:
                    return candidate
        except Exception:
            pass
        raise ValueError("System credential store unavailable; select an environment reference or restore the OS vault")

    def put(self, reference, secret):
        try:
            self._backend().set_password(self.service_name, reference, secret)
        except Exception as error:
            raise ValueError("System credential store unavailable; the key was not saved to a file") from error

    def get(self, reference):
        try:
            return self._backend().get_password(self.service_name, reference)
        except Exception:
            return None

    def delete(self, reference):
        try:
            self._backend().delete_password(self.service_name, reference)
        except Exception:
            pass
