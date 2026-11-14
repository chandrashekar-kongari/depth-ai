import "@opal/components/buttons/button/styles.css";
import { Interactive, type InteractiveStatelessProps } from "@opal/core";
import type {
  ContainerSizeVariants,
  DistributiveOmit,
  ExtremaSizeVariants,
  RichStr,
} from "@opal/types";
import { type TooltipSide, Tooltip } from "@opal/components";
import { ButtonLabel } from "@opal/components/buttons/button/label";
import type { IconFunctionComponent } from "@opal/types";
import { iconWrapper } from "@opal/components/buttons/icon-wrapper";
import { resolveTriggerInteraction } from "@opal/components/buttons/trigger-interaction";
import { Section } from "@opal/layouts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ButtonContentProps =
  | {
      icon?: IconFunctionComponent;
      children: string | RichStr;
      rightIcon?: IconFunctionComponent;
      responsiveHideText?: never;
    }
  | {
      icon: IconFunctionComponent;
      children?: string | RichStr;
      rightIcon?: IconFunctionComponent;
      responsiveHideText?: boolean;
    };

type ButtonProps = DistributiveOmit<InteractiveStatelessProps, "children"> &
  ButtonContentProps & {
    /**
     * Size preset — controls gap, text size, and Container height/rounding.
     */
    size?: ContainerSizeVariants;

    /** Tooltip text shown on hover. */
    tooltip?: string;

    /** Width preset. `"fit"` shrink-wraps, `"full"` stretches to parent width. */
    width?: ExtremaSizeVariants;

    /** Which side the tooltip appears on. */
    tooltipSide?: TooltipSide;

    /** Applies disabled styling and suppresses clicks. */
    disabled?: boolean;
  };

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

function Button({
  icon: Icon,
  children,
  rightIcon: RightIcon,
  size = "md",
  type = "button",
  width,
  tooltip,
  tooltipSide = "top",
  responsiveHideText = false,
  disabled,
  interaction,
  ...interactiveProps
}: ButtonProps) {
  const isLarge = size === "lg" || size === "md";
  // Only a popup trigger takes the open look: Popover, Dropdown and Dialog
  // triggers set `aria-haspopup`, a Collapsible or disclosure toggle sets
  // `data-state` but opens no popup. An open secondary trigger keeps its rest
  // fill; the stateless styles give it an outline instead of the hover look.
  const popup = interactiveProps["aria-haspopup"];
  const isPopupTrigger =
    popup !== undefined && popup !== false && popup !== "false";
  const resolvedInteraction =
    isPopupTrigger && interactiveProps.prominence !== "secondary"
      ? resolveTriggerInteraction(interaction, interactiveProps)
      : interaction;

  const labelEl = children ? (
    <ButtonLabel
      font={isLarge ? "main-ui-body" : "secondary-body"}
      responsiveHide={responsiveHideText}
    >
      {children}
    </ButtonLabel>
  ) : null;

  const button = (
    <Interactive.Stateless
      type={type}
      disabled={disabled}
      interaction={resolvedInteraction}
      {...interactiveProps}
      data-opal-button={size}
    >
      <Interactive.Container
        type={type}
        border={interactiveProps.prominence === "secondary"}
        size={size}
        width={width}
        rounding={isLarge ? 2 : size === "2xs" ? 1 : 1.5}
      >
        <Section flexDirection="row" gap={0.5} width="fit" height="fit">
          {iconWrapper(Icon, size, false)}

          {labelEl}
          {responsiveHideText ? (
            <Section
              flexDirection="row"
              gap={0}
              width="fit"
              height="fit"
              className="hidden md:flex"
            >
              {iconWrapper(RightIcon, size, false)}
            </Section>
          ) : (
            iconWrapper(RightIcon, size, false)
          )}
        </Section>
      </Interactive.Container>
    </Interactive.Stateless>
  );

  return (
    <Tooltip tooltip={tooltip} side={tooltipSide}>
      {button}
    </Tooltip>
  );
}

export { Button, type ButtonProps };
