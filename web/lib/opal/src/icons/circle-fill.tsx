// Phosphor Icons 2.1.1: circle (fill).
import type { IconProps } from "@opal/types";

function SvgCircleFill({ size, ...props }: IconProps) {
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
        <path d="M232,128A104,104,0,1,1,128,24,104.13,104.13,0,0,1,232,128Z" />
      </g>
    </svg>
  );
}

export default SvgCircleFill;
