"""Progressive Planning Skill loader."""

from importlib.resources import files

from work_management_ai.runtime.manifests import SkillManifest, load_yaml_resource

_PACKAGES = {
    "create_project_plan@1": "work_management_ai.skills.create_project_plan",
    "revise_project_plan@1": "work_management_ai.skills.revise_project_plan",
}


class PlanningSkillLoader:
    def catalog(self) -> tuple[tuple[str, str], ...]:
        catalog: list[tuple[str, str]] = []
        for reference, package in _PACKAGES.items():
            manifest = load_yaml_resource(package, "skill.yaml", SkillManifest)
            catalog.append((reference, manifest.description))
        return tuple(catalog)

    def load(self, reference: str) -> tuple[SkillManifest, str]:
        package = _PACKAGES.get(reference)
        if package is None:
            raise ValueError("PLANNING_SKILL_NOT_ALLOWED")
        manifest = load_yaml_resource(package, "skill.yaml", SkillManifest)
        instructions = files(package).joinpath("SKILL.md").read_text(encoding="utf-8")
        return manifest, instructions


__all__ = ["PlanningSkillLoader"]
