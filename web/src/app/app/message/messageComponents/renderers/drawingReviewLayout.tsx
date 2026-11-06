"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { ReviewFocusRequest } from "@/lib/pdf-review/types";

interface DrawingReviewLayoutValue {
  active: boolean;
  mode: "checklist" | "comments";
  selectedId: string | null;
  focusRequest: ReviewFocusRequest | null;
  focusIssue: (issueId: string, documentId: string, page: number) => void;
  hoveredId: string | null;
  setHoveredId: (id: string | null) => void;
  pageNumber: number;
  selectFinding: (id: string, page: number) => void;
  setPageNumber: (page: number) => void;
}

const EMPTY_LAYOUT: DrawingReviewLayoutValue = {
  active: false,
  mode: "checklist",
  selectedId: null,
  focusRequest: null,
  focusIssue: () => {},
  hoveredId: null,
  setHoveredId: () => {},
  pageNumber: 1,
  selectFinding: () => {},
  setPageNumber: () => {},
};

const DrawingReviewLayoutContext =
  createContext<DrawingReviewLayoutValue>(EMPTY_LAYOUT);

export function DrawingReviewLayoutProvider({
  active,
  mode = "checklist",
  reviewKey,
  children,
}: {
  active: boolean;
  mode?: "checklist" | "comments";
  reviewKey: string;
  children: ReactNode;
}) {
  const [focusRequest, setFocusRequest] = useState<ReviewFocusRequest | null>(
    null
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const selectFinding = useCallback((id: string, page: number) => {
    setSelectedId(id);
    setPageNumber(page);
  }, []);

  const focusIssue = useCallback(
    (issueId: string, documentId: string, page: number) => {
      setSelectedId(issueId);
      setPageNumber(page);
      setFocusRequest({ id: crypto.randomUUID(), issueId, documentId, page });
    },
    []
  );

  useEffect(() => {
    setFocusRequest(null);
    setSelectedId(null);
    setHoveredId(null);
    setPageNumber(1);
  }, [reviewKey]);

  const value = useMemo(
    () => ({
      active,
      mode,
      selectedId,
      focusRequest,
      focusIssue,
      hoveredId,
      setHoveredId,
      pageNumber,
      selectFinding,
      setPageNumber,
    }),
    [
      active,
      mode,
      pageNumber,
      selectFinding,
      selectedId,
      hoveredId,
      focusRequest,
      focusIssue,
    ]
  );

  return (
    <DrawingReviewLayoutContext.Provider value={value}>
      {children}
    </DrawingReviewLayoutContext.Provider>
  );
}

export function useDrawingReviewLayout(): DrawingReviewLayoutValue {
  return useContext(DrawingReviewLayoutContext);
}
