"""The CORS policy is a security boundary, so it gets tests.

The front-end students build is published on hosting nobody here controls:
Figma assigns a random subdomain per site, and a *new* one when a site is
republished. So an exact allow-list means an ops change every time someone
clicks publish — which is how this arrived as a bug report, with a preflight
answered `400 Disallowed CORS origin` and no `Access-Control-Allow-Origin`.

What is checked here is which origins the running middleware admits, for both
the exact list and the pattern. The pattern's *anchoring* is not checked here
and cannot be: Starlette matches with `re.fullmatch`, so a request-level test
cannot tell an anchored pattern from an unanchored one. That property belongs
to `_origin_regex` and is asserted directly in test_config.py.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

FIGMA_REGEX = r"^https://[a-z0-9-]+\.figma\.site$"
PUBLISHED = "https://thorn-snout-04735436.figma.site"
OWN_DOMAIN = "https://hoopai.ithacateens.com"


@pytest.fixture
def cors_app(monkeypatch):
    """Build a TestClient carrying the real CORS policy over a stub route.

    Deliberately not the `client` fixture: that imports `backend.main`, which
    installs the middleware from `config` at import time and caches the module,
    so a later monkeypatch of the settings changes nothing. Calling `add_cors`
    against a fresh app reads the settings now — and reads them through the
    same function production uses, so the two cannot drift apart.

    `origin_regex` is the *environment* value, passed through the real
    `_origin_regex`, so these tests exercise the wrap rather than a hand-built
    imitation of what it produces.
    """
    from backend import config, main

    def _build(origins: list[str], origin_regex: str | None = None) -> TestClient:
        monkeypatch.setattr(config, "CORS_ORIGINS", origins)

        effective = None
        if origin_regex is not None:
            monkeypatch.setenv("HOOPAI_CORS_ORIGIN_REGEX", origin_regex)
            effective = config._origin_regex("HOOPAI_CORS_ORIGIN_REGEX")
        monkeypatch.setattr(config, "CORS_ORIGIN_REGEX", effective)

        app = FastAPI()
        main.add_cors(app)

        @app.post("/probe")
        def probe() -> dict[str, bool]:
            return {"ok": True}

        return TestClient(app)

    return _build


def _preflight(client: TestClient, origin: str, headers: str = "content-type"):
    return client.options(
        "/probe",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": headers,
        },
    )


def _allowed(response) -> bool:
    """Starlette answers an acceptable preflight 200 and a refused one 400.

    Both halves matter: the header alone can be absent on a 200 for a request
    that was never a preflight, and a 400 never carries it.
    """
    return response.status_code == 200 and "access-control-allow-origin" in response.headers


# -- The exact list -----------------------------------------------------------


def test_a_listed_origin_passes_preflight(cors_app):
    with cors_app([OWN_DOMAIN, PUBLISHED]) as client:
        response = _preflight(client, PUBLISHED)
        assert _allowed(response)
        assert response.headers["access-control-allow-origin"] == PUBLISHED


def test_an_unlisted_origin_is_refused(cors_app):
    with cors_app([OWN_DOMAIN]) as client:
        assert not _allowed(_preflight(client, "https://evil.example.com"))


def test_a_list_entry_with_a_trailing_slash_never_matches(cors_app):
    """The mistake that makes the fix look like it didn't work.

    An `Origin` header is scheme + host + optional port and never carries a
    path, so `https://site/` in the allow-list matches nothing at all. Pasting
    the front-end's URL straight out of the address bar produces exactly that,
    and the symptom is identical to not having edited the config.
    """
    with cors_app([PUBLISHED + "/"]) as client:
        assert not _allowed(_preflight(client, PUBLISHED))


# -- The pattern --------------------------------------------------------------


def test_the_pattern_admits_a_published_figma_site(cors_app):
    with cors_app([OWN_DOMAIN], FIGMA_REGEX) as client:
        response = _preflight(client, PUBLISHED)
        assert _allowed(response)
        assert response.headers["access-control-allow-origin"] == PUBLISHED


def test_the_pattern_admits_a_republished_site_under_a_new_subdomain(cors_app):
    """The whole point: a new random subdomain needs no ops change."""
    with cors_app([OWN_DOMAIN], FIGMA_REGEX) as client:
        assert _allowed(_preflight(client, "https://some-other-name-99887766.figma.site"))


@pytest.mark.parametrize(
    "origin",
    [
        # A domain the attacker owns, wearing the pattern as a prefix.
        "https://anything.figma.site.attacker.example",
        # Suffix-glued rather than a subdomain.
        "https://notfigma.site",
        # No subdomain at all: `[a-z0-9-]+` requires one label.
        "https://figma.site",
        # A subdomain of a subdomain — the dot is not in the character class.
        "https://a.b.figma.site",
        # Plaintext. The pattern pins the scheme.
        "http://thorn-snout-04735436.figma.site",
        # A port makes it a different origin, and the pattern allows none.
        "https://thorn-snout-04735436.figma.site:8443",
    ],
)
def test_the_pattern_refuses_lookalike_origins(cors_app, origin):
    """That the character classes are tight enough to mean what they look like.

    `Origin` is input the server has to defend, not something the browser
    vouches for, so a value no real page could produce (the plaintext one) is
    still worth refusing — a non-browser client can send any string here.
    """
    with cors_app([OWN_DOMAIN], FIGMA_REGEX) as client:
        assert not _allowed(_preflight(client, origin)), origin


def test_an_unanchored_environment_value_still_refuses_the_lookalikes(cors_app):
    """Whoever sets the variable is not required to anchor it themselves.

    `_origin_regex` wraps whatever it is given, so the shorter form behaves the
    same. test_config.py is where that wrap is pinned down; this is the
    end-to-end confirmation that nothing between here and the middleware
    discards it.
    """
    with cors_app([OWN_DOMAIN], r"https://[a-z0-9-]+\.figma\.site") as client:
        assert _allowed(_preflight(client, PUBLISHED))
        assert not _allowed(_preflight(client, "https://anything.figma.site.attacker.example"))


def test_the_exact_list_still_works_alongside_a_pattern(cors_app):
    """Starlette checks the pattern *and* the list; neither shadows the other."""
    with cors_app([OWN_DOMAIN], FIGMA_REGEX) as client:
        assert _allowed(_preflight(client, OWN_DOMAIN))


# -- The rest of the policy ---------------------------------------------------


def test_the_real_response_carries_the_origin_header_too(cors_app):
    """A passing preflight is only half of it.

    Starlette decides twice — once in `preflight_response` for the OPTIONS,
    and again in `send` for the response the browser actually reads. The
    second one is what the front-end needs, and testing only the first is how
    a policy gets to look correct while not working, which is the history this
    file exists because of.
    """
    with cors_app([PUBLISHED]) as client:
        response = client.post("/probe", headers={"Origin": PUBLISHED})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == PUBLISHED


def test_the_real_response_withholds_it_from_an_unlisted_origin(cors_app):
    """The request still runs — CORS gates what the browser may *read*."""
    with cors_app([OWN_DOMAIN]) as client:
        response = client.post("/probe", headers={"Origin": "https://evil.example.com"})
        assert "access-control-allow-origin" not in response.headers


def test_the_authorization_header_survives_preflight(cors_app):
    """Every authenticated call sends it; a preflight that drops it blocks login."""
    with cors_app([PUBLISHED]) as client:
        response = _preflight(client, PUBLISHED, headers="authorization,content-type")
        assert _allowed(response)
        assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_credentials_stay_off(cors_app):
    """What makes a pattern over shared hosting tolerable.

    The API authenticates with a Bearer header, not a cookie. With credentials
    off, a browser will not attach one cross-origin, so admitting an origin
    grants it calls that anything with a network connection could already
    make — and not the ability to act as a logged-in student.
    """
    with cors_app([PUBLISHED]) as client:
        assert "access-control-allow-credentials" not in _preflight(client, PUBLISHED).headers
