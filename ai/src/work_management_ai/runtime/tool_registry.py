"""Immutable exact-major Tool manifest registry."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from work_management_ai.runtime.contracts import RiskLevel
from work_management_ai.runtime.manifests import (
    ToolManifest,
    canonical_manifest_fingerprint,
    resolve_contract,
)


class ToolRegistryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    reference: str
    manifest: ToolManifest
    fingerprint: str


class ToolRegistry:
    def __init__(self, manifests: Iterable[ToolManifest] = ()) -> None:
        entries: dict[str, RegisteredTool] = {}
        for manifest in manifests:
            if manifest.risk_level is RiskLevel.EXPLICIT_WRITE and (
                manifest.idempotency != "REQUIRED"
                or manifest.audit != "REQUIRED"
                or "EMPLOYEE" in manifest.roles
                or not manifest.roles
            ):
                raise ToolRegistryError("TOOL_EXPLICIT_WRITE_POLICY_INVALID")
            for contract_path in (manifest.input_contract, manifest.output_contract):
                try:
                    resolve_contract(contract_path)
                except (AttributeError, ImportError, ValueError) as exc:
                    raise ToolRegistryError("TOOL_CONTRACT_INVALID") from exc
            major = manifest.version.split(".", maxsplit=1)[0]
            reference = f"{manifest.name}@{major}"
            if reference in entries:
                raise ToolRegistryError("TOOL_MAJOR_ALREADY_REGISTERED")
            entries[reference] = RegisteredTool(
                reference=reference,
                manifest=manifest,
                fingerprint=canonical_manifest_fingerprint(manifest),
            )
        self._entries: Mapping[str, RegisteredTool] = MappingProxyType(entries)

    def resolve(self, reference: str) -> RegisteredTool:
        try:
            return self._entries[reference]
        except KeyError as exc:
            raise ToolRegistryError("TOOL_NOT_REGISTERED") from exc
