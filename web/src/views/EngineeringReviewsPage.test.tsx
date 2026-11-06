import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import EngineeringReviewsPage from "@/views/EngineeringReviewsPage";
import type { EngineeringReview } from "@/lib/engineering/types";

const mockMutate = jest.fn();
const mockQueueMutate = jest.fn();
let mockReview: EngineeringReview | undefined;
jest.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));
jest.mock("next/dynamic", () => () => () => null);
jest.mock("@/lib/engineering/hooks", () => ({
  useEngineeringReviews: () => ({
    data: mockReview ? [mockReview] : [],
    mutate: mockQueueMutate,
  }),
  useEngineeringReview: () => ({ data: mockReview, mutate: mockMutate }),
}));

beforeEach(() => {
  mockReview = undefined;
  mockMutate.mockReset();
  mockQueueMutate.mockReset();
  jest.restoreAllMocks();
});

it("requires both explicit file roles and sheet-order confirmation", async () => {
  const user = setupUser();
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response("{}", { status: 503 }));
  const { container } = render(<EngineeringReviewsPage />);
  const inputs =
    container.querySelectorAll<HTMLInputElement>('input[type="file"]');
  expect(inputs).toHaveLength(2);
  const oldFile = new File(["%PDF-old"], "original.pdf", {
    type: "application/pdf",
  });
  const newFile = new File(["%PDF-new"], "revised.pdf", {
    type: "application/pdf",
  });
  const first = inputs.item(0);
  const second = inputs.item(1);
  await user.upload(first, oldFile);
  await user.upload(second, newFile);
  expect(screen.getByRole("button", { name: "Submit Review" })).toBeDisabled();
  await user.click(
    screen.getByRole("button", { name: "Confirm matching sheet order" })
  );
  await user.click(screen.getByRole("button", { name: "Submit Review" }));
  await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
  const sent = fetchSpy.mock.calls[0]?.[1]?.body;
  expect(sent).toBeInstanceOf(FormData);
  if (!(sent instanceof FormData)) throw new Error("Missing upload form");
  expect(sent.get("original")).toBe(oldFile);
  expect(sent.get("revised")).toBe(newFile);
  expect(sent.get("page_order_confirmed")).toBe("true");
  await screen.findByText(
    "The request failed. Check that private reviews are enabled, then retry."
  );
  await user.click(screen.getByRole("button", { name: "Submit Review" }));
  await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
  const retried = fetchSpy.mock.calls[1]?.[1]?.body;
  expect(retried).toBeInstanceOf(FormData);
  if (!(retried instanceof FormData)) throw new Error("Missing retry form");
  expect(retried.get("request_key")).toBe(sent.get("request_key"));
});
