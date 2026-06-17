import argparse
import base64
import html
import json
import ssl
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


class ListmonkAPIError(Exception):
    """Erreur lors des appels à l'API Listmonk."""


class ListmonkClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout

    @property
    def auth_header(self) -> str:
        token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    def _request(self, path: str, method: str = "GET", payload: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        data = None
        headers = {
            "Authorization": self.auth_header,
            "Accept": "application/json",
        }

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url=url, data=data, headers=headers, method=method)

        try:
            with urlopen(request, timeout=self.timeout, context=ssl.create_default_context()) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            message = body
            try:
                parsed = json.loads(body)
                message = parsed.get("message") or parsed.get("error") or body
            except json.JSONDecodeError:
                pass
            raise ListmonkAPIError(f"Listmonk API a répondu {exc.code}: {message}") from exc
        except URLError as exc:
            raise ListmonkAPIError(f"Impossible de joindre Listmonk: {exc.reason}") from exc

    def get_lists(self) -> list[dict]:
        response = self._request("/api/lists")
        data = response.get("data", [])
        if isinstance(data, dict):
            data = data.get("results", [])

        lists = []
        for item in data:
            list_id = item.get("id")
            name = item.get("name")
            if list_id is None or not name:
                continue
            lists.append({"id": int(list_id), "name": str(name)})
        return lists

    def send_campaign(self, list_ids: list[int], from_email: str, subject: str, content: str) -> dict:
        now = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        payload = {
            "name": f"simpleMailing-{now}",
            "type": "regular",
            "subject": subject,
            "from_email": from_email,
            "content_type": "html",
            "body": content,
            "lists": list_ids,
        }
        creation_response = self._request("/api/campaigns", method="POST", payload=payload)

        campaign_id = (
            creation_response.get("data", {}).get("id")
            if isinstance(creation_response.get("data"), dict)
            else None
        )
        if campaign_id is None:
            raise ListmonkAPIError("La campagne a été créée, mais aucun identifiant n'a été retourné.")

        # Tentative de démarrage de la campagne.
        started = False
        for method in ("PUT", "POST"):
            try:
                self._request(
                    f"/api/campaigns/{campaign_id}/status",
                    method=method,
                    payload={"status": "running"},
                )
                started = True
                break
            except ListmonkAPIError:
                continue

        if not started:
            raise ListmonkAPIError(
                f"Campagne {campaign_id} créée mais impossible de la démarrer automatiquement."
            )

        return {"id": campaign_id}


class MailingHandler(BaseHTTPRequestHandler):
    server_version = "simpleMailing/1.0"

    def _read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        return parse_qs(body, keep_blank_values=True)

    def _render(self, html_content: str, status: int = 200) -> None:
        encoded = html_content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self._render("<h1>404</h1><p>Page introuvable</p>", status=404)
            return

        params = parse_qs(parsed.query)
        api_url = params.get("api_url", [""])[0].strip()
        username = params.get("username", [""])[0].strip()
        password = params.get("password", [""])[0].strip()

        lists = []
        message = ""
        error = ""

        if api_url and username and password:
            try:
                client = ListmonkClient(api_url, username, password)
                lists = client.get_lists()
                if not lists:
                    message = "Aucune liste disponible sur Listmonk."
            except ListmonkAPIError as exc:
                error = str(exc)

        self._render(
            build_page(
                api_url=api_url,
                username=username,
                password=password,
                lists=lists,
                message=message,
                error=error,
            )
        )

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/send":
            self._render("<h1>404</h1><p>Action introuvable</p>", status=404)
            return

        form = self._read_form()
        api_url = form.get("api_url", [""])[0].strip()
        username = form.get("username", [""])[0].strip()
        password = form.get("password", [""])[0].strip()
        from_email = form.get("from_email", [""])[0].strip()
        subject = form.get("subject", [""])[0].strip()
        body = form.get("body", [""])[0]

        raw_list_ids = [item for item in form.get("list_ids", []) if item.strip()]

        error = ""
        message = ""
        lists = []

        if not api_url or not username or not password:
            error = "Paramètres API incomplets."
        elif not raw_list_ids:
            error = "Sélectionnez au moins une liste."
        elif not from_email or not subject or not body:
            error = "Le formulaire d'envoi est incomplet."
        else:
            try:
                list_ids = [int(v) for v in raw_list_ids]
                client = ListmonkClient(api_url, username, password)
                send_result = client.send_campaign(
                    list_ids=list_ids,
                    from_email=from_email,
                    subject=subject,
                    content=body,
                )
                message = f"Campagne {send_result['id']} créée et démarrée."
            except (ValueError, ListmonkAPIError) as exc:
                error = str(exc)

        if api_url and username and password:
            try:
                lists = ListmonkClient(api_url, username, password).get_lists()
            except ListmonkAPIError as exc:
                if not error:
                    error = str(exc)

        self._render(
            build_page(
                api_url=api_url,
                username=username,
                password=password,
                lists=lists,
                message=message,
                error=error,
                form_values={
                    "from_email": from_email,
                    "subject": subject,
                    "body": body,
                    "selected_list_ids": raw_list_ids,
                },
            )
        )


def build_page(
    api_url: str,
    username: str,
    password: str,
    lists: list[dict],
    message: str = "",
    error: str = "",
    form_values: dict | None = None,
) -> str:
    values = form_values or {}
    selected_ids = set(values.get("selected_list_ids", []))

    escaped = {
        "api_url": html.escape(api_url),
        "username": html.escape(username),
        "password": html.escape(password),
        "from_email": html.escape(values.get("from_email", "")),
        "subject": html.escape(values.get("subject", "")),
        "body": html.escape(values.get("body", "")),
    }

    alerts = ""
    if message:
        alerts += f"<p style='color: #0a6d0a;'><strong>{html.escape(message)}</strong></p>"
    if error:
        alerts += f"<p style='color: #b30000;'><strong>{html.escape(error)}</strong></p>"

    options = ""
    for item in lists:
        item_id = str(item["id"])
        selected = " selected" if item_id in selected_ids else ""
        options += (
            f"<option value='{html.escape(item_id)}'{selected}>"
            f"{html.escape(item['name'])} (#{html.escape(item_id)})"
            "</option>"
        )

    query = urlencode({"api_url": api_url, "username": username, "password": password})

    send_form = ""
    if lists:
        send_form = f"""
        <h2>2) Préparer et envoyer une campagne</h2>
        <form method="post" action="/send">
            <input type="hidden" name="api_url" value="{escaped['api_url']}" />
            <input type="hidden" name="username" value="{escaped['username']}" />
            <input type="hidden" name="password" value="{escaped['password']}" />

            <label>Listes (multi-sélection):<br/>
                <select name="list_ids" multiple size="8" required style="min-width: 360px;">{options}</select>
            </label><br/><br/>

            <label>From email:<br/>
                <input type="email" name="from_email" value="{escaped['from_email']}" required style="min-width: 360px;"/>
            </label><br/><br/>

            <label>Objet:<br/>
                <input type="text" name="subject" value="{escaped['subject']}" required style="min-width: 360px;"/>
            </label><br/><br/>

            <label>Contenu HTML:<br/>
                <textarea name="body" rows="10" cols="80" required>{escaped['body']}</textarea>
            </label><br/><br/>

            <button type="submit">Envoyer</button>
        </form>
        """

    return f"""
    <!doctype html>
    <html lang="fr">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>simpleMailing</title>
    </head>
    <body style="font-family: Arial, sans-serif; margin: 2rem;">
      <h1>simpleMailing</h1>
      <p>Application web pour gérer l'envoi de mails via l'API Listmonk.</p>
      {alerts}

      <h2>1) Connexion Listmonk et chargement des listes</h2>
      <form method="get" action="/">
        <label>URL Listmonk (ex: http://localhost:9000):<br/>
            <input type="url" name="api_url" value="{escaped['api_url']}" required style="min-width: 360px;"/>
        </label><br/><br/>
        <label>Utilisateur API:<br/>
            <input type="text" name="username" value="{escaped['username']}" required style="min-width: 360px;"/>
        </label><br/><br/>
        <label>Mot de passe API:<br/>
            <input type="password" name="password" value="{escaped['password']}" required style="min-width: 360px;"/>
        </label><br/><br/>
        <button type="submit">Charger les listes</button>
      </form>

      {'<p><a href="/?' + html.escape(query) + '">Rafraîchir les listes</a></p>' if api_url and username and password else ''}
      {send_form}
    </body>
    </html>
    """


def run_server(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), MailingHandler)
    print(f"simpleMailing en écoute sur http://{host}:{port}")
    server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Application web simple pour piloter Listmonk")
    parser.add_argument("--host", default="127.0.0.1", help="Adresse d'écoute")
    parser.add_argument("--port", default=8080, type=int, help="Port d'écoute")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run_server(arguments.host, arguments.port)
