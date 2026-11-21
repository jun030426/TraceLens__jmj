"""Publish staff-reviewed native PPT text alongside an active document's existing evidence."""

import hashlib
from pathlib import Path
from typing import Annotated
from uuid import NAMESPACE_URL, uuid5

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from lerny.models import Chunk, Course, Material, MaterialVersion
from lerny.storage import source_file
from lerny.team_engine import chunk_locator
from video_extraction.shared.common import digest_file

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[int, Field(strict=True, gt=0)]


class ReviewedShape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shape_id: Positive
    text_sha256: Digest
    picture_sha256: Digest | None = None
    transcription: str | None = Field(default=None, min_length=1, max_length=1800)


class ReviewedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: Positive
    render_sha256: Digest
    shapes: list[ReviewedShape] = Field(min_length=1, max_length=200)


class SlideReview(BaseModel):
    """A reviewer attests to these shapes in reading order after viewing the rendered pages."""

    model_config = ConfigDict(extra="forbid")
    source_sha256: Digest
    pages: list[ReviewedPage] = Field(min_length=1, max_length=300)


def table_rows(shape):
    """Repeat the origin value across a verified merged span to retain header associations."""
    table = shape.table
    cells = [[None] * len(table.columns) for _ in table.rows]
    for row_index, row in enumerate(table.rows):
        for column, cell in enumerate(row.cells):
            if cell.is_spanned:
                if cells[row_index][column] is None:
                    raise ValueError("INVALID_REVIEW_TABLE")
                continue
            for r in range(row_index, row_index + cell.span_height):
                for c in range(column, column + cell.span_width):
                    if r >= len(cells) or c >= len(row.cells) or cells[r][c] is not None:
                        raise ValueError("INVALID_REVIEW_TABLE")
                    cells[r][c] = cell.text
    return cells


def native_value(shape):
    if shape.has_table:
        return "\n".join(" | ".join(row) for row in table_rows(shape))
    return shape.text if shape.has_text_frame else ""


def reviewed_text(path, review):
    if digest_file(path) != review.source_sha256:
        raise ValueError("SOURCE_CHANGED")
    slides = Presentation(path).slides
    result = {}
    for item in review.pages:
        if item.page > len(slides) or item.page in result:
            raise ValueError("INVALID_REVIEW_PAGE")
        slide = slides[item.page - 1]
        if slide._element.get("show", "1") in {"0", "false"}:
            raise ValueError("INVALID_REVIEW_PAGE")
        by_id = {shape.shape_id: shape for shape in slide.shapes}
        selected = {}
        for entry in item.shapes:
            shape = by_id.get(entry.shape_id)
            if (entry.shape_id in selected or shape is None
                    or shape._element.xpath('.//p:cNvPr[@hidden="1" or @hidden="true"]')):
                raise ValueError("INVALID_REVIEW_SHAPE")
            if entry.transcription is not None or entry.picture_sha256 is not None:
                if (shape.shape_type != MSO_SHAPE_TYPE.PICTURE or not entry.transcription
                        or hashlib.sha256(shape.image.blob).hexdigest() != entry.picture_sha256):
                    raise ValueError("INVALID_REVIEW_PICTURE")
                value = entry.transcription
            else:
                value = native_value(shape)
            if (not value.strip() or len(value) > 1800
                    or hashlib.sha256(value.encode("utf-8")).hexdigest() != entry.text_sha256):
                raise ValueError("REVIEW_TEXT_MISMATCH")
            selected[entry.shape_id] = value
        result[item.page] = selected
    return result


def additions(version, review, texts, existing):
    pending = []
    for item in review.pages:
        prior = [c for c in existing if (c.locator or {}).get("slide") == item.page]
        covered = {i for c in prior for i in c.locator.get("engine", {}).get("reviewed_shape_ids", [])}
        group = {}

        def finish():
            if group:
                locator = chunk_locator({
                    "document_type": "pptx", "source_sha256": review.source_sha256,
                    "source_locator": f"문서 {item.page}쪽", "slide_number": item.page,
                    "quality": "visually_reviewed_native_text_v1",
                    "reviewed_shape_ids": list(group), "render_sha256": item.render_sha256,
                })
                binding = f"lerny:reviewed-ppt:{version.id}:{item.page}:" + ",".join(map(str, group))
                pending.append(Chunk(id=str(uuid5(NAMESPACE_URL, binding)), version_id=version.id, locator=locator,
                                     content="\n\n".join(group.values())))
                group.clear()

        for shape_id, value in texts[item.page].items():
            if shape_id in covered or any(f"\n\n{value}\n\n" in f"\n\n{c.content}\n\n" for c in prior):
                continue
            if group and len("\n\n".join([*group.values(), value])) > 1800:
                finish()
            group[shape_id] = value
        finish()
    return pending


def active_source(session, course_id, version_id, source_sha):
    row = session.execute(select(Material, MaterialVersion)
                          .join(MaterialVersion, MaterialVersion.material_id == Material.id)
                          .where(Material.course_id == course_id, MaterialVersion.id == version_id,
                                 Material.active_version_id == version_id, Material.deleted.is_(False),
                                 Material.visibility == "public", Material.internal_use == "none",
                                 Material.kind != "answer", MaterialVersion.status == "ready",
                                 MaterialVersion.sha256 == source_sha)
                          .with_for_update()).one_or_none()
    if row is None or Path(row[1].filename).suffix.lower() != ".pptx":
        raise ValueError("SOURCE_CHANGED")
    return row[1]


def publish_review(session, job):
    from lerny.rag_index import indexed_ids
    from lerny.worker import embed_chunks

    review = SlideReview.model_validate(job.payload["ppt_review"])
    version = active_source(session, job.course_id, job.payload["version_id"], review.source_sha256)
    with source_file(version) as path:
        texts = reviewed_text(path, review)
    existing = list(session.scalars(select(Chunk).where(Chunk.version_id == version.id)))
    new = additions(version, review, texts, existing)
    if new:
        content = "\n\n".join(filter(None, [version.extracted_text, *(chunk.content for chunk in new)]))
        if len(content) > 1_000_000:
            raise ValueError("TEXT_LIMIT")
        embed_chunks(new, session)
        if len(indexed_ids(new, validate_vectors=True)) != len(new):
            raise ValueError("GEMINI_INDEX_REQUIRED")
        version.extracted_text = content
        report = dict(version.extraction_report or {})
        report["source_reviews"] = [*report.get("source_reviews", []), {
            "job_id": job.id, "review": review.model_dump(), "chunk_ids": [c.id for c in new],
        }]
        version.extraction_report = {**report, "usable_chunks": len(existing) + len(new)}
        course = session.scalar(select(Course).where(Course.id == job.course_id)
                                .execution_options(populate_existing=True).with_for_update())
        course.access_epoch += 1
    return {"version_id": version.id, "added_chunks": len(new), "total_chunks": len(existing) + len(new)}
