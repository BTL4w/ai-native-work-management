"""Progressive loader for the Work Intelligence Skill."""

from importlib.resources import files

from work_management_ai.runtime.manifests import SkillManifest, load_yaml_resource

_PACKAGE = "work_management_ai.skills.answer_work_question"


class AnswerWorkQuestionSkillLoader:
    def catalog(self) -> tuple[tuple[str, str], ...]:
        manifest = load_yaml_resource(_PACKAGE, "skill.yaml", SkillManifest)
        return (("answer_work_question@1", manifest.description),)

    def load(self, reference: str) -> tuple[SkillManifest, str]:
        if reference != "answer_work_question@1":
            raise ValueError("SKILL_NOT_ALLOWED")
        manifest = load_yaml_resource(_PACKAGE, "skill.yaml", SkillManifest)
        instructions = files(_PACKAGE).joinpath("SKILL.md").read_text(encoding="utf-8")
        return manifest, instructions


__all__ = ["AnswerWorkQuestionSkillLoader"]
