"use client";

import type { RichStr } from "@opal/types";
import { DepthLoader, Text } from "@opal/components";
import { useOpalStrings } from "@opal/strings";
import { PageCenter } from "@opal/layouts/page-center/components";

// ---------------------------------------------------------------------------
// PageLoader
// ---------------------------------------------------------------------------

interface PageLoaderProps {
  /** Label beneath the mark, markdown() opt-in. Defaults to the Opal loading label. */
  text?: string | RichStr;
}

/**
 * Full-page loading state: the animated Depth mark with a label, centred in
 * the page body by `PageCenter`. Use for page/route-level loading. For an inline or
 * section-level loader without a label, use `DepthLoader` directly.
 */
function PageLoader({ text }: PageLoaderProps) {
  const strings = useOpalStrings();
  return (
    <PageCenter>
      <div className="flex flex-col items-center gap-3 p-5">
        <DepthLoader />
        <Text font="main-ui-muted" color="text-03">
          {text ?? strings.loadingPage}
        </Text>
      </div>
    </PageCenter>
  );
}

export { PageLoader, type PageLoaderProps };
