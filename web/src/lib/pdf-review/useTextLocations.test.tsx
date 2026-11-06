import { render, screen, waitFor } from "@tests/setup/test-utils";
import { useTextLocations } from "@/lib/pdf-review/useTextLocations";
import { locationKey, resolvedAnchor } from "@/lib/pdf-review/anchors";
import type { LinkedIssue, WorkspaceSnapshot } from "@/lib/pdf-review/types";
const issue: LinkedIssue = {
  id: "c4",
  title: "Thickness",
  request: "Specify 8.0 ±0.1",
  evidence: "8.0 ±0.1. Stock: aluminum",
  remaining: "",
  anchors: { revised: { page: 1, box: null, pageLevel: true } },
};
const snapshot: WorkspaceSnapshot = {
  id: "text-location-test",
  version: 0,
  can_undo: false,
  can_redo: false,
  documents: [],
  state: { annotations: {}, anchors: {}, calibrations: {} },
};
function Result() {
  const result = useTextLocations(snapshot, "revised", [issue]);
  const located = result.issues[0];
  return (
    <output aria-label="Location">
      {JSON.stringify({
        loaded: !!result.data,
        key: located ? locationKey(located) : null,
        anchor: located ? resolvedAnchor(snapshot, "revised", located) : null,
      })}
    </output>
  );
}
it("uses library coordinates while keeping manual correction identity stable", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => [
      {
        id: "c4",
        status: "located_text",
        source: "pdfplumber",
        text: "8.0 ±0.1",
        candidate_count: 1,
        anchor: { page: 1, x: 0.529, y: 0.71, width: 0.032, height: 0.01 },
      },
    ],
  });
  render(<Result />);
  await waitFor(() =>
    expect(
      JSON.parse(screen.getByLabelText("Location").textContent ?? "{}")
    ).toEqual({
      loaded: true,
      key: locationKey(issue),
      anchor: { page: 1, x: 0.529, y: 0.71, width: 0.032, height: 0.01 },
    })
  );
  expect(fetch).toHaveBeenCalledWith(
    "/api/engineering/workspaces/text-location-test/locations",
    expect.objectContaining({ method: "POST" })
  );
});
