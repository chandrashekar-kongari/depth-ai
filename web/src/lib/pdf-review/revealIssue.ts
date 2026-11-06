import type {
  ScrollCapability,
  ScrollScope,
  ScrollToPageOptions,
} from "@embedpdf/plugin-scroll";
import type { IssueFocusTarget } from "@/lib/pdf-review/navigation";
interface RevealIssueOptions {
  documentId: string;
  target: IssueFocusTarget;
  scroll: Pick<ScrollScope, "getLayout" | "scrollToPage">;
  ready: ScrollCapability["onLayoutReady"];
  changed?: ScrollScope["onScroll"];
  canReveal?: () => boolean;
  isVisible?: () => boolean;
  onReveal: () => void;
}
/** Document/page access never changes zoom or depends on annotation saving. */
export function revealIssue({
  documentId,
  target,
  scroll,
  ready,
  changed,
  canReveal = () => true,
  isVisible = () => true,
  onReveal,
}: RevealIssueOptions) {
  let finished = false,
    requested = false;
  function reveal() {
    if (finished || !canReveal()) return;
    if (!requested) {
      if (
        !scroll
          .getLayout()
          .virtualItems.some((item) =>
            item.pageLayouts.some((page) => page.pageNumber === target.page)
          )
      )
        return;
      requested = true;
      const options: ScrollToPageOptions = {
        pageNumber: target.page,
        behavior: "instant",
        alignX: 50,
        alignY: 50,
      };
      if (target.rect)
        options.pageCoordinates = {
          x: target.rect.origin.x + target.rect.size.width / 2,
          y: target.rect.origin.y + target.rect.size.height / 2,
        };
      scroll.scrollToPage(options);
    }
    if (isVisible()) {
      finished = true;
      onReveal();
    }
  }
  const unsubscribe = ready((event) => {
    if (event.documentId === documentId) reveal();
  });
  const unsubscribeScroll = changed?.(() => reveal());
  reveal();
  return () => {
    finished = true;
    unsubscribe();
    unsubscribeScroll?.();
  };
}
