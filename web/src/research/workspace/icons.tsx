const shapes: Record<string, string> = {
  close: "M6 6l12 12M18 6L6 18",
  minimize: "M5 18h14",
  maximize: "M9 4H4v5M15 4h5v5M4 15v5h5M20 15v5h-5",
  restore: "M4 9h5V4M20 9h-5V4M4 15h5v5M20 15h-5v5",
  split: "M3 4h18v16H3zM12 4v16",
  lock: "M5 10h14v11H5zM8 10V6a4 4 0 018 0v4",
  pin: "M8 3h8l-1 6 4 5H5l4-5zM12 14v7",
  source: "M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h4",
  data: "M3 3h18v18H3zM3 9h18M3 15h18M9 3v18M15 3v18",
  graph: "M2 9h5v6H2zM16 2h6v6h-6zM16 16h6v6h-6zM7 12h4V5h5M11 12v7h5",
  probes: "M5 20l4-4 2-6 3-3 3 3-3 3-6 2M14 7l3-3 4 4-3 3",
  tools: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM17.5 14v7M14 17.5h7",
  intelligence: "M5 5h14v11H9l-4 4zM8 9h8M8 12h5",
  changes: "M5 3h14v18H5zM9 8h6M9 12h6M9 16h3",
  context: "M4 4h16v16H4zM8 8h8M8 12h8M8 16h4",
  tasks: "M5 4v16l14-8z",
  terminal: "M4 6l6 6-6 6M12 18h8",
  search: "M15 15l6 6M16 10a6 6 0 11-12 0 6 6 0 0112 0",
  settings: "M4 7h16M4 17h16M9 4v6M15 14v6",
  add: "M12 5v14M5 12h14",
  run: "M7 4v16l13-8z",
  chevron: "M7 10l5 5 5-5",
  check: "M5 12l4 4L19 6",
};
export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={shapes[name] ?? shapes.data} />
    </svg>
  );
}
