import SvgDepthLogo from "@opal/logos/depth-logo";
import SvgDepthWordmark from "@opal/logos/depth-wordmark";
import { cn } from "@opal/utils";

interface DepthLogoWordmarkProps {
  size?: number;
  className?: string;
}

// # NOTE(@raunakab):
// This ratio is not some random, magical number; it is available on Figma.
const HEIGHT_TO_GAP_RATIO = 5 / 16;

const SvgDepthLogoWordmark = ({
  size: height,
  className,
}: DepthLogoWordmarkProps) => {
  const gap = height != null ? height * HEIGHT_TO_GAP_RATIO : undefined;

  return (
    <div
      className={cn(`flex flex-row items-center`, className)}
      style={{ gap }}
    >
      <SvgDepthLogo size={height} />
      <SvgDepthWordmark size={height} />
    </div>
  );
};
export default SvgDepthLogoWordmark;
