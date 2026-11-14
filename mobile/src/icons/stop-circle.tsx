// Phosphor Icons 2.1.1: stop-circle (regular).
import Svg, { Path } from "react-native-svg";
import type { IconProps } from "@/icons/types";

function SvgStopCircle({ size = 16, ...props }: IconProps) {
  return (
    <Svg
      width={size}
      height={size}
      viewBox="0 0 256 256"
      fill="currentColor"
      {...props}
    >
      <Path d="M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm0,192a88,88,0,1,1,88-88A88.1,88.1,0,0,1,128,216ZM160,88H96a8,8,0,0,0-8,8v64a8,8,0,0,0,8,8h64a8,8,0,0,0,8-8V96A8,8,0,0,0,160,88Zm-8,64H104V104h48Z" />
    </Svg>
  );
}

export default SvgStopCircle;
