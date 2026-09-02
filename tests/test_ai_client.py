"""Tests for the AI client module (with mocked OpenAI API)."""

from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image

from exif_tagger.ai_client import (
    _build_prompt,
    _build_structured_output_config,
    _image_to_base64,
    _parse_response,
    clear_client_cache,
    get_openai_client,
    tag_image_with_ai,
)
from exif_tagger.models.schema import ModelConfig, TagDefinition


class TestBuildPrompt:
    """Test that the AI prompt is built correctly from tag definitions."""

    def test_includes_all_tags(self):
        tags = {
            "landscape": TagDefinition(description="Natural scenery", threshold=0.7),
            "portrait": TagDefinition(description="Person face visible", threshold=0.8),
        }

        prompt = _build_prompt(tags)
        assert "landscape" in prompt
        assert "portrait" in prompt
        assert "Natural scenery" in prompt
        assert "Person face visible" in prompt

    def test_excludes_thresholds_from_prompt(self):
        tags = {"tag1": TagDefinition(description="desc", threshold=0.6)}
        prompt = _build_prompt(tags)
        assert "threshold" not in prompt

    def test_includes_all_tags_in_results(self):
        """Every tag must appear in the prompt so the model scores each one."""
        tags = {
            "a": TagDefinition(description="desc a", threshold=0.5),
            "b": TagDefinition(description="desc b", threshold=0.7),
            "c": TagDefinition(description="desc c", threshold=0.9),
        }
        prompt = _build_prompt(tags)
        assert "a" in prompt and "b" in prompt and "c" in prompt

    def test_request_json_format(self):
        """Prompt should ask for JSON output."""
        prompt = _build_prompt({"test": TagDefinition(description="x", threshold=0.5)})
        assert '"results"' in prompt
        assert "tag_name" in prompt
        assert "score" in prompt

    def test_build_prompt_sparse_instructions(self):
        tags = {
            "landscape": TagDefinition(description="Natural scenery", threshold=0.7),
            "portrait": TagDefinition(description="Person face visible", threshold=0.8),
        }

        prompt = _build_prompt(tags)
        assert "landscape" in prompt
        assert "portrait" in prompt
        assert "score >= 0.2" in prompt or "score >= 0" in prompt
        assert "max 10 words" in prompt
        assert "omitted" in prompt.lower()



class TestParseResponse:
    """Test parsing of AI response strings to TaggingResponse."""

    def test_valid_json_response(self):
        response_str = json.dumps(
            {
                "results": [
                    {"tag_name": "landscape", "score": 0.95, "reason": "Mountains visible"},
                    {"tag_name": "portrait", "score": 0.2, "reason": "No faces seen"},
                ]
            }
        )

        result = _parse_response(response_str)
        assert len(result.results) == 2
        assert result.results[0].tag_name == "landscape"
        assert result.results[0].score == 0.95
        assert result.results[1].tag_name == "portrait"
        assert result.results[1].score == 0.2

    def test_valid_json_response_with_scene_description(self):
        response_str = json.dumps(
            {
                "scene_description": "A snowy mountain peak with blue skies.",
                "results": [
                    {"tag_name": "mountain", "score": 0.98, "reason": "Snowy peak in center"},
                ],
            }
        )

        result = _parse_response(response_str)
        assert result.scene_description == "A snowy mountain peak with blue skies."
        assert result.summary == "A snowy mountain peak with blue skies."
        assert len(result.results) == 1
        assert result.results[0].tag_name == "mountain"

    def test_json_in_markdown_code_blocks(self):
        """Model may wrap JSON in ```json ... ``` blocks – should be handled."""
        response_str = '```json\n{"results": [{"tag_name": "x", "score": 0.8}]}\n```\n'
        result = _parse_response(response_str)
        assert len(result.results) == 1
        assert result.results[0].tag_name == "x"

    def test_json_in_markdown_uppercase_and_plain_fences(self):
        """Model may wrap JSON in ```JSON ... ``` or plain ``` ... ``` blocks."""
        response_str_upper = '```JSON\n{"results": [{"tag_name": "y", "score": 0.9}]}\n```'
        result_upper = _parse_response(response_str_upper)
        assert len(result_upper.results) == 1
        assert result_upper.results[0].tag_name == "y"

        response_str_plain = '```\n{"results": [{"tag_name": "z", "score": 0.7}]}\n```'
        result_plain = _parse_response(response_str_plain)
        assert len(result_plain.results) == 1
        assert result_plain.results[0].tag_name == "z"

    def test_preamble_text_before_markdown_code_block(self):
        """Model may add conversational text before markdown-wrapped JSON."""
        response_str = 'Here is the analysis:\n\n```json\n{"results": [{"tag_name": "x", "score": 0.8}]}\n```\n'
        result = _parse_response(response_str)
        assert len(result.results) == 1
        assert result.results[0].tag_name == "x"

    def test_invalid_json_logs_error_and_raises_value_error(self, caplog):
        """When JSON is invalid, logger.error should record the JSONDecodeError details and attempted text."""
        import logging

        with caplog.at_level(logging.ERROR):
            with pytest.raises(ValueError, match="did not return valid JSON"):
                _parse_response("This is not JSON at all!!")

        assert "Failed to parse JSON response" in caplog.text
        assert "This is not JSON at all!!" in caplog.text

    def test_parse_response_handles_bytes_input(self):
        """_parse_response should accept bytes and decode UTF-8 correctly."""
        raw_bytes = b'{"results": [{"tag_name": "landscape", "score": 0.9}]}'
        result = _parse_response(raw_bytes)
        assert len(result.results) == 1
        assert result.results[0].tag_name == "landscape"

    def test_parse_response_handles_utf8_bom(self):
        """_parse_response should strip UTF-8 BOM if present."""
        bom_str = '\ufeff{"results": [{"tag_name": "landscape", "score": 0.9}]}'
        result = _parse_response(bom_str)
        assert len(result.results) == 1

    def test_parse_response_tolerates_unescaped_control_chars(self):
        """_parse_response should parse JSON containing unescaped control chars via strict=False."""
        control_char_str = '{"results": [{"tag_name": "landscape", "score": 0.9, "reason": "Line 1\nLine 2"}]}'
        result = _parse_response(control_char_str)
        assert len(result.results) == 1
        assert result.results[0].reason == "Line 1\nLine 2"

    def test_score_clamped_to_valid_range(self):
        """Scores outside 0-1 should be clamped."""
        response_str = json.dumps(
            {
                "results": [
                    {"tag_name": "test", "score": -0.5},  # Clamped to 0
                    {"tag_name": "test2", "score": 1.5},  # Clamped to 1
                    {"tag_name": "test3", "score": 0.5},  # Unchanged
                ]
            }
        )
        result = _parse_response(response_str)
        assert result.results[0].score == 0.0
        assert result.results[1].score == 1.0
        assert result.results[2].score == 0.5


class TestTagImageWithAi:
    """Integration test for tag_image_with_ai using mock OpenAI client."""

    def test_tags_image_successfully(self, sample_jpeg, mock_openai):
        """Simulate a successful AI call with the mock client."""
        model_config = ModelConfig(
            base_url="https://api.test.com/v1",
            model_name="test-model",
        )

        tags = {
            "landscape": TagDefinition(description="Natural scenery", threshold=0.7),
        }

        result = tag_image_with_ai(model_config, sample_jpeg, tags)
        # Should return at least one result from the mock
        assert len(result.results) >= 1

    def test_default_image_format_uses_jpeg(self, sample_jpeg, monkeypatch):
        """Verify default ModelConfig uses JPEG MIME type data:image/jpeg;base64,..."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"results": [{"tag_name": "landscape", "score": 0.9}]}'
        mock_client.chat.completions.create.return_value = mock_response

        monkeypatch.setattr("exif_tagger.ai_client.OpenAI", lambda **kwargs: mock_client)

        model_config = ModelConfig(
            base_url="https://api.test.com/v1",
            model_name="test-model",
        )
        tags = {"landscape": TagDefinition(description="Natural scenery", threshold=0.7)}
        tag_image_with_ai(model_config, sample_jpeg, tags)

        assert mock_client.chat.completions.create.called
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        user_msg = next(m for m in call_kwargs["messages"] if m["role"] == "user")
        img_part = next(p for p in user_msg["content"] if p.get("type") == "image_url")
        assert img_part["image_url"]["url"].startswith("data:image/jpeg;base64,")


class TestNoTagsSkipsAiCall:
    """Verify that no AI call is made when there are zero tags."""

    def test_empty_tags_no_call(self):
        """With empty tag definitions, should skip AI entirely."""
        model_config = ModelConfig(
            base_url="https://api.test.com/v1",
            model_name="test-model",
        )

        result = tag_image_with_ai(model_config, __import__("pathlib").Path("/dev/null"), {})
        assert len(result.results) == 0


class TestStructuredOutputs:
    """Tests for OpenAI structured outputs (response_format)."""

    def test_prompt_excludes_json_instructions_when_so_enabled(self):
        tags = {"landscape": TagDefinition(description="Natural scenery", threshold=0.7)}
        prompt = _build_prompt(tags, use_structured_outputs=True)
        assert '"results"' not in prompt
        assert "Respond ONLY with valid JSON" not in prompt

    def test_prompt_includes_json_instructions_when_so_disabled(self):
        tags = {"landscape": TagDefinition(description="Natural scenery", threshold=0.7)}
        prompt = _build_prompt(tags, use_structured_outputs=False)
        assert '"results"' in prompt
        assert "Respond ONLY with valid JSON" in prompt

    def test_structured_output_config_has_schema(self):
        config = _build_structured_output_config()
        assert config["type"] == "json_schema"
        assert "json_schema" in config
        schema = config["json_schema"]["schema"]
        assert "$defs" in schema or "properties" in schema  # Pydantic generates $defs for nested models

    def test_tag_image_with_ai_passes_response_format(self, sample_jpeg, mock_openai):
        """When use_structured_outputs=True, response_format should be passed to the API."""
        model_config = ModelConfig(
            base_url="https://api.test.com/v1",
            model_name="test-model",
            use_structured_outputs=True,
        )

        tags = {
            "landscape": TagDefinition(description="Natural scenery", threshold=0.7),
        }

        result = tag_image_with_ai(model_config, sample_jpeg, tags)
        assert len(result.results) >= 1


class TestImageToBase64:
    """Tests for _image_to_base64 fast downscaling and format support."""

    def test_image_to_base64_fast_resizing(self, sample_jpeg):
        b64_str = _image_to_base64(sample_jpeg, max_dim=100, fmt="jpeg", quality=80)
        assert isinstance(b64_str, str)
        assert len(b64_str) > 0
        img_data = base64.b64decode(b64_str)
        with Image.open(io.BytesIO(img_data)) as img:
            assert max(img.size) <= 100

    def test_image_to_base64_webp_format(self, sample_jpeg):
        b64_str = _image_to_base64(sample_jpeg, max_dim=50, fmt="webp", quality=80)
        assert isinstance(b64_str, str)
        img_data = base64.b64decode(b64_str)
        with Image.open(io.BytesIO(img_data)) as img:
            assert img.format == "WEBP"
            assert max(img.size) <= 50

    def test_image_to_base64_large_jpeg_draft(self, tmp_path):
        large_img = Image.new("RGB", (2000, 1500), color=(100, 150, 200))
        img_path = tmp_path / "large_photo.jpg"
        large_img.save(img_path, format="JPEG")

        b64_str = _image_to_base64(img_path, max_dim=512, fmt="jpeg", quality=80)
        assert isinstance(b64_str, str)
        img_data = base64.b64decode(b64_str)
        with Image.open(io.BytesIO(img_data)) as img:
            assert max(img.size) <= 512


class TestOpenAIClientCaching:
    """Tests for OpenAI client caching and connection pooling."""

    def test_get_openai_client_caches_and_reuses_instance(self):

        clear_client_cache()
        client1 = get_openai_client(base_url="http://localhost:8000/v1", api_key="sk-test")
        client2 = get_openai_client(base_url="http://localhost:8000/v1", api_key="sk-test")
        assert client1 is client2

    def test_get_openai_client_creates_different_instance_for_different_endpoints(self):

        clear_client_cache()
        client1 = get_openai_client(base_url="http://localhost:8000/v1", api_key="sk-test")
        client2 = get_openai_client(base_url="http://localhost:9000/v1", api_key="sk-test")
        assert client1 is not client2

    def test_get_openai_client_handles_none_api_key(self):

        clear_client_cache()
        client1 = get_openai_client(base_url="http://localhost:8000/v1", api_key=None)
        client2 = get_openai_client(base_url="http://localhost:8000/v1")
        assert client1 is client2

    def test_clear_client_cache_resets_cache(self):

        clear_client_cache()
        client1 = get_openai_client(base_url="http://localhost:8000/v1", api_key="sk-test")
        clear_client_cache()
        client2 = get_openai_client(base_url="http://localhost:8000/v1", api_key="sk-test")
        assert client1 is not client2

    def test_get_openai_client_thread_safety(self):
        import concurrent.futures

        clear_client_cache()

        def fetch_client(endpoint_idx: int):
            endpoint = f"http://localhost:800{endpoint_idx % 3}/v1"
            return endpoint_idx % 3, get_openai_client(base_url=endpoint, api_key="sk-test")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(fetch_client, range(30)))

        clients_by_endpoint: dict[int, list] = {}
        for ep_idx, client in results:
            clients_by_endpoint.setdefault(ep_idx, []).append(client)

        for ep_idx, clients in clients_by_endpoint.items():
            assert len(clients) == 10
            for c in clients[1:]:
                assert c is clients[0]

    def test_call_vision_api_reuses_cached_client(self, sample_jpeg, monkeypatch):
        from unittest.mock import MagicMock

        from exif_tagger.ai_client import tag_image_with_ai

        clear_client_cache()
        instantiation_count = 0

        class MockClient:
            def __init__(self, *args, **kwargs):
                nonlocal instantiation_count
                instantiation_count += 1
                self.chat = MagicMock()
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = '{"results": [{"tag_name": "t", "score": 0.9}]}'
                self.chat.completions.create.return_value = mock_response

        monkeypatch.setattr("exif_tagger.ai_client.OpenAI", MockClient)

        model_config = ModelConfig(
            base_url="https://api.pool-test.com/v1",
            model_name="test-model",
        )
        tags = {"t": TagDefinition(description="test", threshold=0.5)}

        tag_image_with_ai(model_config, sample_jpeg, tags)
        tag_image_with_ai(model_config, sample_jpeg, tags)
        tag_image_with_ai(model_config, sample_jpeg, tags)

        assert instantiation_count == 1
