export function StatusDot({ enabled }: { enabled: boolean }) {
  return (
    <span
      className={`status-dot ${enabled ? "status-dot-on" : "status-dot-off"}`}
      aria-label={enabled ? "已配置" : "未配置"}
    />
  );
}
