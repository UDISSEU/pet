"""Read provider keys from the desktop Secret Service keyring."""

from contextlib import contextmanager
import logging
import sys

logger = logging.getLogger(__name__)

PROVIDERS = {
    "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
    "groq": ("groq_api_key", "GROQ_API_KEY"),
    "mistral": ("mistral_api_key", "MISTRAL_API_KEY"),
}


def _attributes(provider):
    return {"application": "desktop_pet_pixel_art", "purpose": PROVIDERS[provider][0]}


def _service(dbus):
    bus = dbus.SessionBus()
    try:
        proxy = bus.get_object("org.freedesktop.secrets", "/org/freedesktop/secrets")
        return bus, dbus.Interface(proxy, "org.freedesktop.Secret.Service")
    except Exception:
        try:
            bus.close()
        except Exception as exc:
            logger.warning("Não foi possível fechar a conexão Secret Service (%s)", type(exc).__name__)
        raise


def _open_session(dbus, service):
    return service.OpenSession("plain", dbus.String(""))[1]


@contextmanager
def _session_context(dbus):
    bus, service = _service(dbus)
    session = None
    try:
        session = _open_session(dbus, service)
        yield bus, service, session
    finally:
        operation_failed = sys.exc_info()[0] is not None
        cleanup_error = None
        if session is not None:
            try:
                service.Close(session)
            except Exception as exc:
                cleanup_error = exc
        try:
            bus.close()
        except Exception as exc:
            cleanup_error = cleanup_error or exc
        if cleanup_error is not None:
            if operation_failed:
                logger.warning(
                    "Não foi possível fechar a sessão Secret Service (%s)",
                    type(cleanup_error).__name__,
                )
            else:
                raise cleanup_error


def store(provider, value):
    import dbus

    with _session_context(dbus) as (bus, service, session):
        collection_path = service.ReadAlias("default")
        if collection_path == "/":
            raise RuntimeError("O cofre não tem uma coleção padrão.")
        collection = bus.get_object("org.freedesktop.secrets", collection_path)
        interface = dbus.Interface(collection, "org.freedesktop.Secret.Collection")
        properties = dbus.Dictionary({
            "org.freedesktop.Secret.Item.Label": dbus.String(f"Nova · {provider.title()} API key"),
            "org.freedesktop.Secret.Item.Attributes": dbus.Dictionary(_attributes(provider), signature="ss"),
        }, signature="sv")
        secret = dbus.Struct((
            dbus.ObjectPath(session), dbus.Array([], signature="y"),
            dbus.ByteArray(value.encode("utf-8")), dbus.String("text/plain"),
        ), signature="oayays")
        _item_path, prompt_path = interface.CreateItem(properties, secret, True)
        if prompt_path != "/":
            raise RuntimeError("O cofre precisa ser desbloqueado para guardar a chave.")


def load(provider):
    import dbus

    with _session_context(dbus) as (bus, service, session):
        unlocked, locked = service.SearchItems(dbus.Dictionary(_attributes(provider), signature="ss"))
        if locked:
            newly_unlocked, prompt_path = service.Unlock(locked)
            unlocked = list(unlocked) + list(newly_unlocked)
            if prompt_path != "/":
                raise RuntimeError("O cofre precisa ser desbloqueado para ler a chave.")
        if not unlocked:
            return ""
        item = bus.get_object("org.freedesktop.secrets", unlocked[0])
        secret = dbus.Interface(item, "org.freedesktop.Secret.Item").GetSecret(session)
        return bytes(secret[2]).decode("utf-8")


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("store", "load") or sys.argv[2] not in PROVIDERS:
        print("Uso: keyring_secret.py store|load gemini|groq|mistral", file=sys.stderr)
        return 2
    try:
        if sys.argv[1] == "store":
            value = sys.stdin.read().strip()
            if not value:
                raise RuntimeError("A chave recebida está vazia.")
            store(sys.argv[2], value)
        else:
            value = load(sys.argv[2])
            if value:
                sys.stdout.write(value)
    except Exception as exc:
        print(f"Não foi possível acessar o cofre do sistema: {type(exc).__name__}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
