import type { IconProps } from "@opal/types";

const SvgDepthOctagon = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M4 2.5v11M4 2.5c5.5 0 9 2.4 9 5.5s-3.5 5.5-9 5.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgDepthOctagon;
