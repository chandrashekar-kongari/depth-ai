import type { IconProps } from "@opal/types";

const SvgDepthLogo = ({ size, ...props }: IconProps) => (
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
      d="M4 2.5v11M4 2.5c5.5 0 9 2.4 9 5.5s-3.5 5.5-9 5.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M4 5.5c3.6 0 6 1.4 6 2.5s-2.4 2.5-6 2.5"
      strokeOpacity={0.75}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M4 7.75c1.8 0 3 .6 3 1.25s-1.2 1.25-3 1.25"
      strokeOpacity={0.75}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgDepthLogo;
