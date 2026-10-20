"""Keep all PULSE cleaning rules in one place.

These field names are examples. Update them to match actual mapper outputs.
"""

from app.processing.cleaning import CleaningConfig, FieldRule

CONFIGS = {
    "event": CleaningConfig(
        fields={
            "external_id": FieldRule(required=True),
            "name": FieldRule(required=True),
            "start_at": FieldRule(
                type="datetime",
                input_formats=(
                    # Canadian format
                    "%d/%m/%Y %H:%M",
                    # American format
                    "%m-%d-%Y %H:%M",
                ),
                source_timezone="America/Toronto",
            ),
            "active": FieldRule(type="boolean"),
            "status": FieldRule(
                allowed_values=("planned", "cancelled", "completed"),
                categories={
                    "prévu": "planned",
                    "planifié": "planned",
                    "planned": "planned",
                    "annulé": "cancelled",
                    "cancelled": "cancelled",
                    "terminé": "completed",
                    "completed": "completed",
                },
            ),
        },
        unique_by=("external_id",),
    ),
    "organization": CleaningConfig(
        fields={
            "external_id": FieldRule(required=True),
            "name": FieldRule(required=True),
            "email": FieldRule(type="email"),
        },
        unique_by=("external_id",),
    ),
}


def get_cleaning_config(entity_kind):
    """Return the rules for this entity kind or explain what is missing."""

    if entity_kind not in CONFIGS:
        raise ValueError("No cleaning config for entity kind: " + entity_kind)
    return CONFIGS[entity_kind]
