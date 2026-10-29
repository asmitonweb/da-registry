"""No direct approval: only the approval task decides.

The guard is a mixin on the DA services registered ahead of the platform's
(imports the extension, so it runs in the container).
"""

import ast
import asyncio
from pathlib import Path

import pytest
from openg2p_fastapi_common.component import BaseComponent

from openg2p_registry_da_extension.register_domain.services import component_registration, direct_approval
from openg2p_registry_da_extension.register_domain.services.da_change_request import (
    DAChangeRequestService,
    install_da_change_request_service,
)
from openg2p_registry_da_extension.register_domain.services.da_intake_guard import (
    DAIntakeFormDataService,
    install_da_intake_guard,
)

SERVICES = Path(direct_approval.__file__).parent
WORKFLOW_METHODS = {"approve_submission_with_session", "approve_change_request_from_awe_webhook",
                    "_approve_change_request_core"}


class _Base:
    """Stands in for the platform service: records the calls the guard lets through."""

    def __init__(self):
        self.calls = []

    async def approve_submission(self, submission_id, approved_by):
        self.calls.append("approve_submission")

    async def approve_change_request(self, change_request_id, approved_by=None):
        self.calls.append("approve_change_request")

    async def approve_submission_with_session(self, submission_id, session, approved_by=None):
        self.calls.append("approve_submission_with_session")
        return "approved"

    async def approve_change_request_from_awe_webhook(self, change_request_id, session, approved_by=None):
        self.calls.append("approve_change_request_from_awe_webhook")
        return "applied"


class _Guarded(direct_approval.DirectApprovalClosed, _Base):
    pass


def _refusal(coroutine):
    with pytest.raises(Exception) as caught:
        asyncio.run(coroutine)
    return caught.value


def test_direct_submission_approval_is_refused_and_never_reaches_the_platform():
    service = _Guarded()
    error = _refusal(service.approve_submission("submission-1", "someone"))
    assert error.code == "AWE_APPROVAL_REQUIRED"
    assert "approval task" in error.message
    assert service.calls == []


def test_direct_change_request_approval_is_refused_and_never_reaches_the_platform():
    service = _Guarded()
    error = _refusal(service.approve_change_request("change-1", "admin"))
    assert error.code == "AWE_APPROVAL_REQUIRED"
    assert service.calls == []


def test_the_refusal_holds_for_any_arguments():
    service = _Guarded()
    _refusal(service.approve_submission("submission-1", approved_by="admin"))
    _refusal(service.approve_change_request(change_request_id="change-1", approved_by="admin"))
    assert service.calls == []


def test_the_workflow_engine_decisions_still_reach_the_platform():
    service = _Guarded()
    assert asyncio.run(service.approve_submission_with_session("submission-1", object())) == "approved"
    assert asyncio.run(service.approve_change_request_from_awe_webhook("change-1", object())) == "applied"
    assert service.calls == ["approve_submission_with_session", "approve_change_request_from_awe_webhook"]


def test_the_guard_defines_only_the_two_direct_calls():
    tree = ast.parse((SERVICES / "direct_approval.py").read_text())
    mixin = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DirectApprovalClosed")
    defined = {n.name for n in mixin.body if isinstance(n, ast.AsyncFunctionDef)}
    assert defined == {"approve_submission", "approve_change_request"}
    assert not defined & WORKFLOW_METHODS


@pytest.mark.parametrize("service_class", [DAIntakeFormDataService, DAChangeRequestService])
def test_the_installed_services_carry_the_guard_first(service_class):
    mro = service_class.__mro__
    platform = next(c for c in mro if c.__module__.startswith("openg2p_registry_core"))
    assert direct_approval.DirectApprovalClosed in mro[:3]
    assert mro.index(direct_approval.DirectApprovalClosed) < mro.index(platform)


def test_the_installed_services_are_resolved_ahead_of_the_platform_ones():
    from openg2p_registry_core.services import G2PIntakeFormDataService, G2PRegisterChangeRequestService

    intake = install_da_intake_guard()
    change_request = install_da_change_request_service()
    assert G2PIntakeFormDataService.get_component() is intake
    assert G2PRegisterChangeRequestService.get_component() is change_request
    # idempotent: a second install returns the same instance
    assert install_da_intake_guard() is intake
    assert install_da_change_request_service() is change_request


def test_the_installed_intake_service_refuses_direct_approval():
    service = install_da_intake_guard()
    error = _refusal(service.approve_submission("submission-1", "admin"))
    assert error.code == "AWE_APPROVAL_REQUIRED"


def test_register_ahead_of_platform_puts_the_instance_first_once():
    class Probe(BaseComponent):
        pass

    first = component_registration.register_ahead_of_platform(Probe)
    try:
        assert component_registration.component_registry[0] is first
        assert component_registration.register_ahead_of_platform(Probe) is first
        assert sum(1 for c in component_registration.component_registry if type(c) is Probe) == 1
    finally:
        component_registration.component_registry.remove(first)
