// Phosphor Icons 2.1.1: terminal (regular).
import Svg, { Path } from "react-native-svg";
import type { IconProps } from "@/icons/types";

function SvgTerminalSmall({ size = 16, ...props }: IconProps) {
  return (
    <Svg
      width={size}
      height={size}
      viewBox="0 0 256 256"
      fill="currentColor"
      {...props}
    >
      <Path d="M117.31,134l-72,64a8,8,0,1,1-10.63-12L100,128,34.69,70A8,8,0,1,1,45.32,58l72,64a8,8,0,0,1,0,12ZM216,184H120a8,8,0,0,0,0,16h96a8,8,0,0,0,0-16Z" />
    </Svg>
  );
}

export default SvgTerminalSmall;
