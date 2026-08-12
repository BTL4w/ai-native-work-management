# pyright: reportUnknownParameterType=false, reportMissingParameterType=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false

from uuid import uuid4

import pytest

from app.modules.assistant.application.job_service import AssistantJobService
from app.modules.assistant.domain.models import AssistantJob


class Repo:
    def __init__(self, job):
        self.job, self.commits, self.completed = job, 0, False

    async def claim_job(self, **kwargs):
        return self.job

    async def complete_job(self, **kwargs):
        self.completed = True

    async def fail_job(self, **kwargs) -> None:
        raise AssertionError("unexpected failure")


class Txn:
    def __init__(self, repo):
        self.repository, self.repo = repo, repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def commit(self):
        self.repo.commits += 1


@pytest.mark.asyncio
async def test_job_claim_commits_before_handler_begins() -> None:
    org = uuid4()
    job = AssistantJob.create(
        organization_id=org,
        conversation_id=uuid4(),
        turn_id=uuid4(),
        orchestration_run_id=uuid4(),
        requester_membership_id=uuid4(),
        payload={},
    )
    repo = Repo(job)

    async def handler(*, job, worker_id):
        assert repo.commits == 1

    service = AssistantJobService(
        transaction_factory=lambda _: Txn(repo),  # type: ignore[arg-type]
        handler=handler,
        organization_scopes={org},
    )
    assert await service.run_once(worker_id="worker", organization_id=org)
    assert repo.completed


@pytest.mark.asyncio
async def test_job_failure_never_persists_raw_provider_exception() -> None:
    org = uuid4()
    job = AssistantJob.create(
        organization_id=org,
        conversation_id=uuid4(),
        turn_id=uuid4(),
        orchestration_run_id=uuid4(),
        requester_membership_id=uuid4(),
        payload={},
    )

    class FailureRepo(Repo):
        error_code: str | None = None

        async def fail_job(self, **kwargs):
            self.error_code = kwargs["error_code"]

    repo = FailureRepo(job)

    async def handler(**_):
        raise RuntimeError("sk-secret provider response and SQL details")

    service = AssistantJobService(
        transaction_factory=lambda _: Txn(repo),  # type: ignore[arg-type]
        handler=handler,
        organization_scopes={org},
    )

    assert await service.run_once(worker_id="worker", organization_id=org)
    assert repo.error_code == "ASSISTANT_EXECUTION_FAILED"
    assert "secret" not in repo.error_code.lower()


@pytest.mark.asyncio
async def test_worker_rejects_tenant_outside_configured_scope_before_claim() -> None:
    allowed, foreign = uuid4(), uuid4()

    class NoTransaction:
        def __call__(self, _):
            raise AssertionError("foreign tenant must not open a transaction")

    async def handler(**_):
        raise AssertionError("handler must not run")

    service = AssistantJobService(
        transaction_factory=NoTransaction(),  # type: ignore[arg-type]
        handler=handler,
        organization_scopes={allowed},
    )

    with pytest.raises(ValueError, match="TENANT_SCOPE_VIOLATION"):
        await service.run_once(worker_id="worker", organization_id=foreign)
