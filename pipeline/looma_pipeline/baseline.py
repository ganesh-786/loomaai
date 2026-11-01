"""Today's Looma search, called the way the Library Search page calls it, for side-by-side comparison (gate G8).

Import only. Sends `cmd=search` with the search form's 14 file types (Looma-II includes/looma-search.php) to
looma-database-utilities.php. That command only reads MongoDB. Side effects: one HTTP POST per query to
`LOOMA_WEB_URL`.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

SEARCH_FORM_TYPES = ("pdf", "video", "image", "audio", "history", "html", "slideshow", "map", "lesson", "looma",
                     "game", "text", "text-template", "worksheet")
LOOMA_COOKIES = "source=looma%20local; theme=looma%20local"  # without them Looma serves a bootstrap page
TIMEOUT_SECONDS = 10


class BaselineUnavailable(RuntimeError):
    """Looma's search could not be reached or did not return its usual JSON."""


def today_search(query: str, looma_web_url: str, timeout: float = TIMEOUT_SECONDS) -> tuple[int, list[str]]:
    """(result count, titles in Looma's order) for one query.

    Raises:
        BaselineUnavailable: on network errors or a non-JSON reply.
    """
    form = [("cmd", "search"), ("collection", "activities"), ("search-term", query)]
    form += [("type[]", ft) for ft in SEARCH_FORM_TYPES]
    request = urllib.request.Request(f"{looma_web_url}/looma-database-utilities.php",
                                     data=urllib.parse.urlencode(form).encode(), method="POST",
                                     headers={"Cookie": LOOMA_COOKIES})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BaselineUnavailable(f"{type(exc).__name__}: {exc}") from exc
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise BaselineUnavailable("reply was not JSON") from exc
    if not isinstance(data, dict):
        raise BaselineUnavailable(f"unexpected reply: {str(data)[:80]}")
    titles = [str(doc.get("dn") or doc.get("ndn") or "?") for doc in data.get("list", [])]
    return int(data.get("count", len(titles))), titles
