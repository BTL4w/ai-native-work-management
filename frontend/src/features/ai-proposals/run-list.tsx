import { useTranslations } from "next-intl";

import type { WorkflowRun } from "./contracts";

export function RunList({
  runs,
  selectedId,
  onSelect,
}: {
  runs: WorkflowRun[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const t = useTranslations("ai");
  return (
    <section aria-labelledby="ai-recent-runs" className="ai-run-list">
      <h2 id="ai-recent-runs">{t("recentRuns")}</h2>
      {runs.length === 0 ? <p>{t("emptyRuns")}</p> : (
        <ul>
          {runs.map((run) => (
            <li key={run.id}>
              <button
                aria-current={selectedId === run.id ? "page" : undefined}
                type="button"
                onClick={() => onSelect(run.id)}
              >
                <span>{run.input_goal_text}</span>
                <small>{t(`status.${run.status}`)}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
