"use client";

import { useTranslations } from "next-intl";
import { useDocumentState } from "@embedpdf/core/react";
import { useScroll } from "@embedpdf/plugin-scroll/react";
import { Button } from "@opal/components";
import { cn } from "@opal/utils";
import { anchorRect } from "@/lib/pdf-review/geometry";
import { resolvedAnchor } from "@/lib/pdf-review/anchors";
import { layoutReviewMarkers, type ReviewMarkerTarget, type ReviewMarkerTone } from "@/lib/pdf-review/reviewMarks";
import type { LinkedIssue, WorkspaceSnapshot } from "@/lib/pdf-review/types";

interface ReviewStatusMarkersProps {
  documentId: string;
  pageIndex: number;
  issues: LinkedIssue[];
  snapshot?: WorkspaceSnapshot;
  selectedIssueId?: string | null;
  original: boolean;
  onSelect: (issueId: string, page: number) => void;
}
const colors:Record<ReviewMarkerTone,string>={
  success:"[&_.interactive]:text-status-success-05 [&_.interactive-foreground]:text-status-success-05",
  error:"bg-status-error-05 [&_.interactive]:text-text-light-05 [&_.interactive-foreground]:text-text-light-05",
  warning:"bg-status-warning-05 [&_.interactive]:text-text-dark-05 [&_.interactive-foreground]:text-text-dark-05",
  neutral:"bg-background-neutral-04 [&_.interactive]:text-text-05 [&_.interactive-foreground]:text-text-05",
};

/** Screen-only status controls. They never enter the PDF annotation store. */
export function ReviewStatusMarkers({documentId,pageIndex,issues,snapshot,selectedIssueId,original,onSelect}:ReviewStatusMarkersProps) {
  const t=useTranslations('chat.messages.pdfWorkspace');
  const reviewT=useTranslations('chat.messages.commentReview');
  const {provides:scroll}=useScroll(documentId);
  const state=useDocumentState(documentId);
  const size=state?.document?.pages[pageIndex]?.size;
  const page=size?scroll?.getRectPositionForPage(pageIndex,{origin:{x:0,y:0},size}):null;
  if (!size || !page || !scroll) return null;
  const targets:ReviewMarkerTarget[]=issues.flatMap((issue,index)=>{
    if ((original && issue.verdict==='solved_correct') || (!issue.verdict && issue.id!==selectedIssueId)) return [];
    const anchor=resolvedAnchor(snapshot,documentId,issue);
    if (!anchor || anchor.page!==pageIndex+1) return [];
    const rect=scroll.getRectPositionForPage(pageIndex,anchorRect(anchor,size));
    if (!rect) return [];
    return [{issue,number:index+1,rect:{origin:{x:rect.origin.x-page.origin.x,y:rect.origin.y-page.origin.y},size:rect.size}}];
  });
  const markers=layoutReviewMarkers(targets,page.size.width,page.size.height,Math.max(52,t('markerSolved').length*9+16));
  function status(issue:LinkedIssue):string {
    switch(issue.verdict) {
      case 'solved_correct':return reviewT('solvedCorrectStatus.label');
      case 'open':return reviewT('openStatus.label');
      case 'solved_incorrect':return reviewT('solvedIncorrectStatus.label');
      case 'unclear':return reviewT('unclearStatus.label');
      default:return t('comparisonRegion');
    }
  }
  return <>{markers.map(marker=>{
    const first=marker.targets[0];
    if (!first) return null;
    const grouped=marker.targets.length>1;
    const tooltip=marker.targets.map(target=>t('markerLabel',{status:status(target.issue),finding:t('findingNumber',{number:target.number})})+(target.issue.title?`: ${target.issue.title}`:'')).join('\n');
    const selected=marker.targets.findIndex(target=>target.issue.id===selectedIssueId);
    const next=marker.targets[(selected+1)%marker.targets.length] ?? first;
    const label=grouped?t('markerGroup',{count:marker.targets.length}):tooltip;
    return <div key={first.issue.id} data-testid="pdf-status-marker" data-tone={marker.tone} className={cn('absolute z-30 pointer-events-auto rounded-full print:hidden [&_.interactive]:!bg-transparent',colors[marker.tone],selected>=0 && 'ring-2 ring-status-info-05')} style={{left:marker.rect.origin.x,top:marker.rect.origin.y}}>
      <Button size="2xs" variant="default" prominence="internal" tooltip={tooltip} aria-label={label} aria-pressed={selected>=0} onPointerDown={event=>event.stopPropagation()} onClick={event=>{event.stopPropagation();onSelect(next.issue.id,pageIndex+1);}}>{grouped?String(marker.targets.length):marker.tone==='success'?t('markerSolved'):String(first.number)}</Button>
    </div>;
  })}</>;
}
