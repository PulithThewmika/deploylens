export function TopBar() {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-4">
      <span className="font-heading text-lg font-semibold tracking-wide text-text">
        DeployLens
      </span>
      <div className="flex items-center gap-2 text-xs text-text-muted">
        <span className="h-2 w-2 rounded-full bg-healthy" />
        <span className="hidden md:inline">All systems normal</span>
      </div>
    </header>
  )
}
