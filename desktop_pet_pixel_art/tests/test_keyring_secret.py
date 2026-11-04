import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import keyring_secret


class KeyringSecretTests(unittest.TestCase):
    def make_dbus(self, *, session_error=None):
        service = mock.Mock()
        service.OpenSession.side_effect = (
            session_error if session_error else None
        )
        service.OpenSession.return_value = (None, "/session/test")
        collection = mock.Mock()
        collection.CreateItem.return_value = ("/item/test", "/")
        item = mock.Mock()
        item.GetSecret.return_value = ("/session/test", [], b"secret", "text/plain")
        bus = mock.Mock()
        bus.get_object.side_effect = lambda _name, path: {
            "/org/freedesktop/secrets": service,
            "/collection/test": collection,
            "/item/test": item,
        }[path]
        dbus = SimpleNamespace(
            SessionBus=mock.Mock(return_value=bus),
            Interface=lambda proxy, _interface: proxy,
            String=str,
            Dictionary=lambda value, **_kwargs: value,
            ObjectPath=str,
            Array=lambda value, **_kwargs: value,
            ByteArray=bytes,
            Struct=lambda value, **_kwargs: value,
        )
        service.ReadAlias.return_value = "/collection/test"
        service.SearchItems.return_value = (["/item/test"], [])
        return dbus, bus, service

    def run_with_dbus(self, dbus, operation, provider="gemini", value="api-key"):
        with mock.patch.dict(sys.modules, {"dbus": dbus}):
            return operation(provider, value) if operation is keyring_secret.store else operation(provider)

    def test_store_and_load_close_secret_service_sessions(self):
        dbus, bus, service = self.make_dbus()
        self.run_with_dbus(dbus, keyring_secret.store)
        service.Close.assert_called_once_with("/session/test")
        bus.close.assert_called_once_with()

        dbus, bus, service = self.make_dbus()
        self.assertEqual(self.run_with_dbus(dbus, keyring_secret.load), "secret")
        service.Close.assert_called_once_with("/session/test")
        bus.close.assert_called_once_with()

    def test_session_and_bus_close_when_secret_service_operations_fail(self):
        dbus, bus, service = self.make_dbus()
        service.ReadAlias.side_effect = RuntimeError("service failed")
        with self.assertRaisesRegex(RuntimeError, "service failed"):
            self.run_with_dbus(dbus, keyring_secret.store)
        service.Close.assert_called_once_with("/session/test")
        bus.close.assert_called_once_with()

        dbus, bus, service = self.make_dbus()
        service.SearchItems.side_effect = RuntimeError("search failed")
        with self.assertRaisesRegex(RuntimeError, "search failed"):
            self.run_with_dbus(dbus, keyring_secret.load)
        service.Close.assert_called_once_with("/session/test")
        bus.close.assert_called_once_with()

    def test_bus_closes_when_opening_session_fails(self):
        dbus, bus, service = self.make_dbus(session_error=RuntimeError("open failed"))
        with self.assertRaisesRegex(RuntimeError, "open failed"):
            self.run_with_dbus(dbus, keyring_secret.load)
        service.Close.assert_not_called()
        bus.close.assert_called_once_with()

    def test_cleanup_failure_does_not_mask_secret_service_error(self):
        dbus, bus, service = self.make_dbus()
        service.SearchItems.side_effect = RuntimeError("search failed")
        service.Close.side_effect = RuntimeError("close failed")
        with self.assertLogs(keyring_secret.logger, level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "search failed"):
                self.run_with_dbus(dbus, keyring_secret.load)
        bus.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
