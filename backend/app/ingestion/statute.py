"""Parse an Indian central Act (Legislative Department PDF layout) into hierarchical chunks.

Layout handled (verified on the Hindu Marriage Act, 1955 PDF):

* "Arrangement of sections" pages, then the enacted text from a ``body_start`` line.
* Section headings ``13. Divorce.—(1) Any marriage ...`` (amended ones prefixed ``1[``).
* Chapter headings as upper-case lines (``NULLITY OF MARRIAGE AND DIVORCE``).
* Per-page amendment footnotes (``1. Subs. by Act 68 of 1976 ...``) numbered from 1 on each page,
  referenced from the text by markers ``1[...]`` (substituted/inserted) and ``3* * *`` (omitted).
  Markers are removed from the text and each footnote is attached to the section it annotates.
* Sub-sections ``(1)``/``(1A)``, clauses ``(a)``/``(bb)``, roman clauses ``(i)``/``(ia)``,
  provisos and explanations.

Chunking (docs/architecture.md): one parent chunk per section; child "provision" chunks at the
first clause level under a section/sub-section (deeper levels stay inside their clause), so each
child is a self-contained, citable unit. The lead-in text of the container ("... on the ground
that the other party—") goes into the child's contextual header.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from app.ingestion.models import Chunk, CourtLevel, Document, Page, SourceFile
from app.ingestion.text import clean_line, detect_statutes, join_lines, parse_date


@dataclass(frozen=True)
class ActSpec:
    act_id: str  # chunk-id prefix, e.g. "hma1955"
    title: str
    short_title: str
    body_start: re.Pattern[str]  # first line of the enacted text (after the arrangement pages)
    personal_law: str | None = None  # applicability gate, None for secular laws


HMA_1955 = ActSpec(
    act_id="hma1955",
    title="The Hindu Marriage Act, 1955",
    short_title="Hindu Marriage Act, 1955",
    body_start=re.compile(r"^BE it enacted by Parliament"),
    personal_law="hindu",
)

SECTION_HEADING = re.compile(
    r"^(?P<num>\d{1,3}[A-Z]{0,2})\.\s*(?P<title>\[?[A-Z][^—]*?)\s*—\s*(?P<rest>.*)$"
)
CHAPTER_HEADING = re.compile(r"^[A-Z][A-Z ,&'()-]{3,}$")
PAGE_NUMBER = re.compile(r"^\d{1,4}$")
FOOTNOTE = re.compile(r"^(?P<num>\d{1,2})\.\s+(?P<text>.*)$")
MARKER_OPEN = re.compile(r"(?<![\w.])(\d{1,2})\[")
MARKER_OMIT = re.compile(r"(?<![\w.])(\d{1,2})\s?\*(?:\s?\*)+")
BARE_OMIT = re.compile(r"\*(?:\s?\*)+")

SUBSECTION_LABEL = re.compile(r"^\((\d{1,2}[A-Z]{0,2})\)\s*")
CLAUSE_LABEL = re.compile(r"^\(([a-z]{1,4})\)\s*")
PROVISO = re.compile(r"^Provided\b")
EXPLANATION = re.compile(r"^Explanation(?:\s*\d+|\s+[IVX]+)?\s*\.?\s*[—-]")
# "(1) of section 13" wrapped onto a new line is a cross-reference, not a new sub-section.
CROSS_REFERENCE = re.compile(r"^(?:of|and|or|shall|is|are)\b|^[,;)\]]")
BOUNDARY_END = re.compile(r"(?:[;:.,—-]|\bor|\band|namely:?—?)$")
ROMAN = re.compile(r"^(x{0,3})(ix|iv|v?i{0,3})([a-z]?)$")
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10}


class StatuteParseError(ValueError):
    pass


def _roman_value(label: str) -> tuple[int, int] | None:
    m = ROMAN.match(label)
    if not m or not (m[1] or m[2]):
        return None
    base = m[1] + m[2]
    total = 0
    for i, ch in enumerate(base):
        value = _ROMAN_VALUES[ch]
        nxt = _ROMAN_VALUES[base[i + 1]] if i + 1 < len(base) else 0
        total += -value if value < nxt else value
    suffix = ord(m[3]) - 96 if m[3] else 0
    return total, suffix


def _alpha_value(label: str) -> tuple[int, int] | None:
    # (a), (b) ... and inserted doubled letters such as (bb) between (b) and (c).
    if len(set(label)) != 1 or not label.isalpha():
        return None
    return ord(label[0]) - 96, len(label) - 1


def _subsection_value(label: str) -> tuple[int, int]:
    m = re.match(r"(\d+)([A-Z]*)", label)
    if m is None:  # unreachable: SUBSECTION_LABEL only matches digits(+letters)
        raise StatuteParseError(f"bad sub-section label {label!r}")
    return int(m[1]), sum(ord(c) - 64 for c in m[2])


def _is_successor(prev: tuple[int, int], new: tuple[int, int], max_gap: int) -> tuple[bool, bool]:
    """Return (plausible, exact) for `new` following `prev` in a list."""
    if new <= prev:
        return False, False
    if new[0] == prev[0]:  # (i) -> (ia), (b) -> (bb), (1) -> (1A)
        return True, True
    exact = new[0] == prev[0] + 1 and new[1] == 0
    return new[0] - prev[0] <= max_gap and new[1] == 0, exact


@dataclass
class _Node:
    kind: str  # section | subsection | clause | proviso | explanation
    label: str
    parent: "_Node | None" = None
    lines: list[tuple[int, str]] = field(default_factory=list)
    children: list["_Node"] = field(default_factory=list)
    list_type: str | None = None  # "alpha" | "roman" for the clause children of this node
    value: tuple[int, int] = (0, 0)

    def add(self, child: "_Node") -> "_Node":
        child.parent = self
        self.children.append(child)
        return child

    def last_clause(self) -> "_Node | None":
        clauses = [c for c in self.children if c.kind == "clause"]
        return clauses[-1] if clauses else None

    def pages(self) -> Iterator[int]:
        for page, _ in self.lines:
            yield page
        for child in self.children:
            yield from child.pages()

    def own_text(self) -> str:
        return join_lines([text for _, text in self.lines])

    def render(self) -> str:
        parts = [self.own_text(), *(child.render() for child in self.children)]
        return "\n".join(p for p in parts if p)


@dataclass
class _Section:
    number: str
    title: str
    chapter: str | None
    root: _Node
    amendments: list[str] = field(default_factory=list)


class _SectionBuilder:
    """Builds the provision tree of one section, line by line."""

    def __init__(self, root: _Node) -> None:
        self.root = root
        self.current = root
        self.prev_text: str | None = None
        self.after_omission = False  # "* * *" just removed clauses: allow a wider numbering gap

    def note_omission(self) -> None:
        self.after_omission = True

    def feed(self, page: int, text: str, after_label: bool = False) -> None:
        widen, self.after_omission = self.after_omission, False
        if m := SUBSECTION_LABEL.match(text):
            if self._accept_subsection(m[1], text[m.end() :], after_label):
                node = self.root.add(_Node("subsection", m[1], value=_subsection_value(m[1])))
                self._open(node, page, text, m.end())
                return
        elif m := CLAUSE_LABEL.match(text):
            target = self._place_clause(m[1], text[m.end() :], after_label, widen)
            if target is not None:
                parent, list_type, value = target
                parent.list_type = list_type
                self._open(parent.add(_Node("clause", m[1], value=value)), page, text, m.end())
                return
        elif PROVISO.match(text):
            owner = self.current
            while owner.kind == "proviso" and owner.parent is not None:
                owner = owner.parent
            self.current = owner.add(_Node("proviso", "proviso"))
        elif EXPLANATION.match(text):
            self.current = self._explanation_parent(text).add(_Node("explanation", "explanation"))
        self.current.lines.append((page, text))
        self.prev_text = text

    def _open(self, node: _Node, page: int, text: str, label_end: int) -> None:
        """Make `node` current; a second label on the same line ("(f) (i) ...") nests inside it."""
        self.current = node
        rest = text[label_end:]
        if CLAUSE_LABEL.match(rest):
            node.lines.append((page, text[:label_end].strip()))
            self.prev_text = text[:label_end]
            self.feed(page, rest, after_label=True)
        else:
            node.lines.append((page, text))
            self.prev_text = text

    def _boundary(self, after_label: bool) -> bool:
        return after_label or self.prev_text is None or bool(BOUNDARY_END.search(self.prev_text))

    def _accept_subsection(self, label: str, rest: str, after_label: bool) -> bool:
        if CROSS_REFERENCE.match(rest):
            return False
        existing = [c for c in self.root.children if c.kind == "subsection"]
        value = _subsection_value(label)
        if not existing:
            return value == (1, 0) and self._boundary(after_label)
        plausible, exact = _is_successor(existing[-1].value, value, max_gap=1)
        return plausible and (exact or self._boundary(after_label))

    def _place_clause(
        self, label: str, rest: str, after_label: bool, widen: bool = False
    ) -> tuple[_Node, str, tuple[int, int]] | None:
        if CROSS_REFERENCE.match(rest):
            return None
        typed = {"alpha": _alpha_value(label), "roman": _roman_value(label)}
        # Continue the nearest open list (deepest first).
        node: _Node | None = self.current
        while node is not None:
            last = node.last_clause()
            if last is not None and node.list_type is not None:
                value = typed[node.list_type]
                if value is not None:
                    gap = 1 if node.list_type == "alpha" else 2  # omitted clauses leave gaps
                    gap += 3 if widen else 0
                    plausible, exact = _is_successor(last.value, value, gap)
                    if plausible and (exact or self._boundary(after_label)):
                        return node, node.list_type, value
            node = node.parent
        # Otherwise start a new list under the current node.
        if label == "a":
            return self.current, "alpha", (1, 0)
        if label == "i":
            return self.current, "roman", (1, 0)
        return None

    def _explanation_parent(self, text: str) -> _Node:
        # "In this clause" / "This clause applies" explains the current clause; otherwise the
        # explanation belongs to the enclosing sub-section (or the section itself).
        if re.search(r"\b[Tt]his clause\b", text):
            node: _Node | None = self.current
            while node is not None and node.kind != "clause":
                node = node.parent
            if node is not None:
                return node
        node = self.current
        while node is not None and node.kind not in ("subsection", "section"):
            node = node.parent
        return node or self.root


def _strip_footnotes(lines: list[str]) -> tuple[list[str], list[tuple[int, str]]]:
    """Split a page into body lines and its numbered footnotes (which start at "1." per page)."""
    start = None
    for i, line in enumerate(lines):
        if line.startswith("1. ") and not SECTION_HEADING.match(line):
            start = i
    if start is None:
        return lines, []
    footnotes: list[tuple[int, str]] = []
    for line in lines[start:]:
        m = FOOTNOTE.match(line)
        if m and (not footnotes or int(m["num"]) == footnotes[-1][0] + 1):
            footnotes.append((int(m["num"]), m["text"]))
        elif footnotes:
            footnotes[-1] = (footnotes[-1][0], f"{footnotes[-1][1]} {line}")
    return lines[:start], footnotes


class _BracketBalancer:
    """Drop the closing "]" of amendment markers whose opener ``1[`` was removed."""

    def __init__(self) -> None:
        self.depth = 0

    def __call__(self, text: str) -> str:
        out = []
        for ch in text:
            if ch == "[":
                self.depth += 1
            elif ch == "]":
                if self.depth == 0:
                    continue
                self.depth -= 1
            out.append(ch)
        return "".join(out)


def _clean_title(title: str) -> str:
    return title.strip().strip("[]").strip().rstrip(".").strip("[]").strip()


def _section_key(number: str) -> tuple[int, str]:
    m = re.match(r"(\d+)([A-Z]*)", number)
    if m is None:  # unreachable: SECTION_HEADING only matches digits(+letters)
        raise StatuteParseError(f"bad section number {number!r}")
    return int(m[1]), m[2]


def parse_sections(pages: list[Page], spec: ActSpec) -> tuple[list[_Section], list[str]]:
    sections: list[_Section] = []
    builders: dict[str, _SectionBuilder] = {}
    marker_owner: dict[tuple[int, int], _Section] = {}
    page_footnotes: dict[int, list[tuple[int, str]]] = {}
    balance = _BracketBalancer()
    chapter: str | None = None
    started = False

    for page in pages:
        lines = [clean_line(raw) for raw in page.text.splitlines()]
        lines = [line for line in lines if line]
        if lines and PAGE_NUMBER.match(lines[-1]):
            lines = lines[:-1]
        if not started:
            for i, line in enumerate(lines):
                if spec.body_start.match(line):
                    started = True
                    lines = lines[i + 1 :]
                    break
            else:
                continue
        body, footnotes = _strip_footnotes(lines)
        page_footnotes[page.number] = footnotes

        for raw in body:
            markers = [int(n) for n in MARKER_OPEN.findall(raw) + MARKER_OMIT.findall(raw)]
            text = MARKER_OPEN.sub("", raw)
            text = MARKER_OMIT.sub("* * *", text)
            text = BARE_OMIT.sub("* * *", text)
            text = clean_line(balance(text))

            if CHAPTER_HEADING.match(text) and "ACT" not in text:
                chapter = text
                continue
            heading = SECTION_HEADING.match(text)
            if heading and (
                not sections or _section_key(heading["num"]) > _section_key(sections[-1].number)
            ):
                root = _Node("section", heading["num"])
                root.lines.append((page.number, text[: heading.start("rest")].strip()))
                section = _Section(heading["num"], _clean_title(heading["title"]), chapter, root)
                sections.append(section)
                builders[section.number] = _SectionBuilder(root)
                text = heading["rest"].strip()
            if not sections:
                continue
            for number in markers:
                marker_owner[(page.number, number)] = sections[-1]
            if text == "* * *":
                builders[sections[-1].number].note_omission()
            elif text:
                builders[sections[-1].number].feed(page.number, text)

    if not sections:
        raise StatuteParseError(f"no sections found for {spec.act_id}")

    notes: list[str] = []
    for page_number, footnotes in page_footnotes.items():
        for number, note in footnotes:
            owner = marker_owner.get((page_number, number))
            if owner is not None:
                owner.amendments.append(note)
            else:
                notes.append(note)
    return sections, notes


def _node_id(node: _Node, siblings: list[_Node]) -> str:
    if node.kind == "subsection":
        return f"ss{node.label}"
    if node.kind == "clause":
        return f"cl({node.label})"
    same = [s for s in siblings if s.kind == node.kind]
    index = same.index(node) + 1
    if node.kind == "proviso":
        return f"prov{index}"
    return "expl" if index == 1 else f"expl{index}"


def _node_label(node: _Node, siblings: list[_Node]) -> str:
    if node.kind in ("subsection", "clause"):
        return f"({node.label})"
    same = [s for s in siblings if s.kind == node.kind]
    index = same.index(node) + 1
    name = "Proviso" if node.kind == "proviso" else "Explanation"
    return f", {name}" if len(same) == 1 else f", {name} {index}"


def _units(
    container: _Node, path_id: str, path_label: str
) -> Iterator[tuple[_Node, str, str, str]]:
    """Yield (node, chunk-id suffix, label, lead-in) for each retrieval unit under `container`."""
    has_subsections = any(c.kind == "subsection" for c in container.children)
    has_clauses = any(c.kind == "clause" for c in container.children)
    if container.kind == "section" and has_subsections:
        for child in container.children:
            cid = f"{path_id}:{_node_id(child, container.children)}"
            clabel = path_label + _node_label(child, container.children)
            if child.kind == "subsection":
                yield from _units(child, cid, clabel)
            else:
                yield child, cid, clabel, ""
    elif has_clauses:
        lead = f"{path_label} lead-in: {container.own_text()}"
        for child in container.children:
            cid = f"{path_id}:{_node_id(child, container.children)}"
            yield child, cid, path_label + _node_label(child, container.children), lead
    else:
        suffix = ":body" if container.kind == "section" else ""
        yield container, path_id + suffix, path_label, ""


def build_statute(
    pages: list[Page], spec: ActSpec, sources: list[SourceFile]
) -> tuple[Document, list[Chunk]]:
    sections, notes = parse_sections(pages, spec)
    front = "\n".join(p.text for p in pages[:4])
    enacted = re.search(r"\[(\d{1,2}(?:st|nd|rd|th)? \w+, \d{4})\.?\]", front)
    court_level: CourtLevel = "legislation"
    document = Document(
        doc_id=spec.act_id,
        doc_type="statute",
        court_level=court_level,
        title=spec.title,
        personal_law=spec.personal_law,
        enacted_on=parse_date(enacted[1]) if enacted else None,
        notes=notes,
        page_count=len(pages),
        sources=sources,
    )

    chunks: list[Chunk] = []
    order = 0
    for section in sections:
        root = section.root
        section_id = f"{spec.act_id}:s{section.number}"
        heading = (
            f"{spec.short_title} | {section.chapter or ''} | "
            f"Section {section.number}. {section.title}"
        )
        pages_used = list(root.pages())
        section_text = root.render()
        chunks.append(
            Chunk(
                chunk_id=section_id,
                doc_id=document.doc_id,
                kind="section",
                label=f"Section {section.number}",
                order=order,
                text=section_text,
                context=heading,
                page_start=min(pages_used),
                page_end=max(pages_used),
                amendments=section.amendments,
                statutes_cited=detect_statutes(section_text),
            )
        )
        order += 1
        for node, chunk_id, label, lead in _units(root, section_id, f"Section {section.number}"):
            text = node.render()
            if node is root:  # unstructured section: the provision is the body after the heading
                body = join_lines([t for _, t in root.lines[1:]])
                text = "\n".join(p for p in [body, *(c.render() for c in root.children)] if p)
            node_pages = list(node.pages())
            context = f"{heading}\n{lead}" if lead else heading
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    doc_id=document.doc_id,
                    parent_id=section_id,
                    kind="provision",
                    label=label,
                    order=order,
                    text=text,
                    context=context,
                    page_start=min(node_pages),
                    page_end=max(node_pages),
                    statutes_cited=detect_statutes(text),
                )
            )
            order += 1
    return document, chunks
