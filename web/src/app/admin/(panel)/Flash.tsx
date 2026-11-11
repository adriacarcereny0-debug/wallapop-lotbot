export default function Flash({ ok }: { ok?: string }) {
  if (!ok) return null;
  const warning = ok.startsWith("⚠");
  return <div className={`notice${warning ? "" : " ok"}`}>{ok}</div>;
}
