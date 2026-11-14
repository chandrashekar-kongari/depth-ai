import type { IconProps } from "@opal/types";

export default function SvgHand({ size, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <path
        d="M5 8V3.5a1 1 0 0 1 2 0V7 2.5a1 1 0 0 1 2 0V7 3.5a1 1 0 0 1 2 0v4-2a1 1 0 0 1 2 0V10a4.5 4.5 0 0 1-4.5 4.5H8a4 4 0 0 1-3.2-1.6L2 9.2a1.1 1.1 0 0 1 1.6-1.5L5 9"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
