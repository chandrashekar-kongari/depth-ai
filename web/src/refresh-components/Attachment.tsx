import { Text, Button, OverflowText } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgFileText, SvgMaximize2 } from "@opal/icons";
import { useTranslations } from "next-intl";
export interface AttachmentsProps {
  fileName: string;
  open?: () => void;
}

export default function Attachments({ fileName, open }: AttachmentsProps) {
  const t = useTranslations("common.attachment");
  return (
    <Section
      flexDirection="row"
      justifyContent="start"
      width="fit"
      height="fit"
      gap={2}
      padding={1.5}
      className="max-w-full min-w-0 border border-border-01 bg-background-tint-00 rounded-08"
    >
      <div className="shrink-0 p-2 bg-background-neutral-02 rounded-08">
        <SvgFileText className="w-5 h-5 stroke-text-03" />
      </div>
      <Section
        alignItems="stretch"
        width="fit"
        height="fit"
        gap={0}
        className="min-w-0 flex-1"
      >
        <OverflowText as="p" font="secondary-action" color="text-05">
          {fileName}
        </OverflowText>
        <Text as="p" font="secondary-body" color="text-03">
          {t("document.label")}
        </Text>
      </Section>

      {open && (
        <Button
          aria-label={t("expandButton.ariaLabel")}
          onClick={open}
          icon={SvgMaximize2}
          prominence="tertiary"
          size="sm"
        />
      )}
    </Section>
  );
}
