import { useTranslations } from "next-intl";

export function ApprovalCard({
  version,
  canDecide,
  canApprove,
  blockedReason,
  onApprove,
  onReject,
}: {
  version: number;
  canDecide: boolean;
  canApprove: boolean;
  blockedReason?: string;
  onApprove: () => void;
  onReject: () => void;
}) {
  const t = useTranslations("ai");
  return (
    <section aria-labelledby="approval-card" className="ai-card">
      <h3 id="approval-card">{t("card.approval")}</h3>
      <p>{t("proposalVersion", { version })}</p>
      <p>{t("noRowsBeforeApproval")}</p>
      {blockedReason ? <p className="error-message">{blockedReason}</p> : null}
      <div className="ai-actions">
        <button disabled={!canDecide} type="button" onClick={onReject}>{t("action.reject")}</button>
        <button disabled={!canApprove} type="button" onClick={onApprove}>{t("action.approve")}</button>
      </div>
    </section>
  );
}
