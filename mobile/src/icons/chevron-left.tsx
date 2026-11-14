// Phosphor Icons 2.1.1: caret-left (regular).
import Svg, { Path } from "react-native-svg";
import type { IconProps } from "@/icons/types";

function SvgChevronLeft({ size = 16, ...props }: IconProps) {
  return (
    <Svg
      width={size}
      height={size}
      viewBox="0 0 256 256"
      fill="currentColor"
      {...props}
    >
      <Path d="M165.66,202.34a8,8,0,0,1-11.32,11.32l-80-80a8,8,0,0,1,0-11.32l80-80a8,8,0,0,1,11.32,11.32L91.31,128Z" />
    </Svg>
  );
}

export default SvgChevronLeft;
