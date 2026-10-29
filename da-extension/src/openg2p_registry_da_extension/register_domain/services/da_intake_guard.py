"""A DA submission cannot be saved empty or sent for approval incomplete.

The platform's intake service validates a section's records when they are
saved, but only the fields the request carries, and at finalize it validates
nothing: a form saved with its required fields left out (the staff UI omits
untouched fields) reaches the approvers as an empty record. The checks live in
RequiredFieldsMixin (required_fields_mixin.py), driven by the register metadata
(required_fields.py); this module puts them, and the closed direct approval
(direct_approval.py), in front of the platform's service as one class:

- save: a new record of a web-intake submission must carry every required,
  visible field of that section, so "Next" on an empty section is refused;
- finalize: every section of the submission is checked for every channel
  (web, file import, partner push), so an incomplete submission never starts
  an approval.

Imports and DA Services pushes are also checked when the record is validated
for the register (g2p_register_domain_service_da.py); a refused record shows in
the DA Services exceptions list with the readable reason.

Installed with install_da_intake_guard(): the instance goes to the front of
the platform's component registry, so G2PIntakeFormDataService.get_component()
(what the controllers call) resolves to it. No platform code is changed.
"""

from __future__ import annotations

import logging

from openg2p_registry_core.services.intake_form_data_service import G2PIntakeFormDataService

from .component_registration import register_ahead_of_platform
from .direct_approval import DirectApprovalClosed
from .required_fields_mixin import RequiredFieldsMixin

_logger = logging.getLogger("da-intake-guard")


class DAIntakeFormDataService(RequiredFieldsMixin, DirectApprovalClosed, G2PIntakeFormDataService):
    """The one DA intake service: required fields checked, no direct approval."""


def install_da_intake_guard() -> DAIntakeFormDataService:
    """Register the DA intake service ahead of the platform's."""
    service = register_ahead_of_platform(DAIntakeFormDataService)
    _logger.info("DA intake guard installed: required fields checked on save and finalize; no direct approval")
    return service
