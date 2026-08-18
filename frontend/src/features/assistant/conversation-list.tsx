import { useTranslations } from "next-intl";

import type { AssistantConversation } from "./contracts";

export function ConversationList({ conversations, selectedId, collapsed, onSelect, onNew, onToggle }: {
  conversations: AssistantConversation[];
  selectedId: string | null;
  collapsed: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onToggle: () => void;
}) {
  const t = useTranslations("assistant");
  return <aside className={`assistant-conversations ${collapsed ? "is-collapsed" : ""}`} aria-label={t("conversations.label")}>
    <div className="assistant-conversations-heading">
      <button type="button" onClick={onNew}>{t("conversations.new")}</button>
      <button aria-expanded={!collapsed} aria-label={t("conversations.toggle")} type="button" onClick={onToggle}>☰</button>
    </div>
    {!collapsed ? <div className="assistant-conversation-items">
      {conversations.length === 0 ? <p>{t("conversations.empty")}</p> : conversations.map((conversation) =>
        <button
          aria-current={conversation.id === selectedId ? "page" : undefined}
          className={conversation.id === selectedId ? "is-active" : ""}
          key={conversation.id}
          type="button"
          onClick={() => onSelect(conversation.id)}
        >{conversation.title ?? t("conversations.untitled")}</button>)}
    </div> : null}
  </aside>;
}
