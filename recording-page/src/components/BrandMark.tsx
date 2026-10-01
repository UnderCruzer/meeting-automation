/** Product mark: a check in a solid square — "from meeting to done". */
export default function BrandMark({ size = 20 }: { size?: number }) {
  return <span className="brand-mark" aria-hidden style={{ width: size, height: size }}>
    <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      style={{ width: size * 0.6, height: size * 0.6 }}><path d="M2.5 6.3 5 8.6l4.5-5.2" /></svg>
  </span>;
}
