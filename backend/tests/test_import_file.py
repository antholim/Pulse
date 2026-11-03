# AI contribution: 50% or more AI-generated
import uuid

from app.import_file import report
from app.models import SyncRun


def test_the_report_says_how_many_rejected_rows_are_not_listed():
    # Arrange
    run = SyncRun(
        id=uuid.UUID(int=1),
        mode="full",
        status="succeeded",
        counts={"fetched": 1, "failed": 3, "failures": [{"id": "row 2", "reason": "row 2: bad"}]},
    )

    # Act
    lines = report(run).splitlines()

    # Assert
    assert lines[1:] == ["Rejected rows:", "  row 2: bad", "  ...and 2 more"]
