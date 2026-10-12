import { Notice, WeaveMark } from '../shared/ui'

export function ProductLoadingScreen({ title, copy, error, onRetry }) {
  return (
    <main className="product-loading-page">
      <section className="product-loading-card" aria-live="polite">
        <div className="product-loading-orbit"><WeaveMark /></div>
        <span className="product-kicker">WEAVE CBT</span>
        <h1>{title}</h1>
        <p>{copy}</p>
        {error && <Notice tone="danger">{error}</Notice>}
        {error && onRetry && <button className="button button--primary" onClick={onRetry}>Try again</button>}
      </section>
    </main>
  )
}
