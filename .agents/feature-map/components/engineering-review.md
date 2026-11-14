# Engineering Review Queue

> Owner-scoped two-PDF review queue with private inference, worker leases, evidence, engineer decisions, and JSON export.

**Verified against:** `3eb6420f6c` (2026-11-01)
**Edition:** CE. Single-tenant pilot, disabled by default.

---

## User experience

The opt-in `/app/reviews` page accepts an original commented PDF and a revised PDF.
The user confirms equal sheet order. Both PDFs must have 1–8 pages and at most 20 MiB.
Users see their own queued reviews, PDF evidence, model proposals, and append-only engineer decisions.
JSON export records input hashes, pipeline version, results and decision history.
The pilot does not approve drawing release.

Chat also offers `review_with_vision` for explicit vision review requests. For a
PDF pair, the tool indexes views on the first eight pages of each revision.
It uses the Captioning LLM to detect core and complete view boundaries and
compare matched crops. Before matching, Onyx separates neighboring crops at visible gaps, assigns native dimensions
using extension-line references when available, and ranks colored review marks within each view.
The model rechecks crops that still cross a neighboring core. Unresolved overlap blocks detailed comparison.
View matching uses normalized PDF outlines where available
and rendered geometry otherwise. Unique view labels can break ties between
geometrically eligible pairs. Drawing numbers and detected view types do not
gate matching. The Captioning LLM verifies unique candidates with partial
geometric correspondence before detailed comparison. Invalid model responses receive
one schema-constrained retry. A failed verification is reported separately from
an ambiguous match. Ambiguous matches stay out of
detailed comparison. Onyx inventories requests using the full original page before comparing revisions. It keeps the requested value and
baseline spans separate from the revised evidence. Numeric verdicts compare the request with the cited revised callout.
Onyx rechecks uncertain marks and reports requests that could not be assigned to a view.
Unverified marks get an original-page anchor and a review card. The comparison prompt assigns edits to the requests they address.
Onyx suppresses independent findings that repeat a resolved correction with the same original and revised text spans.
Native text spans and crop-relative evidence boxes map to PDF page coordinates for the review viewer.
Explicit requests with one or two attachments run directly and return coverage
and findings.

Chat PDF attachments open a single-document EmbedPDF Headless viewer inside chat.
Original/revised tabs share numbered findings with the chat cards. Each card opens either revision.
EmbedPDF native annotations render and select confirmed locations. Navigation preserves zoom and waits for layout.
Hover previews and custom issue overlays are removed. Legacy comment/text boxes remain proposed locations.
The owner-scoped locations endpoint uses local pdfplumber native text geometry. Unique isolated dimension
labels matched to evidence can produce located_text anchors; these identify text, not verified geometric features.
Repeated or missing labels remain unmarked. No edge-placeholder annotations are generated.
Manual location corrections use the native rectangle tool and versioned workspace commands.
Corrections use finding-content keys; legacy sequential issue keys are ignored to prevent reassociation.
The explicit Inspect detail action increases zoom without automatic fit-to-area navigation.
PDF export includes native review annotations. It does not change the source PDF.

## Scope

This component owns review records, job execution, inference policy, and engineer decisions.
The file store owns binary storage. Authentication owns the acting user.
The tools framework owns historical chat result persistence and rendering.

## Architecture

- `backend/onyx/server/features/engineering/api.py` authorizes routes with BASIC_ACCESS plus owner checks.
- `backend/onyx/engineering/config.py` gates deployment and builds explicit Ollama inference at a literal internal IP.
- `backend/onyx/db/models.py:EngineeringReview` is the immutable input pair and durable work ledger.
- `backend/onyx/db/engineering_review.py` owns request deduplication, leases, fenced completion, cancellation and optimistic decisions.
- `backend/onyx/engineering/worker.py` polls PostgreSQL, avoiding a broker dependency in Lite and the publish/commit gap.
- `backend/onyx/engineering/processing.py` isolates PDF parsing, reads native annotations and records coverage limits.
- `backend/onyx/engineering/checks.py` checks quoted note replacements. It never measures geometry.
- `web/src/views/EngineeringReviewsPage.tsx` owns explicit file roles, polling, decisions and export.
- The existing comment viewer accepts a file URL resolver. Historical chat callers keep their original file routes.
- `web/src/lib/pdf-review/` owns EmbedPDF loading, durable edit synchronization, native annotations and local text-location requests.
- `backend/onyx/db/drawing_workspace.py` owns idempotent commands, optimistic versions and shared undo/redo.
- `backend/onyx/server/features/engineering/workspace_api.py` authorizes workspace reads, edits and region crops.
- `backend/onyx/tools/tool_implementations/drawing_review/workspace_tool.py` exposes the same commands to agents.

## Contracts and traps

1. `deployment-gate` **The capabilities route controls sidebar availability.** Disabled installations reject review routes.
2. `separate-input-path` **Review inputs bypass chat extraction and model defaults.** The worker requires explicit private inference settings.
3. `single-tenant-worker` **The worker and API share one database, schema and file store.** The worker refuses multi-tenant mode.
4. `lease-fence` **Only the current lease holder may publish.** Cancel invalidates the token. Expired owners cannot renew it.
5. `bounded-recovery` **Claims skip locked rows.** Interrupted runs restart from inputs, up to three attempts.
6. `native-priority` **Native annotations are retained.** With vision configured, every before page is also scanned for graphic/handwritten requests. Failed discovery reports incomplete coverage.
7. `confirmed-order` **Page matching is confirmed identity order.** Reject unequal page counts and oversized packages.
8. `human-decisions` **AI proposals and human decisions stay separate.** Decision versions prevent lost updates.
9. `legacy-contracts` **Old tool names, result types and checkpoint discriminators stay unchanged.** The new workflow adds records outside chat.
10. `private-boundary` **Endpoint checks do not replace network controls.** Unit tests do not qualify model quality or offline operation.

11. `revised-evidence-grounding` **Private verification receives full revision text. Native evidence requires a source match; visual evidence requires a separate target and observation check.** This checks quote provenance, not engineering correctness. Independent local PDF change discovery runs after comment checks. Its coverage and spatial comment links do not change comment verdicts.

12. `context-forwarding` **The private adapter sends an 8,192-token context to Ollama.** A client input budget alone does not change the server context; both limits must agree.

13. `highlight-grounding` **Model-selected revision spans must match their quoted evidence.** Unknown, wrong-page, short or unrelated spans become page-level highlights. This does not qualify exact region association.

14. `identical-inputs` **Identical input bytes are rejected before inference.** The API also compares source hashes before storing a review. This does not detect unchanged regions inside otherwise different PDFs.

15. `pin-location` **Only confirmed normalized anchors produce native feature regions.** Page-level evidence must remain visibly unconfirmed.
16. `shared-edits` **Users and agents share owner checks, idempotency keys and expected versions.** Never add a separate agent mutation path.
17. `chat-viewer` **PDF review stays inside chat.** Document switch requests include the target file, issue and page, with a fresh ID for repeated clicks.
18. `local-pdf-runtime` **The PDFium WASM URL must be absolute inside its blob worker.** Assets are copied from the pinned SDK during frontend preparation.

19. `native-text-location` **pdfplumber returns text locations, not engineering feature identities.** Automatic anchors require unique native callout evidence and remain distinct from manual feature confirmation. Raster-only drawings remain unlocated.
20. `no-edge-fallback` **An unresolved location produces no PDF annotation.** Never replace missing coordinates with a margin note or a fabricated box.

## Known issues

Shared project roles, automated retention/deletion, per-comment checkpoints, extraction caching, model qualification and GPU lifecycle control are not implemented.
Deleting an account removes its review metadata through foreign-key cascades. Binary cleanup still needs the installation's retention process.

## Dependencies

- [[file-store-and-user-files]]: the file store persists and reads the original PDFs.
- [[authorization]]: BASIC_ACCESS gates the acting user; review ownership limits object access.
- [[tools-framework]]: comment tools supply the existing typed result and viewer contract.

## Verification

`backend/tests/unit/onyx/engineering/test_review.py` covers PDF limits, private inference configuration, ownership, recovery, cancellation, decisions and exact text checks.
SQLite ledger tests do not prove PostgreSQL locking. Verify concurrent workers against PostgreSQL before production.
Existing drawing/comment/DXF tests protect chat compatibility. The route manifest covers new API permissions.


### Local review coverage and navigation

The chat reviewer uses the VISION model flow, not the selected chat model. Drawing results record the actual vision model.
Native text-line indexing uses pdfplumber and reports its explicit limits; the first-80-word restriction is removed.
Request extraction receives BEFORE-only stage instructions; missing AFTER is not an extraction ambiguity.
Extraction uncertainty is forwarded to paired verification rather than skipping that request.
The original review render includes native annotation appearances. Close-ups supplement discovery and paired feature verification. Associated scalar requests survive omitted visual value fields.
Grounded scalar mismatches cannot pass the numeric request. Explicit observed values can replace prose evidence only through an exact native span match.
The review budget is five minutes; per-call limits remain bounded.
Unclear judgements receive at most three evidence-changing visual passes. Repeated unclear output stops retries.
The verdict and location remain distinct; supported geometry is not implied by a located text excerpt.
Original locations resolve native comment text independently of the revised evidence.
The chat tool rejects likely reversed PDF roles when only the revised input contains native comments.
An empty comment review raises an actionable tool error, rather than returning a successful zero-finding result.
Each run evaluates the inputs afresh and publishes per-comment progress.

Read-only PDF/page navigation is independent of workspace saving and inference. The SDK handles scroll coordinates,
rotation and crop transforms. A transient page-relative ring lasts two seconds after visibility confirmation.
The ring has no annotation ID, persistence command or export representation. Repeated requests restart its lifetime.


### Chat presentation

Chat uses `web/src/lib/chat-workspace/ChatWorkspace.tsx` with react-resizable-panels for the document/conversation split.
Container width selects a two-pane layout or Conversation/Document controls. Both panels stay mounted during resizing.
Layout widths are a local preference, not engineering document state. A finding focus request opens the document pane on compact layouts.
Review rows have status and search filters. Evidence appears in the title when available.
The request appears in the expanded details. Revision actions stay visible when collapsed.
PDF tools use an explicit annotation mode and action/zoom popovers. EmbedPDF remains responsible for rendering and geometry.
Chat-specific surfaces and borders are scoped; admin and plugin management do not use the chat styling.


### Visual change interpretation

Before-page images accompany after-page verification. Circled dimensions with clearly associated replacement
values can establish a request without a sentence, leader, or strike-through. Ambiguous marks stay in the queue.
Short numeric AFTER evidence requires an exact identified native span. Repeated labels require an explicit matching span ID.
Without a span ID, a short callout must be unique. Other native evidence keeps its six-character default.
Visual-only evidence receives a separate model check of target identity, observation, and verdict; it does not create a native text anchor.
A numbered native bracket can establish a scalar request. A unique revised callout must match both bracket endpoints through its extension lines.
A known unmet requirement stays open when its baseline value is unknown. Failed evidence checks discard the rejected observation and its explanation. The card names the failed check.
Chat comment review checks supervisor requests with the Captioning LLM.
PDF pairs then run an independent local change comparator in `backend/onyx/engineering/drawing_changes.py`.
It excludes native annotations, aligns pages and distinct translated blocks, and combines native numeric text changes with visual regions.
Local candidate discovery uses no model. MechVL validates candidates and proposes further changes. No result cache is used. Results use a separate drawing_changes field; historical extra_issues remain unchanged.
Chat comparison accepts two PDFs. Unique sheet identifiers or sufficiently detailed identical native text can pair reordered sheets. Inserted, removed, and ambiguous sheets have separate coverage. The chat tool also accepts explicit user confirmation of the same sheet order for equal-size packages. Identity inspection stops at 64 pages; rendering and comparison cover the first eight pages of each input. Explicit original-page scope applies to both stages.
Supported linear callouts use extension-line origins for correspondence, independently of text orientation or dimension-line offset.
Ambiguous or unsupported references use conservative local matching. Equal values on different resolved references cannot cancel.
The main list counts confirmed printed-text findings. Confirmed geometry differences appear in a collapsed section. Unchecked or unconfirmed candidates produce no finding or PDF marker. MechVL proposes changes beyond local comparison; discoveries without native support require focused checks of both regions. Rotation, layout shifts, artifacts, and review marks are rejected.
Unmatched text is not evidence of addition/deletion. Final-answer guidance must not invent restoration work or reopen solved comments.
Spatial text correspondence is not verified CAD feature identity. Unmatched callouts remain separate, and visual candidates do not assert metric values.
Spatial associations remain possible links. A verified link requires the same feature and supported requested action. Shorthand receives an independent Before-mark and After-feature check. Verified change evidence appears once on its comment card. Unrelated confirmed changes remain separate.
The viewer uses located_difference anchors for source comparison regions. These do not confirm engineering targets. Grounded Vision Review changes show numbered tags before selection. Selecting a tag uses the existing evidence focus path.
Comment verification and change validation expose separate completion states and completed pages. Skipped pages name coverage failures. Per-page PDF isolation preserves earlier comparisons after later timeouts. Completed validation survives later failures or cancellation. Each chat tool instance claims a PDF pair once by content hash; no result cache is stored. Legacy extra-scan flags do not enable the retired model audit.
