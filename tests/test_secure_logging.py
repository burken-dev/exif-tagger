import logging
from pathlib import Path

from exif_tagger.ai_client import SecretRedactor, setup_secure_logging


def test_secret_redactor_scrubs_headers():
    redactor = SecretRedactor()
    record = logging.LogRecord(
        "test", logging.ERROR, "", 0, "Authorization: Bearer sk-123456789012345678901234", (), None
    )
    redactor.filter(record)
    assert "sk-123456789012345678901234" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_secret_redactor_scrubs_api_key_header():
    redactor = SecretRedactor()
    record = logging.LogRecord("test", logging.ERROR, "", 0, "x-api-key: secret-key-value-1234567890", (), None)
    redactor.filter(record)
    assert "secret-key-value-1234567890" not in record.getMessage()


def test_setup_secure_logging_creates_file_handler(tmp_path):
    log_dir = str(tmp_path / "logs")
    setup_secure_logging(level="DEBUG", log_dir=log_dir, logger_name="test_logger")
    test_logger = logging.getLogger("test_logger")
    test_logger.info("Test log entry")

    log_file = Path(log_dir) / "exif-tagger.log"
    assert log_file.exists()
    assert "Test log entry" in log_file.read_text()


def test_redaction_does_not_mutate_record(caplog):
    import logging

    from exif_tagger.ai_client import SecretRedactingFormatter

    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "key sk-abcdefghijklmnopqrst", None, None)
    out = SecretRedactingFormatter("%(message)s").format(rec)
    assert "[REDACTED]" in out
    assert rec.msg == "key sk-abcdefghijklmnopqrst"
    assert rec.args is None
