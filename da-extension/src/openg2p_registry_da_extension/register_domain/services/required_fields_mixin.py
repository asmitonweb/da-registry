"""Required-field checks for the DA intake service, from the register metadata.

widget-required (with the show / hide / require conditions of
widget-data-options, see required_fields.py) is the single source of truth.

- save ("Next"): a new record of a web-intake section must carry every
  required, visible field of that section. A partial update only has its blank
  fields refused. A list section left with no rows is refused too.
- submit (finalize): every section of the submission is checked on the server
  for every channel - web, file import and partner push - so an incomplete
  submission never starts an approval.

Messages are readable and name the section, e.g.
"Cannot submit for approval. Required: DA contact details: fill in Mobile Number".
"""

from __future__ import annotations

import logging

from openg2p_registry_da_extension.register_domain.services.domain_validation_utils import validation_error
from openg2p_registry_da_extension.register_domain.services.required_fields import (
    describe,
    has_requirements,
    problems,
    section_name_of,
)
from openg2p_registry_da_extension.register_domain.services.validation_rules import is_interactive

_logger = logging.getLogger("da-intake-guard")

EMPTY_LIST = "add at least one row"


def _add(found: dict[str, list[str]], name: str, phrases: list[str]) -> None:
    bucket = found.setdefault(name, [])
    for phrase in phrases:
        if phrase not in bucket:
            bucket.append(phrase)
    if not bucket:
        del found[name]


def _sentence(found: dict[str, list[str]]) -> str:
    return "Required: " + "; ".join(describe(name, phrases) for name, phrases in found.items())


class RequiredFieldsMixin:
    """Placed ahead of the platform intake service; see the module docstring."""

    async def save_intake_form_submission_with_session(
        self, submission_id, section_id, section_payload, section_register_id, form_id, register_id,
        created_by, session, documents=None,
    ):
        section = await self._get_section_or_error(section_id, session)
        schema = section.section_ui_schema
        if has_requirements(schema):
            existing = await self._existing_record_ids(submission_id, section_register_id, session)
            name = section_name_of(section)
            found: dict[str, list[str]] = {}
            records = [r for r in self._records_for_validation(section_payload) if isinstance(r, dict)]
            for record in records:
                if not is_interactive(record):
                    continue
                # A record is new unless the submission already holds it, whatever
                # edit_action the client put on it: the staff UI sends UPDATE for a
                # section it believes it saved, even when nothing was stored.
                new = str(record.get("internal_record_id") or "") not in existing
                _add(found, name, problems(schema, record, absent_is_missing=new))
            if getattr(section, "is_list", False):
                kept = {str(r.get("internal_record_id")) for r in records if r.get("internal_record_id")} | existing
                deleted = {
                    str(r.get("internal_record_id")) for r in (section_payload or [])
                    if isinstance(r, dict) and r.get("edit_action") == "DELETE"
                }
                if not records and not (kept - deleted):
                    _add(found, name, [EMPTY_LIST])
            if found:
                validation_error(_sentence(found))
        return await super().save_intake_form_submission_with_session(
            submission_id, section_id, section_payload, section_register_id, form_id, register_id,
            created_by, session, documents=documents,
        )

    async def _existing_record_ids(self, submission_id, section_register_id, session) -> set[str]:
        """internal_record_ids the submission already stores for this register."""
        if not submission_id:
            return set()
        try:
            submission = await self._get_submission_or_error(submission_id, session)
            intake_class = await self._resolve_intake_form_class(section_register_id, session)
            rows = await self._get_intake_rows(intake_class, submission.submission_id, session)
        except Exception as exc:  # noqa: BLE001 - unknown submission: the platform decides below
            _logger.info("intake guard: no stored rows for submission %s (%s)", submission_id, exc)
            return set()
        # The platform returns {internal_record_id: row}; accept a list of rows too.
        ids = rows.keys() if isinstance(rows, dict) else (getattr(r, "internal_record_id", None) for r in rows)
        return {str(i) for i in ids if i}

    async def finalize_submission_with_session(
        self, submission_id, session, finalized_by=None, bearer_token=None, requester_sub=None,
    ):
        submission = await self._get_submission_or_error(submission_id, session)
        sections = await self._get_form_sections(submission.form_id, session)
        payloads = {p.section_id: p for p in await self._build_section_payloads(submission, session)}
        found: dict[str, list[str]] = {}
        for section in sections:
            schema = section.section_ui_schema
            if not has_requirements(schema):
                continue
            payload = payloads.get(section.section_id)
            records = [r for r in (payload.records if payload else []) if isinstance(r, dict)]
            name = section_name_of(section)
            if getattr(section, "is_list", False):
                # A list section needs one row; each row carries its own required fields.
                if not records:
                    _add(found, name, [EMPTY_LIST])
                targets = records
            else:
                targets = [records[0] if records else {}]
            for record in targets:
                _add(found, name, problems(schema, record, absent_is_missing=True))
        if found:
            validation_error("Cannot submit for approval. " + _sentence(found))
        return await super().finalize_submission_with_session(
            submission_id, session, finalized_by, bearer_token=bearer_token, requester_sub=requester_sub,
        )
