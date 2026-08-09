import logging
from unittest.mock import MagicMock, patch

import pytest
from openai import APIError

from exif_tagger.ai_client import _call_vision_api
from exif_tagger.models.schema import ModelConfig


def test_vision_api_error_logging_dumps_request_and_response(caplog, tmp_path):
    caplog.set_level(logging.ERROR)

    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.headers = {"content-type": "application/json", "x-request-id": "req-123"}
    mock_response.text = '{"error": {"message": "Invalid prompt", "type": "invalid_request_error"}}'

    fake_error = APIError(
        message="Invalid prompt",
        request=MagicMock(
            url="https://api.openai.com/v1/chat/completions", headers={"Authorization": "Bearer sk-secretkey1234567890"}
        ),
        body={"error": "Invalid prompt"},
    )
    fake_error.response = mock_response

    test_img = tmp_path / "test.jpg"
    from PIL import Image

    Image.new("RGB", (100, 100)).save(test_img)

    model_config = ModelConfig(
        base_url="https://api.openai.com/v1",
        model_name="gpt-4o",
        api_key="sk-secretkey1234567890",
    )

    with patch("openai.resources.chat.completions.Completions.create", side_effect=fake_error):
        with pytest.raises(RuntimeError, match="AI model failed"):
            _call_vision_api(model_config, test_img, "Test prompt")

    log_text = caplog.text
    assert "EXTERNAL API REQUEST ERROR" in log_text
    assert "Target URL: https://api.openai.com/v1" in log_text
    assert "HTTP Status Code: 400" in log_text
    assert "sk-secretkey1234567890" not in log_text
