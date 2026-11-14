// Phosphor Icons 2.1.1: plus (regular).
import Svg, { Path } from "react-native-svg";
import type { IconProps } from "@/icons/types";

function SvgPlus({ size = 16, ...props }: IconProps) {
  return (
    <Svg
      width={size}
      height={size}
      viewBox="0 0 256 256"
      fill="currentColor"
      {...props}
    >
      <Path d="M224,128a8,8,0,0,1-8,8H136v80a8,8,0,0,1-16,0V136H40a8,8,0,0,1,0-16h80V40a8,8,0,0,1,16,0v80h80A8,8,0,0,1,224,128Z" />
    </Svg>
  );
}

export default SvgPlus;
