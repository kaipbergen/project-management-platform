"""Integration tests for document endpoints with mocked S3."""

import io
import uuid
from unittest.mock import patch

from httpx import AsyncClient


def _make_pdf_bytes(name: str = "test") -> bytes:
    """Minimal valid-looking PDF bytes."""
    return b"%PDF-1.4 1 0 obj<</Type /Catalog>>endobj"


class TestUploadDocuments:
    async def test_upload_single_document(self, client: AsyncClient, auth_headers: dict) -> None:
        # Create project
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Doc Project"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]

        with patch("app.services.document_service.upload_file_to_s3") as mock_upload:
            mock_upload.return_value = None
            resp = await client.post(
                f"/api/v1/projects/{project_id}/documents",
                files={"files": ("report.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
                headers=auth_headers,
            )

        assert resp.status_code == 201
        data = resp.json()
        assert len(data) == 1
        assert data[0]["filename"] == "report.pdf"
        assert data[0]["content_type"] == "application/pdf"
        assert data[0]["size_bytes"] > 0

    async def test_upload_invalid_extension(self, client: AsyncClient, auth_headers: dict) -> None:
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Bad Upload Project"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]

        resp = await client.post(
            f"/api/v1/projects/{project_id}/documents",
            files={"files": ("script.exe", io.BytesIO(b"malware"), "application/octet-stream")},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    async def test_upload_multiple_documents(self, client: AsyncClient, auth_headers: dict) -> None:
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Multi Doc Project"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]

        with patch("app.services.document_service.upload_file_to_s3"):
            resp = await client.post(
                f"/api/v1/projects/{project_id}/documents",
                files=[
                    ("files", ("a.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")),
                    (
                        "files",
                        (
                            "b.docx",
                            io.BytesIO(b"PK fake docx"),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        ),
                    ),
                ],
                headers=auth_headers,
            )

        assert resp.status_code == 201
        assert len(resp.json()) == 2

    async def test_upload_no_access_to_project(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        # Register second user
        await client.post(
            "/api/v1/auth/register",
            json={
                "login": "intruder_upload",
                "password": "Password123!",
                "repeat_password": "Password123!",
            },
        )
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"login": "intruder_upload", "password": "Password123!"},
        )
        intruder_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Private"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]

        resp = await client.post(
            f"/api/v1/projects/{project_id}/documents",
            files={"files": ("x.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
            headers=intruder_headers,
        )
        assert resp.status_code == 403


class TestListDocuments:
    async def test_list_empty(self, client: AsyncClient, auth_headers: dict) -> None:
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Empty Docs"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]

        resp = await client.get(
            f"/api/v1/projects/{project_id}/documents",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_after_upload(self, client: AsyncClient, auth_headers: dict) -> None:
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Listed Docs"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]

        with patch("app.services.document_service.upload_file_to_s3"):
            await client.post(
                f"/api/v1/projects/{project_id}/documents",
                files={"files": ("listed.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
                headers=auth_headers,
            )

        resp = await client.get(
            f"/api/v1/projects/{project_id}/documents",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["filename"] == "listed.pdf"


class TestDownloadDocument:
    async def test_download_returns_presigned_url(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Download Project"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]

        with patch("app.services.document_service.upload_file_to_s3"):
            upload_resp = await client.post(
                f"/api/v1/projects/{project_id}/documents",
                files={"files": ("dl.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
                headers=auth_headers,
            )
        doc_id = upload_resp.json()[0]["id"]

        with patch(
            "app.services.document_service.generate_presigned_download_url",
            return_value="https://s3.example.com/presigned-url",
        ):
            resp = await client.get(
                f"/api/v1/documents/{doc_id}",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["download_url"] == "https://s3.example.com/presigned-url"
        assert data["filename"] == "dl.pdf"

    async def test_download_nonexistent_document(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resp = await client.get(
            f"/api/v1/documents/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestDeleteDocument:
    async def test_owner_can_delete_document(self, client: AsyncClient, auth_headers: dict) -> None:
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Delete Doc Project"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]

        with patch("app.services.document_service.upload_file_to_s3"):
            upload_resp = await client.post(
                f"/api/v1/projects/{project_id}/documents",
                files={"files": ("todel.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
                headers=auth_headers,
            )
        doc_id = upload_resp.json()[0]["id"]

        with patch("app.services.document_service.delete_file_from_s3"):
            resp = await client.delete(
                f"/api/v1/documents/{doc_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 204

        # Confirm gone from list
        list_resp = await client.get(
            f"/api/v1/projects/{project_id}/documents",
            headers=auth_headers,
        )
        assert list_resp.json() == []

    async def test_participant_cannot_delete_document(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        # Owner creates project + uploads
        proj = await client.post(
            "/api/v1/projects",
            json={"name": "Participant Cannot Delete"},
            headers=auth_headers,
        )
        project_id = proj.json()["id"]

        with patch("app.services.document_service.upload_file_to_s3"):
            upload_resp = await client.post(
                f"/api/v1/projects/{project_id}/documents",
                files={"files": ("prot.pdf", io.BytesIO(_make_pdf_bytes()), "application/pdf")},
                headers=auth_headers,
            )
        doc_id = upload_resp.json()[0]["id"]

        # Register and invite participant
        await client.post(
            "/api/v1/auth/register",
            json={
                "login": "doc_participant",
                "password": "Password123!",
                "repeat_password": "Password123!",
            },
        )
        await client.post(
            f"/api/v1/projects/{project_id}/invite",
            json={"user_login": "doc_participant"},
            headers=auth_headers,
        )
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"login": "doc_participant", "password": "Password123!"},
        )
        part_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        resp = await client.delete(
            f"/api/v1/documents/{doc_id}",
            headers=part_headers,
        )
        assert resp.status_code == 403
