import httpx
import pytest

from app.ingestion.retry import RetryTransport


class Script:
    """A transport that answers with the given outcomes in order, then 200."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, request):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else 200
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, request=request)


def client_for(script, sleeps, **options):
    transport = RetryTransport(httpx.MockTransport(script), sleep=sleeps.append, **options)
    return httpx.Client(base_url="https://api.test", transport=transport)


@pytest.mark.parametrize(
    "failure", [500, 502, 503, 504, 429, httpx.ConnectError("refused"), httpx.ReadTimeout("slow")]
)
def test_network_and_server_errors_are_retried_until_a_response_succeeds(failure):
    # Arrange
    script, sleeps = Script(failure, failure), []

    # Act
    response = client_for(script, sleeps).get("/x")

    # Assert
    assert response.status_code == 200
    assert script.calls == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_are_returned_at_once(status):
    # Arrange
    script, sleeps = Script(status), []

    # Act
    response = client_for(script, sleeps).get("/x")

    # Assert
    assert response.status_code == status
    assert script.calls == 1
    assert sleeps == []


def test_the_last_server_error_is_returned_after_every_attempt():
    # Arrange
    script, sleeps = Script(*[503] * 5), []

    # Act
    response = client_for(script, sleeps, attempts=3).get("/x")

    # Assert
    assert response.status_code == 503
    assert script.calls == 3


def test_the_last_network_error_is_raised_after_every_attempt():
    # Arrange
    script, sleeps = Script(*[httpx.ConnectError("refused")] * 5), []

    # Act / Assert
    with pytest.raises(httpx.ConnectError):
        client_for(script, sleeps, attempts=2).get("/x")
    assert script.calls == 2


def test_delays_double_up_to_the_maximum():
    # Arrange
    script, sleeps = Script(*[500] * 6), []

    # Act
    client_for(script, sleeps, attempts=6, base_delay=0.5, max_delay=3).get("/x")

    # Assert
    assert sleeps == [0.5, 1.0, 2.0, 3, 3]


def test_requests_that_are_not_idempotent_are_not_retried():
    # Arrange
    script, sleeps = Script(503), []

    # Act
    response = client_for(script, sleeps).post("/x")

    # Assert
    assert response.status_code == 503
    assert script.calls == 1


def test_at_least_one_attempt_is_required():
    # Act / Assert
    with pytest.raises(ValueError, match="attempts"):
        RetryTransport(httpx.MockTransport(Script()), attempts=0)


def test_closing_the_client_closes_the_wrapped_transport(mocker):
    # Arrange
    inner = httpx.MockTransport(Script())
    close = mocker.spy(inner, "close")
    client = httpx.Client(transport=RetryTransport(inner))

    # Act
    client.close()

    # Assert
    close.assert_called_once()
