import io
import json
import logging

import pytest

from app.core.logging import (
    REDACTED,
    configure_logging,
    get_logger,
    level_from_env,
    logged_run,
    mask_sensitive_data,
)


def test_logs_are_json_with_timestamp_level_and_module(log_output):
    get_logger("app.example").info("thing_happened", count=3)

    [entry] = log_output()
    assert entry["event"] == "thing_happened"
    assert entry["level"] == "info"
    assert entry["module"] == "app.example"
    assert entry["count"] == 3
    assert entry["timestamp"].endswith("Z")


def test_standard_library_loggers_use_the_same_format(log_output):
    logging.getLogger("app.ingestion.omerlo").warning("Skipped %s records", 2)

    [entry] = log_output()
    assert entry["event"] == "Skipped 2 records"
    assert entry["level"] == "warning"
    assert entry["module"] == "app.ingestion.omerlo"


def test_errors_include_the_stack_trace(log_output):
    try:
        raise RuntimeError("sync exploded")
    except RuntimeError:
        get_logger("app.example").exception("sync_failed")

    [entry] = log_output()
    assert entry["level"] == "error"
    assert "Traceback" in entry["exception"]
    assert "RuntimeError: sync exploded" in entry["exception"]


@pytest.mark.usefixtures("log_output")
def test_messages_below_the_configured_level_are_dropped():
    stream = io.StringIO()
    configure_logging(level="WARNING", stream=stream)

    log = get_logger("app.example")
    log.info("ignored")
    log.warning("kept")

    assert [json.loads(line)["event"] for line in stream.getvalue().splitlines()] == ["kept"]


@pytest.mark.usefixtures("log_output")
def test_uvicorn_logs_join_the_json_output_and_noisy_loggers_are_quiet():
    # uvicorn installs its own handler before importing the app.
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.addHandler(logging.StreamHandler(io.StringIO()))
    uvicorn_logger.propagate = False
    stream = io.StringIO()
    configure_logging(level="INFO", stream=stream)

    logging.getLogger("uvicorn.error").info("Started server process")
    logging.getLogger("uvicorn.access").info("GET /api/health 200")
    logging.getLogger("httpx").info("HTTP Request: GET https://api.example/x?api_key=k")

    events = [json.loads(line)["event"] for line in stream.getvalue().splitlines()]
    assert events == ["Started server process"]


@pytest.mark.usefixtures("log_output")
def test_the_configured_level_also_applies_to_uvicorn_logs():
    stream = io.StringIO()
    configure_logging(level="ERROR", stream=stream)
    # uvicorn sets its loggers to INFO itself, which overrides the root level.
    uvicorn_logger = logging.getLogger("uvicorn.error")
    uvicorn_logger.setLevel(logging.INFO)
    try:
        uvicorn_logger.info("Started server process")
    finally:
        uvicorn_logger.setLevel(logging.NOTSET)

    assert stream.getvalue() == ""


def test_logged_output_is_masked(log_output):
    get_logger("app.example").warning(
        "import_row_rejected", email="marie@exemple.qc.ca", reason="bad phone 514-555-0199"
    )

    [entry] = log_output()
    assert entry["email"] == REDACTED
    assert entry["reason"] == "bad phone [PHONE]"


def test_values_under_sensitive_keys_are_redacted():
    event = mask_sensitive_data(
        None,
        "info",
        {
            "event": "login",
            "password": "hunter2",
            "api_key": "k",
            "Authorization": "Bearer x",
            "contact_email": "a@b.ca",
        },
    )

    assert event == {
        "event": "login",
        "password": REDACTED,
        "api_key": REDACTED,
        "Authorization": REDACTED,
        "contact_email": REDACTED,
    }


def test_hyphenated_header_keys_and_credentials_are_redacted():
    event = mask_sensitive_data(
        None,
        "info",
        {
            "event": "omerlo_request",
            "X-Api-Key": "k",
            "credentials": "user:pass",
            "headers": {"x-api-key": "k", "accept": "application/json"},
        },
    )

    assert event == {
        "event": "omerlo_request",
        "X-Api-Key": REDACTED,
        "credentials": REDACTED,
        "headers": {"x-api-key": REDACTED, "accept": "application/json"},
    }


def test_decimals_are_not_mistaken_for_phone_numbers():
    event = mask_sensitive_data(None, "info", {"event": "took 1234567890.5 ms"})

    assert event["event"] == "took 1234567890.5 ms"


def test_phone_number_at_the_end_of_a_sentence_is_masked():
    event = mask_sensitive_data(None, "info", {"event": "call 514-555-0199."})

    assert event["event"] == "call [PHONE]."


def test_emails_and_phone_numbers_inside_text_are_masked():
    event = mask_sensitive_data(
        None,
        "info",
        {"event": "Could not import marie@exemple.qc.ca, phone (514) 555-0199 or +1 418.555.0123"},
    )

    assert event["event"] == "Could not import [EMAIL], phone [PHONE] or [PHONE]"


def test_masking_reaches_nested_values():
    event = mask_sensitive_data(
        None,
        "info",
        {
            "event": "row_rejected",
            "row": {
                "name": "Groupe Exemple",
                "phone": "5145550199",
                "notes": ["write to info@exemple.ca"],
            },
        },
    )

    assert event["row"] == {
        "name": "Groupe Exemple",
        "phone": REDACTED,
        "notes": ["write to [EMAIL]"],
    }


def test_ids_and_timestamps_are_not_mistaken_for_phone_numbers():
    original = {
        "event": "request_completed",
        "request_id": "5a52f95c30a64f5093310ef5bc03285e",
        "timestamp": "2026-10-20T03:28:59.851988Z",
        "count": 5145550199,
    }

    assert mask_sensitive_data(None, "info", dict(original)) == original


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, "INFO"), ("debug", "DEBUG"), (" WARN ", "WARNING"), ("error", "ERROR")],
)
def test_level_from_env(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("LOG_LEVEL", raw)

    assert level_from_env() == expected


def test_level_from_env_rejects_unknown_levels(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "LOUD")

    with pytest.raises(ValueError, match="LOG_LEVEL must be one of"):
        level_from_env()


def test_a_run_logs_start_and_completion_with_counts_under_one_run_id(log_output):
    log = get_logger("app.ingestion.example")

    with logged_run("sync", source="omerlo") as counts:
        log.info("page_fetched", page=1)
        counts["fetched"] = 120
        counts["rejected"] = 2

    started, page, completed = log_output()
    assert started["event"] == "run_started"
    assert started["run_kind"] == "sync"
    assert started["source"] == "omerlo"
    assert page["run_id"] == started["run_id"] == completed["run_id"]
    assert completed["event"] == "run_completed"
    assert completed["fetched"] == 120
    assert completed["rejected"] == 2
    assert completed["duration_ms"] >= 0


def test_a_failed_run_is_logged_with_its_trace_and_reraised(log_output):
    with (
        pytest.raises(RuntimeError),
        logged_run("import", source="csv", run_id="run-42") as counts,
    ):
        counts["imported"] = 10
        raise RuntimeError("file vanished")

    failed = log_output()[-1]
    assert failed["event"] == "run_failed"
    assert failed["level"] == "error"
    assert failed["run_id"] == "run-42"
    assert failed["imported"] == 10
    assert "RuntimeError: file vanished" in failed["exception"]


def test_the_run_id_is_not_kept_after_the_run(log_output):
    with logged_run("sync", source="omerlo"):
        pass
    get_logger("app.example").info("after")

    assert "run_id" not in log_output()[-1]
