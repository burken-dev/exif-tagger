"""Tests for the AI client module (with mocked OpenAI API)."""

from __future__ import annotations

import json

import pytest

from exif_tagger.ai_client import (
    _build_prompt,
    _build_structured_output_config,
    _parse_response,
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

    def test_json_in_markdown_code_blocks(self):
        """Model may wrap JSON in ```json ... ``` blocks – should be handled."""
        response_str = '```json\n{"results": [{"tag_name": "x", "score": 0.8}]}\n```\n'
        result = _parse_response(response_str)
        assert len(result.results) == 1
        assert result.results[0].tag_name == "x"

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
