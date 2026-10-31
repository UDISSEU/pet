"""Pure parsing and matching rules for requests to open desktop apps."""

import re
import unicodedata


def app_open_target(question):
    match = re.match(
        r"^\s*(?:(?:quero|preciso)\s+|gostaria\s+de\s+|"
        r"voc(?:e|ê)\s+pode\s+|consegue\s+|pode\s+|poderia\s+)?"
        r"(?:(?:por\s+favor)[,:]?\s+)?"
        r"(?:abre|abra|abrir|inicia|inicie|iniciar|executa|execute|executar)"
        r"\s+(.+?)\s*[.!?]*\s*$",
        question,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def is_app_open_request(question):
    return bool(app_open_target(question))


def looks_like_app_target(question):
    target = app_open_target(question)
    if not target:
        return False
    words = re.findall(r"[\w.+-]+", target)
    if not words:
        return False
    articles = {"o", "a", "os", "as", "um", "uma", "uns", "umas", "the"}
    while words and words[0].casefold() in articles:
        words.pop(0)
    if not words:
        return False
    non_app_targets = {
        "codigo", "code", "sql", "script", "arquivo", "ficheiro", "html",
        "csv", "json", "python", "javascript", "css", "texto",
        "teste", "test", "projeto", "pandas", "jupyter", "notebook",
        "query", "dados",
    }
    normalized_words = [normalize(word) for word in words]
    if len(words) == 1:
        return normalized_words[0] not in non_app_targets
    return any(word[:1].isupper() for word in words)


def match_registered_app(question, saved_apps, get_installed_apps):
    target = app_open_target(question)
    if not target:
        return None
    normalized_question = normalize(target)

    def contains_phrase(text, phrase):
        return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))

    def match_apps(apps, allow_partial=False):
        named_apps = [
            (app, normalize(app.get("name", "").strip()))
            for app in apps
            if isinstance(app, dict)
            and isinstance(app.get("name"), str)
            and app["name"].strip()
        ]
        exact_matches = [
            (app, name) for app, name in named_apps
            if contains_phrase(normalized_question, name)
        ]
        if exact_matches:
            return max(exact_matches, key=lambda item: len(item[1]))[0], True

        # Google só identifica o Chrome quando não há outro candidato Google.
        google_matches = [
            app for app, name in named_apps
            if name == "google chrome" and contains_phrase(normalized_question, "google")
        ]
        google_candidates = [
            app for app, name in named_apps
            if contains_phrase(name, "google") and contains_phrase(normalized_question, "google")
        ]
        if len(google_matches) == 1 and len(google_candidates) == 1:
            return google_matches[0], True
        if allow_partial:
            partial_matches = [
                app for app, name in named_apps
                if any(contains_phrase(normalized_question, word) for word in re.findall(r"\w+", name))
            ]
            if len(partial_matches) == 1:
                return partial_matches[0], True
            return None, bool(partial_matches)
        return None, False

    def installed_apps():
        try:
            return get_installed_apps()
        except OSError:
            return []

    saved_match, has_saved_candidate = match_apps(saved_apps, allow_partial=True)
    if saved_match:
        if not saved_match.get("desktop_file"):
            saved_name = normalize(saved_match["name"])
            system_app = next(
                (
                    item for item in installed_apps()
                    if normalize(item.get("name", "")) == saved_name
                    and item.get("desktop_file")
                ),
                None,
            )
            if system_app:
                saved_match = {**saved_match, "desktop_file": system_app["desktop_file"]}
        return saved_match
    if has_saved_candidate:
        return None
    installed_match, _has_candidate = match_apps(installed_apps())
    return installed_match


def normalize(value):
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))
