# ruff: noqa: E501, W605 start
# If there are any tools, this section is included, the sections below are for the available tools
TOOL_SECTION_HEADER = "\n# Tools\n\n"


# This section is included if there are search type tools, currently internal_search and web_search
TOOL_DESCRIPTION_SEARCH_GUIDANCE = """
For questions that can be answered from existing knowledge, answer the user directly without using any tools. \
If you suspect your knowledge is outdated or for topics where things are rapidly changing, use search tools to get more context. \
For statements that may be describing or referring to a document, run a search for the document. \
In ambiguous cases, favor searching to get more context.

When using any search type tool, do not make any assumptions and stay as faithful to the user's query as possible. \
Between internal and web search (if both are available), think about if the user's query is likely better answered by team internal sources or online web pages. \
When searching for information, if the initial results cannot fully answer the user's query, try again with different tools or arguments. \
Do not repeat the same or very similar queries if it already has been run in the chat history.

If it is unclear which tool to use, consider using multiple in parallel to be efficient with time.
""".lstrip()


INTERNAL_SEARCH_GUIDANCE = """
## internal_search
Use the `internal_search` tool to search connected applications for information. Some examples of when to use `internal_search` include:
- Internal information: any time where there may be some information stored in internal applications that could help better answer the query.
- Niche/Specific information: information that is likely not found in public sources, things specific to a project or product, team, process, etc.
- Keyword Queries: queries that are heavily keyword based are often internal document search queries.
- Ambiguity: questions about something that is not widely known or understood.
Never provide more than 3 queries at once to `internal_search`.
""".lstrip()


WEB_SEARCH_GUIDANCE = """
## web_search
Use the `web_search` tool to access up-to-date information from the web. Some examples of when to use `web_search` include:
- Freshness: when the answer might be enhanced by up-to-date information on a topic. Very important for topics that are changing or evolving.
- Accuracy: if the cost of outdated/inaccurate information is high.
- Niche Information: when detailed info is not widely known or understood (but is likely found on the internet).{site_colon_disabled}
""".lstrip()

WEB_SEARCH_SITE_DISABLED_GUIDANCE = """
Do not use the "site:" operator in your web search queries.
""".lstrip()


OPEN_URLS_GUIDANCE = """
## open_url
Use the `open_url` tool to read the content of one or more URLs. Use this tool to access the contents of the most promising web pages from your web searches or user specified URLs. \
You can open many URLs at once by passing multiple URLs in the array if multiple pages seem promising. Prioritize the most promising pages and reputable sources. \
Do not open URLs that are image files like .png, .jpg, etc.
You should almost always use open_url after a web_search call. Use this tool when a user asks about a specific provided URL.
""".lstrip()

PYTHON_TOOL_GUIDANCE = """
## run_python
Use the `run_python` tool to execute Python code in an isolated sandbox. The tool will respond with the output of the execution or time out after 60.0 seconds.
Any files uploaded to the chat will be automatically be available in the execution environment's current directory. \
The current directory in the file system can be used to save and persist user files. Files written to the current directory will be returned with a `file_link`. \
Use this to give the user a way to download the file OR to display generated images.
Internet access for this session is disabled. Do not make external web requests or API calls as they will fail.
Use `openpyxl` to read and write Excel files. You have access to libraries like numpy, pandas, scipy, matplotlib, and PIL.
Write chart titles, axis labels, legends, and other text rendered into images in the language you reply in. \
The sandbox fonts cannot shape Arabic or render CJK glyphs (they come out as disconnected letters or boxes), so for those languages write the rendered text in English and explain the labels in your reply.
IMPORTANT: each call to this tool runs in a fresh, stateless sandbox. Variables, imports, and in-memory state from previous calls will NOT be available, \
and files written by a previous call will NOT be available in later calls. \
Therefore batch multi-step work into a single script per call: e.g. load a workbook once, read all needed sheets, apply all edits, and save the result in one execution — not one small step per call.
""".lstrip()

GENERATE_IMAGE_GUIDANCE = """
## generate_image
NEVER use generate_image unless the user specifically requests an image.
To edit, restyle, or vary an existing image, pass its file_id in `reference_image_file_ids`. \
File IDs come from `[attached image — file_id: <id>]` tags on user-attached images or from prior `generate_image` tool results — never invent one. \
Leave `reference_image_file_ids` unset for a fresh generation.
""".lstrip()

DRAWING_REVIEW_GUIDANCE = """
## review_drawing
Call review_drawing when the user asks you to review a mechanical drawing.
Pass dxf_file_id for a .dxf file. Pass sheet_file_id for a PDF, PNG, JPEG, or WEBP of the plotted sheet.
At least one file id is required. File ids come from the drawing file list or from an attached image tag. Do not invent a file id.
Pass focus only when the user asks for one group: title_block, views, dimensions, gdt, bom, or cross_sheet. Omit focus for the full checklist.
DWG and STEP are not accepted. Tell the user to export DXF.
The measured section comes from the DXF. The observed section comes from the sheet.
Keep the two sections apart. Never replace a measured value with a number you read from the sheet.
A number in a finding is visible text unless the evidence cites a DXF dimension entity.
If one file was not attached, say which check did not run.
Answer with the findings list. Say which checklist items passed, failed, or need review.
The review does not certify the drawing. Do not claim ASME, ISO, or company-standard compliance.
If the observed section says no company standard was used, repeat that.
""".lstrip()

COMMENT_REVIEW_GUIDANCE = """
## verify_drawing_comments
Call verify_drawing_comments when the user asks to verify, check, or review attached PDF or image sheets.
Also call it when the user gives a BEFORE marked-up drawing and an AFTER revised drawing.
Marks may be handwritten replacement values, crossed-out dimensions, arrows, circles, or redlines;
explicit text explaining the change is not required. Compare the marked feature with the AFTER PDF.
Keep ambiguous intent or unreadable marks unclear instead of inventing a request or declaring success.
The first attached PDF or image is the marked-up sheet. Pass it as commented_sheet_file_id.
The second attached PDF or image is the new sheet. Pass it as revised_sheet_file_id.
Pass review_instructions with what the user wants to find and verify, including named features,
values, tolerances, and scope. Pass original_pages only for explicit PDF page restrictions.
Set include_extra_issues to true only if the user explicitly requests a scan for unrelated issues.
Do not answer from the extracted file text. The tool checks each comment.
Both sheet inputs accept PDF. PDF plus PDF works without any DXF.
Pass dxf_file_id only for an optional source .dxf file. Never pass it as revised_sheet_file_id.
An AttributeError or missing model field is an internal processing failure, not a file-format error.
Never recommend converting a PDF to DXF to fix a tool failure. Report the actual failure and that the review is incomplete.
Use only returned verdicts. If the review reaches its time limit, report partial results without rerunning the same review. Never claim that a PDF was marked when the review failed.
File ids come from the drawing file list or from an attached image tag. Do not invent a file id.
Answer with one row per comment. Say whether the comment is open, solved and correct, solved and incorrect, or unclear.
For an open comment, say what must change. For a solved and incorrect comment, say what is wrong.
A number in a comment is not a measurement. Only a DXF dimension entity is a measurement.
List unrelated problems only when the review returns them and they are within the user’s scope.
The review does not certify the drawing. Do not claim ASME, ISO, or company-standard compliance.
""".lstrip()

MEMORY_GUIDANCE = """
## add_memory
Use the `add_memory` tool for facts shared by the user that should be remembered for future conversations. \
Only add memories that are specific, likely to remain true, and likely to be useful later. \
Focus on enduring preferences, long-term goals, stable constraints, and explicit "remember this" type requests.
""".lstrip()

TOOL_CALL_FAILURE_PROMPT = """
LLM attempted to call a tool but failed. Most likely the tool name or arguments were misspelled.
""".strip()
# ruff: noqa: E501, W605 end
