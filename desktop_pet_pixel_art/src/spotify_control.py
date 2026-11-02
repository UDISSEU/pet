"""Local Spotify playback and playlist actions using OAuth PKCE."""

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


REDIRECT_URI = "http://127.0.0.1:8765/callback"
SCOPES = "playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public"
TOKEN_PATH = Path.home() / ".config" / "desktop_pet" / "spotify_token.json"
API_ROOT = "https://api.spotify.com/v1"


class SpotifyError(Exception):
    pass


def parse_spotify_command(question):
    """Recognize Portuguese Spotify requests despite common conjugation errors."""
    import unicodedata

    raw = " ".join(str(question or "").strip().split())
    folded = "".join(
        char for char in unicodedata.normalize("NFKD", raw.casefold())
        if not unicodedata.combining(char)
    )
    spotify_requested = bool(re.search(r"\bspotify\b", folded))
    verbs = list(re.finditer(
        r"\b(adicion\w*|coloc\w*|bota\w*|jog\w*|poe|poem|toca\w*|"
        r"reproduz\w*|executa\w*|abri|abre|abrir|play)\b", folded,
    ))
    if not verbs:
        return None
    verb = next(
        (item for item in verbs if item.group(1) not in ("abri", "abre", "abrir")),
        verbs[-1],
    )
    action = verb.group(1)
    adding = action.startswith(("adicion", "coloc", "bota", "jog", "poe", "poem"))
    playlist_match = re.search(
        r"\b(?:na|em|a|para|pra)\s+(?:a\s+)?(?:minha\s+)?playlist\b|"
        r"\bplaylist\s+(?:minha|chamada|com\s+nome)\b", folded,
    )
    playlist_link = re.search(
        r"https?://open\.spotify\.com/playlist/[a-z0-9]+(?:\?[^\s]*)?"
        r"|spotify:playlist:[a-z0-9]+", folded,
    )
    if playlist_link:
        playlist_match = playlist_link
    play_cue_before_playlist = playlist_match and any(
        item.group(1).startswith(("toca", "reproduz", "executa", "play"))
        and item.start() < playlist_match.start()
        for item in verbs
    )
    play_cue = any(item.group(1).startswith(("toca", "reproduz", "executa", "play")) for item in verbs)

    def original_index(normalized_index):
        count = 0
        for index, char in enumerate(raw):
            expanded = "".join(
                item for item in unicodedata.normalize("NFKD", char.casefold())
                if not unicodedata.combining(item)
            )
            if count + len(expanded) > normalized_index:
                return index
            count += len(expanded)
        return len(raw)

    if spotify_requested and adding and playlist_match and not play_cue_before_playlist:
        operation = "add"
    elif spotify_requested and re.search(r"\b(playlist|lista)\b", folded) and play_cue:
        operation = "play"
        if not playlist_link:
            playlist_match = re.search(r"\b(?:playlist|lista)(?:\s+(?:chamada|de\s+nome))?\s*", folded)
    elif spotify_requested and action in ("abri", "abre", "abrir") and re.search(r"\b(playlist|lista)\b", folded):
        operation = "play"
        if not playlist_link:
            playlist_match = re.search(r"\b(?:playlist|lista)(?:\s+(?:chamada|de\s+nome))?\s*", folded)
    elif (
        not playlist_match
        and not re.search(r"\b(playlist|lista)\b", folded)
        and action not in ("abri", "abre", "abrir")
        and (
            action.startswith(("toca", "reproduz", "play"))
            or re.search(r"\b(musica|faixa|cancao|som)\b", folded)
            or spotify_requested
        )
    ):
        track_start = original_index(verb.end())
        track = raw[track_start:]
        track = re.sub(
            r"(?i)^\s*(?:(?:a|uma|um)\s+)?(?:musica|música|faixa|cancao|canção|som)\b",
            "",
            track,
        )
        track = re.sub(r"(?i)^\s*(?:do|da|de)\s+", "", track)
        track = re.sub(
            r"(?i)\s+(?:(?:no|do|para o|pro)\s+)?spotify\s*$", "", track
        )
        track = re.sub(r"(?i)\s+(?:pra|para)\s+(?:tocar|reproduzir)\s*$", "", track)
        track = re.sub(r"(?i)\s+por favor\s*$", "", track)
        track = track.strip(" \t,;:-.!?\"'“”‘’()")
        return {"operation": "play_track", "track": track}
    else:
        return None

    if operation == "add":
        track_end = original_index(playlist_match.start())
        track_start = original_index(verb.end())
        track = raw[track_start:track_end]
        track = re.sub(r"(?i)^\s*(?:a\s+)?(?:musica|música|faixa|cancao|canção)\s+", "", track)
        track = re.sub(r"(?i)^\s*(?:do|da|de)\s+", "", track).strip(" \t,;:-.!?\"'“”‘’()")
        if playlist_link:
            playlist = raw[
                original_index(playlist_link.start()):original_index(playlist_link.end())
            ].strip(" \t,;:-.!?\"'“”‘’()")
        else:
            playlist_start = original_index(playlist_match.end())
            playlist = raw[playlist_start:].strip(" \t,;:-.!?\"'“”‘’()")
            playlist = re.sub(r"(?i)^(?:chamada|com\s+nome)\s+", "", playlist)
            playlist = re.sub(r"(?i)^(?:spotify\s+)?(?:e\s+)?", "", playlist).strip(" \t,;:-.!?\"'“”‘’()")
        return {"operation": operation, "track": track, "playlist": playlist}

    if playlist_link:
        playlist = raw[
            original_index(playlist_link.start()):original_index(playlist_link.end())
        ].strip(" \t,;:-.!?\"'“”‘’()")
    else:
        playlist_start = original_index(playlist_match.end()) if playlist_match else len(raw)
        playlist = raw[playlist_start:].strip(" \t,;:-.!?\"'“”‘’()")
        playlist = re.sub(r"(?i)^(?:spotify\s+)?(?:e\s+)?", "", playlist).strip(" \t,;:-.!?\"'“”‘’()")
    # Requests like “toca minha playlist” have no name: let the UI ask.
    playlist = re.sub(
        r"(?i)\s+(?:(?:do|no)(?:\s+meu)?)?\s*spotify\s*$", "", playlist
    ).strip()
    if playlist.casefold() in ("minha", "a minha", "minha playlist"):
        playlist = ""
    return {"operation": operation, "playlist": playlist}


def _save_token(data):
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".spotify-token-", dir=TOKEN_PATH.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
        Path(temporary_name).replace(TOKEN_PATH)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    os.chmod(TOKEN_PATH, 0o600)


def connect_spotify(client_id, timeout=180):
    """Authorize this desktop app with PKCE; no client secret is stored."""
    client_id = str(client_id or "").strip()
    if not client_id:
        raise SpotifyError("Informe o Client ID do aplicativo Spotify primeiro.")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    result = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            result["code"] = params.get("code", [None])[0]
            result["state"] = params.get("state", [None])[0]
            result["error"] = params.get("error", [None])[0]
            payload = ("Autorização concluída. Você pode fechar esta janela." if result.get("code")
                       else "A autorização não foi concluída. Volte ao aplicativo da Nova.")
            body = f"<html><meta charset='utf-8'><title>Spotify</title><p>{payload}</p></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    try:
        server = HTTPServer(("127.0.0.1", 8765), CallbackHandler)
    except OSError as exc:
        raise SpotifyError("A porta local 8765 está ocupada; feche o outro processo e tente de novo.") from exc
    server.timeout = timeout
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)
    try:
        if not webbrowser.open(auth_url):
            raise SpotifyError("Não consegui abrir o navegador para autorizar o Spotify.")
        thread.join(timeout)
    finally:
        server.server_close()
    if thread.is_alive() or not result.get("code"):
        raise SpotifyError("A autorização Spotify expirou ou foi cancelada.")
    if result.get("state") != state:
        raise SpotifyError("A resposta de autorização não corresponde a esta sessão.")
    form = urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }).encode()
    token = _request("https://accounts.spotify.com/api/token", data=form)
    token["client_id"] = client_id
    token["expires_at"] = time.time() + int(token.get("expires_in", 3600))
    _save_token(token)


def spotify_connected(client_id):
    try:
        token = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        return token.get("client_id") == str(client_id or "").strip() and bool(token.get("refresh_token"))
    except (OSError, json.JSONDecodeError):
        return False


def _request(url, token=None, data=None, method=None, body=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=data if data is not None else json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            detail = ""
        if exc.code == 401:
            raise SpotifyError("A autorização Spotify expirou. Conecte a conta novamente.") from exc
        if exc.code == 403:
            raise SpotifyError("O Spotify recusou a ação. Para tocar playlists, use uma conta Premium e deixe um dispositivo ativo.") from exc
        if exc.code == 404:
            raise SpotifyError("O Spotify não encontrou esse item ou nenhum dispositivo está ativo.") from exc
        if exc.code == 429:
            raise SpotifyError("O Spotify pediu para aguardar antes de tentar outra vez.") from exc
        raise SpotifyError(detail or f"O Spotify respondeu com erro {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SpotifyError("Não consegui acessar o Spotify. Confira a conexão com a internet.") from exc


def _access_token(client_id):
    try:
        token = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpotifyError("Conecte sua conta Spotify nas preferências da Nova primeiro.") from exc
    if token.get("client_id") != str(client_id or "").strip():
        raise SpotifyError("O Client ID mudou. Conecte sua conta Spotify novamente.")
    if token.get("expires_at", 0) > time.time() + 60:
        return token["access_token"]
    refreshed = _request("https://accounts.spotify.com/api/token", data=urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": token.get("refresh_token", ""),
    }).encode())
    token.update(refreshed)
    token["client_id"] = client_id
    token["expires_at"] = time.time() + int(refreshed.get("expires_in", 3600))
    _save_token(token)
    return token["access_token"]


def _api(client_id, path, method=None, body=None):
    token = _access_token(client_id)
    return _request(API_ROOT + path, token=token, method=method, body=body)


def _best_match(items, query, kind):
    if not items:
        raise SpotifyError(f"Não encontrei {kind} com esse nome na sua conta Spotify.")
    needle = " ".join(query.casefold().split())
    scored = []
    for item in items:
        name = " ".join(str(item.get("name", "")).casefold().split())
        artists = ", ".join(
            artist.get("name", "") for artist in item.get("artists", [])
            if isinstance(artist, dict)
        )
        label = " ".join(part.casefold() for part in (name, artists) if part)
        score = max(
            SequenceMatcher(None, needle, name).ratio(),
            SequenceMatcher(None, needle, label).ratio(),
        )
        if needle in name or name in needle:
            score = max(score, 0.82)
        scored.append((score, item, label))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored[0][0] < 0.62:
        raise SpotifyError(f"Não achei uma correspondência segura para {kind}. Tente dizer o nome mais completo.")
    if (len(scored) > 1 and scored[0][0] - scored[1][0] < 0.045
            and (scored[0][2] != scored[1][2]
                 or scored[0][1].get("uri") != scored[1][1].get("uri"))):
        raise SpotifyError(f"Encontrei mais de uma opção para {kind}. Diga o nome completo para eu escolher com segurança.")
    return scored[0][1]


def _find_playlist(client_id, query):
    playlists = []
    offset = 0
    while offset < 1000:
        page = _api(client_id, f"/me/playlists?limit=50&offset={offset}")
        items = page.get("items", [])
        playlists.extend(item for item in items if item and item.get("id"))
        if not page.get("next") or not items:
            break
        offset += len(items)
    return _best_match(playlists, query, "uma playlist")


def _find_track(client_id, query):
    params = urllib.parse.urlencode({"q": query, "type": "track", "limit": 10})
    result = _api(client_id, "/search?" + params)
    tracks = result.get("tracks", {}).get("items", [])
    return _best_match(tracks, query, "essa música")


def playlist_uri_from_input(value):
    value = str(value or "").strip()
    match = re.search(r"spotify:playlist:([A-Za-z0-9]+)", value)
    if match:
        return f"spotify:playlist:{match.group(1)}"
    parsed = urllib.parse.urlparse(value)
    if parsed.hostname and parsed.hostname.casefold() in ("open.spotify.com", "www.open.spotify.com"):
        match = re.search(r"/playlist/([A-Za-z0-9]+)", parsed.path)
        if match:
            return f"spotify:playlist:{match.group(1)}"
    # IDs copied from Spotify's developer documentation are also useful here:
    # the command already establishes that this opaque ID refers to a playlist.
    if re.fullmatch(r"[A-Za-z0-9]{22}", value):
        return f"spotify:playlist:{value}"
    return ""


def _play_spotify_uri_locally(uri, item_url, description):
    """Open a Spotify URI locally and start playback through MPRIS when available."""
    spotify = shutil.which("spotify")
    opener = shutil.which("xdg-open") or shutil.which("gio")
    if spotify:
        try:
            process = subprocess.Popen(
                [spotify, uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            time.sleep(0.4)
            if process.poll() not in (None, 0):
                raise SpotifyError("O aplicativo Spotify encerrou ao tentar abrir o conteúdo.")
        except OSError as exc:
            raise SpotifyError(f"Não consegui iniciar o Spotify: {exc}") from exc
        opened_message = f"Abri o Spotify com {description}."
    elif opener:
        try:
            command = [opener, item_url] if opener.endswith("xdg-open") else [opener, "open", item_url]
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
            if result.returncode:
                details = (result.stderr or result.stdout or "").strip()
                raise SpotifyError(details or "O sistema não conseguiu abrir o link do Spotify.")
        except (OSError, subprocess.SubprocessError) as exc:
            raise SpotifyError(f"Não consegui abrir o link do Spotify: {exc}") from exc
        opened_message = f"Abri o link de {description} no aplicativo associado pelo sistema."
    else:
        raise SpotifyError("Não encontrei Spotify nem um abridor de links (xdg-open/gio) neste Linux.")

    time.sleep(2.0)
    gdbus = shutil.which("gdbus")
    if gdbus:
        common = [
            gdbus, "call", "--session", "--dest", "org.mpris.MediaPlayer2.spotify",
            "--object-path", "/org/mpris/MediaPlayer2",
        ]
        try:
            subprocess.run(
                [*common, "--method", "org.mpris.MediaPlayer2.Player.OpenUri", repr(uri)],
                check=True, capture_output=True, timeout=10,
            )
            subprocess.run(
                [*common, "--method", "org.mpris.MediaPlayer2.Player.Play"],
                check=True, capture_output=True, timeout=10,
            )
            return f"Comecei a tocar {description} no aplicativo Spotify."
        except (OSError, subprocess.SubprocessError):
            pass
    return f"{opened_message} Se ele abriu no navegador, toque em Reproduzir por lá; o controle automático de mídia não está disponível."


def _play_playlist_locally(uri):
    """Use Spotify's desktop client via its URI/MPRIS, which avoids Premium API playback."""
    playlist_id = uri.rsplit(":", 1)[-1]
    return _play_spotify_uri_locally(
        uri,
        f"https://open.spotify.com/playlist/{playlist_id}",
        "sua playlist",
    )


def _play_track_locally(track):
    track_id = track["id"]
    artists = ", ".join(
        artist.get("name", "") for artist in track.get("artists", [])
        if isinstance(artist, dict) and artist.get("name")
    )
    description = f"{track.get('name', 'a música')} — {artists}" if artists else track.get("name", "a música")
    return _play_spotify_uri_locally(
        track["uri"],
        f"https://open.spotify.com/track/{track_id}",
        description,
    )


def execute_spotify_action(client_id, operation, playlist_query, track_query=""):
    if operation == "play_track":
        if not track_query.strip():
            raise SpotifyError("Qual música você quer ouvir? Diga o nome da faixa e, se souber, o artista.")
        return _play_track_locally(_find_track(client_id, track_query))
    if operation == "play":
        local_uri = playlist_uri_from_input(playlist_query)
        if local_uri:
            return _play_playlist_locally(local_uri)
    local_uri = playlist_uri_from_input(playlist_query)
    if local_uri and operation == "add":
        playlist_id = local_uri.rsplit(":", 1)[-1]
        playlist = {"id": playlist_id, "uri": local_uri, "name": playlist_query}
    else:
        playlist = _find_playlist(client_id, playlist_query)
    if operation == "play":
        return _play_playlist_locally(playlist["uri"])
    if operation == "add":
        if not track_query.strip():
            raise SpotifyError("Qual música você quer adicionar? Diga, por exemplo: ‘adiciona Blinding Lights na playlist Favoritas’.")
        track = _find_track(client_id, track_query)
        _api(
            client_id, f"/playlists/{urllib.parse.quote(playlist['id'], safe='')}/items",
            method="POST", body={"uris": [track["uri"]]},
        )
        artists = ", ".join(item.get("name", "") for item in track.get("artists", []))
        return f"Adicionei {track['name']} — {artists} à playlist {playlist['name']}."
    raise SpotifyError("Não entendi se você quer tocar ou adicionar música.")
