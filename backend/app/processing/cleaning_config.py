# AI contribution: Below 50% AI-generated
"""

Cleaning rules for scalar columns emitted by the Omerlo mappers.

The batch mapper preserves attributes and external_ids as mapped, outside cleaning.
Both remain part of duplicate fingerprints and version hashes.
"""

from app.processing.cleaning import CleaningConfig, FieldRule

CONFIGS = {
    kind: CleaningConfig(
        fields={
            "kind": FieldRule(required=True, allowed_values=(kind,)),
            "external_id": FieldRule(required=True),
            "workspace_id": FieldRule(),
            "name_normalized": FieldRule(required=kind in ("organization", "person")),
            "domain": FieldRule(),
            "linkedin": FieldRule(),
            "city": FieldRule(),
        },
        # Compare the complete cleaned record, including external_id. An id alone
        # would hide changed payloads. Never supply historical records here.
        unique_by=(),
    )
    for kind in ("organization", "person", "event", "project", "content")
}


def get_cleaning_config(entity_kind):
    """Return the rules for this entity kind or explain what is missing."""
    if entity_kind not in CONFIGS:
        raise ValueError("No cleaning config for entity kind: " + entity_kind)
    return CONFIGS[entity_kind]
