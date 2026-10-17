/** The Agent Mandate mark: a shield holding a small authority graph, one person at the top
 *  and the two things their word reaches. Sits on the gradient tile from `.brand-mark`. */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <span className="brand-mark" aria-hidden="true" style={{ width: size, height: size }}>
      <svg viewBox="0 0 32 32" width={size * 0.78} height={size * 0.78} fill="none">
        <path
          d="M16 4.5 25.5 8.2V15.6C25.5 21 21.7 25 16 27.5 10.3 25 6.5 21 6.5 15.6V8.2Z"
          fill="#fff"
        />
        <path
          d="M16 12.2 11.8 19.2M16 12.2 20.2 19.2M11.8 19.2H20.2"
          stroke="#4f46e5"
          strokeWidth="1.3"
          strokeLinecap="round"
        />
        <circle cx="16" cy="12.2" r="2.3" fill="#4f46e5" />
        <circle cx="11.8" cy="19.2" r="1.8" fill="#8b5cf6" />
        <circle cx="20.2" cy="19.2" r="1.8" fill="#ec4899" />
      </svg>
    </span>
  );
}
