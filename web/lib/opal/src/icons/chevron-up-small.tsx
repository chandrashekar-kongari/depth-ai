// Phosphor Icons 2.1.1: caret-up (regular).
import type { IconProps } from "@opal/types";

function SvgChevronUpSmall({ size, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 256 256"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <g stroke="none">
        <path d="M213.66,165.66a8,8,0,0,1-11.32,0L128,91.31,53.66,165.66a8,8,0,0,1-11.32-11.32l80-80a8,8,0,0,1,11.32,0l80,80A8,8,0,0,1,213.66,165.66Z" />
      </g>
    </svg>
  );
}

export default SvgChevronUpSmall;
