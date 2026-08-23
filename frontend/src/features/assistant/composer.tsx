import { useEffect, useRef, type FormEvent } from "react";
import { useTranslations } from "next-intl";

export function Composer({ value, disabled, autoFocus, onChange, onSubmit }: {
  value: string;
  disabled: boolean;
  autoFocus: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const t = useTranslations("assistant");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { if (autoFocus) inputRef.current?.focus(); }, [autoFocus]);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (value.trim() && !disabled) onSubmit();
  }
  return <form className="assistant-composer" onSubmit={submit}>
    <label className="sr-only" htmlFor="assistant-message">{t("composer.label")}</label>
    <textarea
      ref={inputRef}
      id="assistant-message"
      maxLength={8000}
      placeholder={t("composer.placeholder")}
      rows={1}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          if (value.trim() && !disabled) onSubmit();
        }
      }}
    />
    <div className="assistant-composer-footer">
      <span className="assistant-composer-mode"><span aria-hidden="true">◇</span>{t("composer.mode")}</span>
      <button aria-label={t("composer.send")} disabled={disabled || !value.trim()} type="submit">
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2"><path d="M12 19V5m-6 6 6-6 6 6" /></svg>
      </button>
    </div>
  </form>;
}
