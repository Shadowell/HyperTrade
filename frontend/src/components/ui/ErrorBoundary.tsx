import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
  /** Shown above the error message, e.g. "This section crashed; the rest of the console works." */
  title: string;
  retryLabel: string;
  /** When this changes, a crashed boundary clears itself (e.g. the operator switched section). */
  resetKey?: string;
};

type State = { error: Error | null };

/**
 * One crashing component must not blank the whole operator console. Wrap each independent
 * region in its own boundary so the rest keeps working and the operator can retry just that part.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[console] a section crashed", error, info.componentStack);
  }

  componentDidUpdate(previous: Props) {
    if (this.state.error && previous.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="mt-5 rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm" role="alert">
        <div className="font-semibold text-danger">{this.props.title}</div>
        <div className="mt-1 font-mono text-xs text-ink/55">{error.message}</div>
        <button
          className="icon-button mt-3"
          onClick={() => this.setState({ error: null })}
          type="button"
        >
          {this.props.retryLabel}
        </button>
      </div>
    );
  }
}
