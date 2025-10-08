from __future__ import annotations

import email
from email.message import Message
from pathlib import Path

from .base import AdapterResponse
from ..detection import DocumentType
from ..utils import normalize_newlines, slugify


class EMLAdapter:
    document_type = DocumentType.EML

    def convert(self, source: Path, run_assets: Path) -> AdapterResponse:  # type: ignore[override]
        raw = source.read_bytes()
        message: Message = email.message_from_bytes(raw)
        subject = message.get("subject", "Email")
        lines = [f"# {subject}", ""]
        warnings: list[str] = []
        assets: dict[str, Path] = {}

        if message.is_multipart():
            for part in message.walk():
                if part.is_multipart():
                    continue
                disposition = part.get_content_disposition()
                filename = part.get_filename()
                payload = part.get_payload(decode=True) or b""
                if disposition == "attachment" and filename:
                    safe_name = slugify(filename)
                    destination = run_assets / safe_name
                    destination.write_bytes(payload)
                    warnings.append("ATTACHMENT_SAVED")
                    assets[safe_name] = destination
                    lines.append(f"![Attachment](./assets/{safe_name})")
                elif part.get_content_type() == "text/plain":
                    text = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                    lines.append(text)
        else:
            payload = message.get_payload(decode=True) or b""
            text = payload.decode(message.get_content_charset() or "utf-8", errors="ignore")
            lines.append(text)

        markdown = normalize_newlines("\n".join(lines))
        return AdapterResponse(markdown=markdown, warnings=warnings, assets=assets)
