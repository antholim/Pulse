"""Hand-written Omerlo detail payloads shaped like the backoffice documentation.

All values are synthetic. Each builder returns a fresh payload, so a test can
break one field without affecting the others.
"""

from typing import Any

WORKSPACE_ID = "ws-capitale"


def contact(locale: str, **fields: Any) -> dict[str, Any]:
    empty = dict.fromkeys(
        ("email", "phone", "facebook", "linkedin", "instagram", "twitter", "bluesky", "website")
    )
    return {"id": f"contact-{locale}", "locale": locale, **empty, "deleted_at": None, **fields}


def address(locale: str, city: str | None) -> dict[str, Any]:
    return {
        "id": f"address-{locale}",
        "locale": locale,
        "country": "CA",
        "city": city,
        "street": "1 rue Saint-Jean",
        "location": None,
        "deleted_at": None,
    }


def profile(record_id: str) -> dict[str, Any]:
    return {
        "id": record_id,
        "workspace_id": WORKSPACE_ID,
        "profile_categories": [{"id": "pc-1", "category_id": "cat-1"}],
        "profile_type_id": "type-1",
        "status_id": "status-1",
        # The profile's page on the media site, never the organization's own website.
        "canonical_url": f"https://lacapitale.ca/profils/{record_id}",
    }


def profile_fields(record_id: str) -> dict[str, Any]:
    return {
        "id": record_id,
        "profile_image_key": "images/profile.png",
        "cover_image_key": None,
        "profile": profile(record_id),
        "description": [],
        "address": [address("fr", "Québec"), address("en", "Quebec City")],
        "contact": [],
        "inserted_at": "2026-09-01T12:00:00Z",
        "updated_at": "2026-10-15T12:00:00Z",
    }


def organization() -> dict[str, Any]:
    return {
        **profile_fields("org-1"),
        "name": "Boulangerie Saint-Roch Inc.",
        "contact": [
            contact(
                "fr",
                email="Info@BoulangerieStRoch.ca",
                phone="418 555-0142",
                website="https://www.boulangeriestroch.ca",
                linkedin="https://www.linkedin.com/company/boulangerie-st-roch/",
            ),
            contact(
                "en",
                email="info@boulangeriestroch.ca",
                phone="+1 418-555-0142",
                website="https://www.boulangeriestroch.ca/en",
                linkedin="https://ca.linkedin.com/company/boulangerie-st-roch",
            ),
        ],
        "locales": [
            {"id": "ol-fr", "locale": "fr", "summary_html": "<p>Pain</p>", "deleted_at": None}
        ],
    }


def person() -> dict[str, Any]:
    return {
        **profile_fields("person-1"),
        "first_name": "Marie-Ève",
        "last_name": "Tremblay",
        "other_name": None,
        "pronoun": "elle",
        "contact": [
            contact(
                "fr",
                email="marie-eve@boulangeriestroch.ca",
                phone="418 555-0199",
                linkedin="https://www.linkedin.com/in/marie-eve-tremblay",
            )
        ],
        "locales": [
            {
                "id": "pl-fr",
                "locale": "fr",
                "job_title": "Directrice générale",
                "summary_html": "<p>Biographie</p>",
                "deleted_at": None,
            },
            {
                "id": "pl-en",
                "locale": "en",
                "job_title": "General Manager",
                "summary_html": None,
                "deleted_at": None,
            },
        ],
    }


def named_locale(locale: str, name: str) -> dict[str, Any]:
    return {
        "id": f"nl-{locale}",
        "locale": locale,
        "name": name,
        "summary_html": None,
        "deleted_at": None,
    }


def project() -> dict[str, Any]:
    return {
        **profile_fields("project-1"),
        "owner_id": "org-1",
        "contact": [contact("fr", website="https://corridorvert.ca")],
        "locales": [named_locale("fr", "Corridor vert"), named_locale("en", "Green Corridor")],
    }


def event() -> dict[str, Any]:
    return {
        **profile_fields("event-1"),
        "subscription_url": None,
        "schedule": {"id": "schedule-1", "recurrence": "none", "timezone": "America/Toronto"},
        "locales": [named_locale("fr", "Festival d'été"), named_locale("en", "Summer Festival")],
        "form": {"id": "form-1", "blocks": []},
        "registration_opens_at": None,
        "registration_closes_at": None,
        "registration_timezone": None,
    }


def content() -> dict[str, Any]:
    return {
        "id": "content-1",
        "template_id": "template-1",
        "workspace_id": WORKSPACE_ID,
        "status_id": "status-1",
        "canonical_domain": "lacapitale.ca",
        "canonical_url": "https://lacapitale.ca/articles/content-1",
        "is_archived": False,
        "show_publication_datetime": True,
        "is_advertising": False,
        "is_sponsored": True,
        "is_ai_generated": False,
        "locales": [
            {
                "id": "cl-fr",
                "locale": "fr",
                "location": None,
                "title_html": "<h1>La boulangerie &amp; ses 100 ans</h1>",
                "subtitle_html": None,
                "lead_html": None,
                "seo": {"description": None, "title": None},
                "visual": {"id": "visual-1", "type": "none"},
                "authors": [{"id": "author-1", "profile_id": "person-9"}],
                "deleted_at": None,
            }
        ],
        "content_categories": [{"id": "cc-1", "category_id": "cat-1"}],
        "published_at": "2026-10-10T14:30:00Z",
        "released_at": None,
        "released_at_timezone": None,
        "inserted_at": "2026-10-09T10:00:00Z",
        "updated_at": "2026-10-10T14:30:00Z",
        "deleted_at": None,
    }


def profiles_block(profile_kind: str, *profile_ids: str) -> dict[str, Any]:
    return {
        "id": f"block-{profile_kind}",
        "template_id": None,
        "content_locale_id": "cl-fr",
        "position": 1,
        "kind": "profiles",
        "profile_kind": profile_kind,
        "visual": None,
        "profile_entries": [
            {"id": f"entry-{pid}", "profile_id": pid, "content_block_id": f"block-{profile_kind}"}
            for pid in profile_ids
        ],
    }
