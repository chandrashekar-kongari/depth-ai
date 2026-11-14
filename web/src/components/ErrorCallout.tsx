import { Callout } from "@/components/ui/callout";
import { SvgAlertTriangle as FiAlertTriangle } from "@opal/icons";

export function ErrorCallout({
  errorTitle,
  errorMsg,
}: {
  errorTitle?: string;
  errorMsg?: string;
}) {
  return (
    <div>
      <Callout
        className="mt-4"
        title={errorTitle || "Page not found"}
        icon={<FiAlertTriangle className="text-red-500 h-5 w-5" />}
        type="danger"
      >
        {errorMsg}
      </Callout>
    </div>
  );
}
