import logging

import app.main  # noqa: F401  (configures logging on import, as uvicorn does)


def test_application_info_logs_are_enabled():
    """The summary of the periodic sweep is logged at INFO, so it must be visible in the server output."""
    app_logger = logging.getLogger("app")

    assert app_logger.handlers
    assert logging.getLogger("app.services.workflow.sweeper").isEnabledFor(logging.INFO)
