"""Unit tests for the Lambda file size calculator."""

import json
import os
import sys
import types
import uuid
from unittest.mock import MagicMock, patch


def _load_lambda_module():
    """Load lambda module with psycopg2 mocked out (not installed in test env)."""
    psycopg2_mock = types.ModuleType("psycopg2")
    psycopg2_mock.connect = MagicMock()
    sys.modules.setdefault("psycopg2", psycopg2_mock)

    import importlib
    import os

    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
    os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "file_size_calculator",
        os.path.join(os.path.dirname(__file__), "../../lambda/file_size_calculator.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class TestExtractProjectId:
    def setup_method(self) -> None:
        self.lm = _load_lambda_module()

    def test_valid_key(self) -> None:
        pid = uuid.uuid4()
        doc_id = uuid.uuid4()
        key = f"projects/{pid}/documents/{doc_id}/report.pdf"
        result = self.lm._extract_project_id(key)
        assert result == pid

    def test_invalid_prefix(self) -> None:
        result = self.lm._extract_project_id("uploads/something/file.pdf")
        assert result is None

    def test_invalid_uuid(self) -> None:
        result = self.lm._extract_project_id("projects/not-a-uuid/documents/x/file.pdf")
        assert result is None

    def test_short_key(self) -> None:
        result = self.lm._extract_project_id("projects/")
        assert result is None


class TestHandlerWithMocks:
    def setup_method(self) -> None:
        self.lm = _load_lambda_module()

    def test_handler_skips_non_project_keys(self) -> None:
        event = {
            "Records": [
                {"s3": {"object": {"key": "uploads/random-file.pdf"}}}
            ]
        }
        with patch.object(self.lm, "_calculate_project_size") as mock_calc:
            result = self.lm.handler(event, None)
            mock_calc.assert_not_called()
        assert result["statusCode"] == 200

    def test_handler_processes_valid_key(self) -> None:
        pid = uuid.uuid4()
        doc_id = uuid.uuid4()
        key = f"projects/{pid}/documents/{doc_id}/report.pdf"
        event = {"Records": [{"s3": {"object": {"key": key}}}]}

        with (
            patch.object(self.lm, "_calculate_project_size", return_value=1024) as mock_calc,
            patch.object(self.lm, "_update_project_size") as mock_update,
        ):
            result = self.lm.handler(event, None)
            mock_calc.assert_called_once_with(pid)
            mock_update.assert_called_once_with(pid, 1024)

        body = json.loads(result["body"])
        assert str(pid) in body["processed_projects"]
        assert body["errors"] == []

    def test_handler_error_captured(self) -> None:
        pid = uuid.uuid4()
        doc_id = uuid.uuid4()
        key = f"projects/{pid}/documents/{doc_id}/report.pdf"
        event = {"Records": [{"s3": {"object": {"key": key}}}]}

        with patch.object(self.lm, "_calculate_project_size", side_effect=Exception("S3 error")):
            result = self.lm.handler(event, None)

        body = json.loads(result["body"])
        assert len(body["errors"]) == 1
        assert "S3 error" in body["errors"][0]
