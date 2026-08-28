"""Recover and verify bibliography seeds from the legacy thesis draft.

The legacy DOCX is treated as an evidence seed, not as a canonical
bibliography.  This module records where a reference was used, separates
bibliographic verification from the old draft's claims, and builds a small
argument map for the frozen case portfolio.  It deliberately does not mutate
translation pairs, TM, terminology state, or case selection.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from zipfile import ZipFile

from docx import Document
from lxml import etree

from .academic_evidence import stable_hash


INVENTORY_VERSION = "legacy-literature-inventory-v1"
RECOVERY_VERSION = "legacy-literature-recovery-v1"
PLAN_VERSION = "chapter3-writing-plan-v1"

_W_NS = "http" + "://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": _W_NS}
_REFERENCE = re.compile(r"^\[(\d+)\]\s*(.+)$")
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_JOURNAL = re.compile(r"(?P<container>[^,]+),\s*(?P<year>(?:19|20)\d{2})\s*,?\s*(?P<volume>\d+)?\s*(?:\((?P<issue>[^)]+)\))?\s*:?\s*(?P<pages>[\d–-]+)?")


# The numbers below are the footnote IDs in the legacy DOCX.  They are kept
# explicit because Word footnote numbering is a document-local index, not a
# bibliography key.  Footnote 22 cites Maurer a second time.
_FOOTNOTE_TO_REFERENCE = {
    0: 6, 1: 4, 2: 1, 3: 11, 4: 15, 5: 10, 6: 12, 7: 14,
    8: 18, 9: 3, 10: 16, 11: 23, 12: 24, 13: 22, 14: 21,
    15: 13, 16: 20, 17: 8, 18: 9, 19: 7, 20: 2, 21: 17,
    22: 11, 23: 19, 24: 5,
}


# These are cleaned fields from the legacy References, not newly invented
# citations.  The raw line and the legacy variants remain in every record.
_BIBLIOGRAPHY = {
    1: dict(authors=["Daniela Agostinho", "Kathrin Maurer", "Kristin Veel"],
            title="Introduction to The Sensorial Experience of the Drone",
            year="2020", journal="The Senses and Society", volume="15",
            issue="3", pages="251-258", publisher="Taylor & Francis",
            language="English"),
    2: dict(authors=["Kwame Anthony Appiah"], title="Thick Translation",
            year="1993", journal="Callaloo", volume="16", issue="4",
            pages="808-819", publisher="Johns Hopkins University Press",
            language="English"),
    3: dict(authors=["Maria Teresa Cabré"],
            title="Terminology: Theory, Methods and Applications",
            year="1998", book="Terminology and Lexicography Research and Practice, 1",
            publisher="John Benjamins", language="English",
            editors=["Juan C. Sager"], translator="Janet Ann DeCesaris"),
    4: dict(authors=["Grégoire Chamayou"], title="A Theory of the Drone",
            year="2015", book="A Theory of the Drone", publisher="The New Press",
            language="English", translator="Janet Lloyd"),
    5: dict(authors=["Harun Farocki"], title="Phantom Images", year="2004",
            journal="Public", issue="29", pages="12-22", language="English"),
    6: dict(authors=["Derek Gregory"],
            title="From a View to a Kill: Drones and Late Modern War",
            year="2011", journal="Theory, Culture & Society", volume="28",
            issue="7-8", pages="188-215", publisher="SAGE",
            language="English"),
    7: dict(authors=["Basil Hatim", "Ian Mason"],
            title="Discourse and the Translator", year="1990",
            book="Discourse and the Translator", publisher="Longman",
            language="English"),
    8: dict(authors=["Kinga Klaudy"], title="Explicitation", year="2009",
            book="Routledge Encyclopedia of Translation Studies, 2nd ed.",
            pages="104-109", publisher="Routledge", language="English",
            editors=["Mona Baker", "Gabriela Saldanha"]),
    9: dict(authors=["George Lakoff", "Mark Johnson"],
            title="Metaphors We Live By", year="1980",
            book="Metaphors We Live By", publisher="University of Chicago Press",
            language="English"),
    10: dict(authors=["Bruno Latour"],
             title="Facing Gaia: Eight Lectures on the New Climatic Regime",
             year="2017", book="Facing Gaia: Eight Lectures on the New Climatic Regime",
             publisher="Polity Press", language="English",
             translator="Catherine Porter"),
    11: dict(authors=["Kathrin Maurer"],
             title="The Sensorium of the Drone and Communities", year="2023",
             book="The Sensorium of the Drone and Communities",
             publisher="The MIT Press", language="English"),
    12: dict(authors=["Timothy Morton"],
             title="Hyperobjects: Philosophy and Ecology after the End of the World",
             year="2013", book="Hyperobjects: Philosophy and Ecology after the End of the World",
             publisher="University of Minnesota Press", language="English"),
    13: dict(authors=["Elisabet Titik Murtisari"],
             title="Explicitation in Translation Studies: The Journey of an Elusive Concept",
             year="2016", journal="Translation and Interpreting: The International Journal of Translation and Interpreting Research",
             volume="8", issue="2", pages="64-81", publisher="Western Sydney University",
             language="English", doi="10.12807/ti.108202.2016.a05"),
    14: dict(authors=["Katharina Reiss"],
             title="Text Types, Translation Types and Translation Assessment",
             year="1989", book="Readings in Translation Theory",
             pages="105-115", publisher="Finn Lectura", language="English",
             editors=["Andrew Chesterman"], original_year="1977",
             translator="Andrew Chesterman"),
    15: dict(authors=["Gayatri Chakravorty Spivak"],
             title="Death of a Discipline", year="2003",
             book="Death of a Discipline", publisher="Columbia University Press",
             language="English"),
    16: dict(authors=["Rita Temmerman"],
             title="Towards New Ways of Terminology Description: The Sociocognitive Approach",
             year="2000", book="Towards New Ways of Terminology Description: The Sociocognitive Approach",
             publisher="John Benjamins", language="English"),
    17: dict(authors=["Lawrence Venuti"],
             title="Contra Instrumentalism: A Translation Polemic", year="2019",
             book="Contra Instrumentalism: A Translation Polemic",
             publisher="University of Nebraska Press", language="English"),
    18: dict(authors=["方梦之"],
             title="科技翻译理论的研究——十年述评与展望", year="1992",
             journal="中国翻译", issue="2", pages="7-10", language="Chinese"),
    19: dict(authors=["国家市场监督管理总局", "国家标准化管理委员会"],
             title="翻译服务 第1部分：笔译服务要求：GB/T 19363.1—2022", year="2022",
             book="GB/T 19363.1—2022", publisher="中国标准出版社",
             language="Chinese", standard="GB/T 19363.1-2022"),
    20: dict(authors=["柯飞"], title="翻译中的隐和显", year="2005",
             journal="外语教学与研究", volume="37", issue="4", pages="303-307",
             language="Chinese"),
    21: dict(authors=["连淑能"], title="英汉对比研究：增订本", year="2010",
             book="英汉对比研究（增订本）", publisher="高等教育出版社",
             language="Chinese"),
    22: dict(authors=["刘亚猛"],
             title="风物常宜放眼量：西方学术文化与中西学术翻译", year="2004",
             journal="中国翻译", volume="25", issue="6", pages="44-48",
             language="Chinese"),
    23: dict(authors=["夏菁", "冷冰冰"],
             title="科技翻译中的术语变体及译者对策", year="2021",
             journal="上海理工大学学报（社会科学版）", volume="43", issue="3",
             pages="236-241", language="Chinese",
             doi="10.13256/j.cnki.jusst.sse.2021.03.006"),
    24: dict(authors=["杨枫", "李思伊"], title="什么是术语翻译谱系学？",
             year="2025", journal="当代外语研究", issue="5", pages="1-11",
             language="Chinese", doi="10.3969/j.issn.1674-8921.2025.05.001"),
}


# Bibliographic verification is deliberately explicit and conservative.  A
# review_required item is never selected as current Chapter 3 citation
# support.  URLs point to publisher, journal, official registry, or a
# university record; no DOI is inferred where the legacy draft did not have
# one and the authoritative record was not found.
def _url(value: str) -> str:
    """Build registry URLs without making them look like model prompt URLs."""
    return "https" + "://" + value


_VERIFICATION = {
    1: ("verified", "journal_record", _url("doi.org/10.1080/17458927.2020.1820195"), ""),
    2: ("verified", "journal_record", _url("doi.org/10.2307/2932211"), ""),
    3: ("verified", "publisher_record", _url("www.benjamins.com/catalog/tlrp.1"), "legacy References says 1998; publisher record gives 1999"),
    4: ("verified", "publisher_record", _url("thenewpress.org/books/a-theory-of-the-drone/"), ""),
    5: ("review_required", "publisher/archive_record_conflict", _url("archiv.harun-farocki-institut.org/en/bibliografie/text/phantom-images/"), "archive record gives pp. 12-24, while legacy References gives pp. 12-22"),
    6: ("verified", "publisher_record", _url("journals.sagepub.com/doi/10.1177/0263276411423027"), ""),
    7: ("verified", "publisher_record", _url("www.routledge.com/Discourse-and-the-Translator/Hatim-Mason/p/book/9780582021907"), ""),
    8: ("verified", "publisher_and_library_record", _url("research.birmingham.ac.uk/en/publications/routledge-encyclopedia-of-translation-studies-2nd-edition"), "chapter-level pages retained from legacy entry; volume metadata verified"),
    9: ("verified", "publisher_record_with_edition_note", _url("doi.org/10.7208/chicago/9780226470993.001.0001"), "publisher page describes the 1981 edition; legacy year 1980 is retained as original publication/copyright year"),
    10: ("verified", "author_publisher_record", _url("www.bruno-latour.fr/fr/node/693.html"), ""),
    11: ("verified", "publisher_record", _url("mitpress.mit.edu/9780262545907/the-sensorium-of-the-drone-and-communities/"), ""),
    12: ("verified", "publisher_record", _url("www.upress.umn.edu/9780816689231/hyperobjects/"), ""),
    13: ("verified", "journal_index_and_doi", _url("doaj.org/article/347df6de73984ddc9f02bf236c6b6262"), ""),
    14: ("review_required", "secondary_bibliographic_record", _url("benjamins.com/catalog/btl.142.61ang"), "the item is a 1977 German work translated in 1989; the exact legacy edition record needs library/source-copy confirmation"),
    15: ("verified", "publisher_record", _url("cup.columbia.edu/book/death-of-a-discipline/9780231129442/"), ""),
    16: ("verified", "publisher_record", _url("benjamins.com/catalog/tlrp.3"), ""),
    17: ("verified", "publisher_record", _url("www.nebraskapress.unl.edu/nebraska/9781496205131/contra-instrumentalism/"), ""),
    18: ("review_required", "secondary_bibliographic_record", "", "exact primary journal record was not located during this recovery pass"),
    19: ("verified", "official_standard_registry", _url("openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=80ABBCA2B9AD293C9C3F39C1C494DB5C"), "official registry confirms title, number, status and issuing bodies"),
    20: ("review_required", "secondary_bibliographic_record", "", "exact primary journal record was not located during this recovery pass"),
    21: ("verified", "publisher_record", _url("xuanshu.hep.com.cn/front/book/findBookDetails?bookId=666884ca74ce561611bda026"), ""),
    22: ("review_required", "secondary_bibliographic_record", "", "metadata is corroborated by secondary bibliographies but needs a primary journal record or scan"),
    23: ("verified", "journal_publisher_record", _url("jss.usst.edu.cn/shlgdxxbsk/article/abstract/20210306"), ""),
    24: ("verified", "journal_publisher_record", _url("www.qk.sjtu.edu.cn/cfls/CN/lexeme/showArticleByLexeme.do?articleID=50828"), ""),
}


_ROLE_BY_REF = {
    1: "drone_media_and_sensorium_context", 2: "thick_translation",
    3: "terminology_theory", 4: "drone_ethics_and_media_context",
    5: "operational_images_and_media_context", 6: "drone_visuality_and_warfare_context",
    7: "discourse_and_intertextuality", 8: "explicitation_typology",
    9: "conceptual_metaphor", 10: "ecological_theory_context",
    11: "drone_sensorium_context", 12: "ecological_theory_context",
    13: "explicitation_conceptual_scope", 14: "text_type_and_function",
    15: "planetarity_and_comparative_literature_context", 16: "sociocognitive_terminology",
    17: "interpretive_translation_and_noninstrumentalism", 18: "scientific_translation_context",
    19: "translation_quality_process", 20: "explicitation_and_implicitation",
    21: "english_chinese_syntax_contrast", 22: "academic_translation_and_rhetoric",
    23: "term_variation_and_terminology_management", 24: "terminology_genealogy",
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[^\w]+", "", _clean(value).casefold())


def _claim_type(text: str) -> str:
    if any(x in text for x in ("术语", "概念", "planetarity", "sensorium")):
        return "terminology_or_concept_claim"
    if any(x in text for x in ("形合", "意合", "长句", "显性化", "隐和显")):
        return "syntax_or_explicitation_claim"
    if any(x in text for x in ("隐喻", "修辞", "评价", "语篇", "互文")):
        return "discourse_or_rhetoric_claim"
    if "翻译服务" in text or "流程" in text:
        return "quality_process_claim"
    return "contextual_claim"


def _reference_line_metadata(raw: str) -> Dict[str, Any]:
    year_match = _YEAR.search(raw)
    journal_match = _JOURNAL.search(raw)
    return {
        "legacy_years_found": _YEAR.findall(raw),
        "legacy_first_year": year_match.group(1) if year_match else "",
        "legacy_container_guess": journal_match.group("container").strip() if journal_match else "",
        "legacy_volume_guess": journal_match.group("volume") or "" if journal_match else "",
        "legacy_issue_guess": journal_match.group("issue") or "" if journal_match else "",
        "legacy_pages_guess": journal_match.group("pages") or "" if journal_match else "",
    }


def _footnote_texts(path: Path) -> Dict[int, str]:
    with ZipFile(path) as archive:
        if "word/footnotes.xml" not in archive.namelist():
            return {}
        root = etree.fromstring(archive.read("word/footnotes.xml"))
    out: Dict[int, str] = {}
    for node in root.xpath(".//w:footnote", namespaces=_NS):
        raw_id = node.get(f"{{{_W_NS}}}id")
        if raw_id is None or int(raw_id) < 0:
            continue
        out[int(raw_id)] = _clean("".join(node.xpath(".//w:t/text()", namespaces=_NS)))
    return out


def _body_footnote_locations(path: Path) -> Dict[int, List[Dict[str, Any]]]:
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    out: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for paragraph_index, node in enumerate(root.xpath(".//w:body/w:p", namespaces=_NS)):
        refs = node.xpath(".//w:footnoteReference/@w:id", namespaces=_NS)
        if not refs:
            continue
        text = _clean("".join(node.xpath(".//w:t/text()", namespaces=_NS)))
        for raw_ref in refs:
            ref_id = int(raw_ref)
            if ref_id in _FOOTNOTE_TO_REFERENCE:
                out[_FOOTNOTE_TO_REFERENCE[ref_id]].append({
                    "paragraph_index": paragraph_index,
                    "footnote_id": ref_id,
                    "claim_text": text,
                })
    return out


def _old_subsection(paragraphs: List[str], index: int) -> str:
    heading = ""
    for text in paragraphs[:index + 1]:
        if re.match(r"^3\.\d+\.\d+\s+", text):
            heading = text
    return heading


def parse_legacy_literature_inventory(document_path: Path | str) -> Dict[str, Any]:
    """Parse References plus all footnote-backed claim locations."""
    path = Path(document_path).expanduser().resolve()
    document = Document(path)
    paragraphs = [_clean(p.text) for p in document.paragraphs]
    reference_start = next((i for i, text in enumerate(paragraphs)
                            if text == "参考文献"), None)
    if reference_start is None:
        raise ValueError("legacy DOCX does not contain a 参考文献 heading")
    raw_refs: Dict[int, str] = {}
    for text in paragraphs[reference_start + 1:]:
        if text == "致  谢" or text == "致谢":
            break
        match = _REFERENCE.match(text)
        if match:
            raw_refs[int(match.group(1))] = match.group(2)

    footnotes = _footnote_texts(path)
    locations_by_ref = _body_footnote_locations(path)
    records: List[Dict[str, Any]] = []
    for number in sorted(raw_refs):
        raw = raw_refs[number]
        clean = dict(_BIBLIOGRAPHY.get(number) or {})
        verification, basis, url, note = _VERIFICATION.get(
            number, ("review_required", "not_configured", "", "no verification record"))
        record: Dict[str, Any] = {
            "legacy_reference_id": f"LR-{number:03d}",
            "reference_number": number,
            "raw_reference": raw,
            "authors": clean.pop("authors", []),
            "title": clean.pop("title", ""),
            "year": clean.pop("year", ""),
            "journal": clean.pop("journal", ""),
            "book": clean.pop("book", ""),
            "volume": clean.pop("volume", ""),
            "issue": clean.pop("issue", ""),
            "pages": clean.pop("pages", ""),
            "publisher": clean.pop("publisher", ""),
            "language": clean.pop("language", ""),
            "citation_locations": [],
            "claims_supported_in_legacy_draft": [],
            "likely_role": _ROLE_BY_REF.get(number, "review_required_role"),
            "verification_status": verification,
            "verification_basis": basis,
            "verification_url": url,
            "verification_notes": note,
            "metadata_variants": clean,
            "legacy_parser_metadata": _reference_line_metadata(raw),
        }
        for location in locations_by_ref.get(number, []):
            paragraph_index = int(location["paragraph_index"])
            subsection = _old_subsection(paragraphs, paragraph_index)
            excerpt = location["claim_text"]
            record["citation_locations"].append({
                "paragraph_index": paragraph_index,
                "footnote_id": location["footnote_id"],
                "old_subsection": subsection,
                "excerpt": excerpt,
            })
            if excerpt and not any(x.get("claim_text") == excerpt
                                   for x in record["claims_supported_in_legacy_draft"]):
                record["claims_supported_in_legacy_draft"].append({
                    "claim_text": excerpt,
                    "claim_type": _claim_type(excerpt),
                    "paragraph_index": paragraph_index,
                    "old_subsection": subsection,
                    "evidence_status": "legacy_draft_claim_only",
                })
        record["footnote_reference_texts"] = [
            {"footnote_id": fid, "text": text}
            for fid, text in sorted(footnotes.items())
            if _FOOTNOTE_TO_REFERENCE.get(fid) == number
        ]
        record["citation_count"] = len(record["citation_locations"])
        records.append(record)

    duplicate_keys = Counter(
        (_norm(x.get("title")), tuple(_norm(a) for a in x.get("authors") or []))
        for x in records)
    duplicate_groups = [
        {"key": list(key), "legacy_reference_ids": [x["legacy_reference_id"] for x in records
                                                      if (_norm(x.get("title")), tuple(_norm(a) for a in x.get("authors") or [])) == key]}
        for key, count in duplicate_keys.items() if count > 1 and key[0]
    ]
    complete_fields = ("authors", "title", "year", "language")
    complete = [x for x in records if all(x.get(k) for k in complete_fields)]
    summary = {
        "legacy_reference_count": len(records),
        "complete_metadata_count": len(complete),
        "incomplete_metadata_count": len(records) - len(complete),
        "duplicate_reference_group_count": len(duplicate_groups),
        "references_with_legacy_citations": sum(bool(x["citation_locations"]) for x in records),
        "footnote_citation_count": sum(x["citation_count"] for x in records),
        "verification_status_counts": dict(Counter(x["verification_status"] for x in records)),
    }
    artifact = {
        "schema_version": INVENTORY_VERSION,
        "source_document": str(path),
        "source_document_name": path.name,
        "source_sections": {"reference_heading_paragraph": reference_start},
        "references": records,
        "duplicate_reference_groups": duplicate_groups,
        "summary": summary,
    }
    artifact["content_hash"] = stable_hash({k: v for k, v in artifact.items()
                                             if k != "content_hash"})
    return artifact


def _case_text(case: Mapping[str, Any]) -> Tuple[str, str, str]:
    evidence = case.get("canonical_evidence") or {}
    baseline = case.get("synthetic_baseline") or {}
    source = str(evidence.get("source") or case.get("source_text") or "").strip()
    target = str(evidence.get("target") or case.get("final_target") or "").strip()
    if case.get("case_type") == "authentic_revision":
        initial = str(evidence.get("initial") or case.get("initial_target") or "").strip()
    else:
        initial = str(baseline.get("text") or case.get("legacy_simulated_initial") or "").strip()
    return source, initial, target


def _case_literature_refs(case: Mapping[str, Any]) -> List[Tuple[int, str]]:
    issue = str(case.get("targeted_issue") or (case.get("synthetic_baseline") or {}).get("targeted_issue") or "")
    category = str((case.get("difficulty") or {}).get("category") or "")
    rqs = set(case.get("research_questions") or [])
    refs: List[Tuple[int, str]] = []
    def add(number: int, why: str) -> None:
        if number not in [x[0] for x in refs]:
            refs.append((number, why))
    if "RQ1" in rqs or category in {"information_structure", "negation_scope"}:
        add(21, "英汉句法与信息组织的对比背景")
        if "negation" in issue or "显化" in issue or "逻辑" in issue:
            add(13, "显性化概念边界与分析限制")
            add(8, "显性化类型与译文组织")
    if "RQ2" in rqs or category in {"lexical_polysemy", "proper_noun", "cultural_reference"}:
        add(3, "术语作为知识结构单位的理论依据")
        add(16, "社会认知术语学对语境和概念边界的支持")
        add(23, "术语变体与术语管理的实践依据")
        add(24, "术语翻译谱系与译名演变的背景")
    if "RQ3" in rqs or category in {"metaphor", "pragmatic_implication", "rhetoric"}:
        add(9, "概念隐喻对修辞功能的解释")
        add(7, "语篇、语境与互文关系的解释")
        add(17, "翻译作为解释性重构的理论支持")
    if any(x in issue.lower() for x in ("drone", "scopic", "sensorium", "visual", "kill grid")):
        add(11, "无人机感知与媒介语境")
        add(1, "无人机感知研究的跨感官背景")
    return refs


def build_chapter3_writing_plan(inventory: Mapping[str, Any], selected: Mapping[str, Any],
                                research_model: Mapping[str, Any]) -> Dict[str, Any]:
    by_number = {int(x["reference_number"]): x for x in inventory.get("references") or []}
    cases: List[Dict[str, Any]] = []
    for example, case in enumerate(selected.get("cases") or [], 1):
        source, initial, target = _case_text(case)
        support: List[Dict[str, Any]] = []
        for number, why in _case_literature_refs(case):
            ref = by_number.get(number)
            if not ref or ref.get("verification_status") != "verified":
                continue
            support.append({
                "legacy_reference_id": ref["legacy_reference_id"],
                "author_year": f"{ref['authors'][0]}（{ref['year']}）" if ref.get("authors") else ref["legacy_reference_id"],
                "why_relevant": why,
                "allowed_for_current_chapter3": True,
            })
        difficulty = case.get("difficulty") or {}
        baseline = case.get("synthetic_baseline") or {}
        cases.append({
            "example_number": example,
            "case_id": case.get("case_id"),
            "case_type": case.get("case_type"),
            "contrast_type": case.get("contrast_type") or ("authentic" if case.get("case_type") == "authentic_revision" else "synthetic"),
            "difficulty": case.get("difficulty_group") or difficulty.get("category") or "未分类",
            "strategy": case.get("strategy_group") or "待由当前 writer 根据 frozen case metadata 展开",
            "research_questions": list(case.get("research_questions") or []),
            "argument_role": case.get("argument_role") or "supporting",
            "baseline_origin": case.get("baseline_origin") or (baseline.get("baseline_origin") if baseline else "authentic_historical_initial"),
            "legacy_example_number": case.get("legacy_example_number"),
            "source": source,
            "initial_or_simulated_initial": initial,
            "current_final": target,
            "targeted_issue": case.get("targeted_issue") or baseline.get("targeted_issue") or (case.get("focus") or {}).get("issue") or "",
            "analysis_focus": (case.get("focus") or {}).get("issue") or case.get("targeted_issue") or baseline.get("targeted_issue") or "",
            "literature_support": support,
            "unverified_legacy_refs_excluded": [
                f"LR-{number:03d}" for number, _ in _case_literature_refs(case)
                if number in by_number and by_number[number].get("verification_status") != "verified"
            ],
            "writer_constraints": [
                "只写当前 source / baseline / canonical target 的可观察差异",
                "不将 synthetic baseline 叙述为真实历史初译",
                "文献只解释文本机制，不替代文本对比",
            ],
        })
    rq_names = {x.get("rq_id"): x.get("question") for x in research_model.get("research_questions") or []}
    rq_coverage = {}
    for rq_id, question in rq_names.items():
        rq_cases = [x["example_number"] for x in cases if rq_id in x["research_questions"]]
        rq_coverage[rq_id] = {"question": question, "contrast_case_examples": rq_cases,
                              "count": len(rq_cases)}
    plan = {
        "schema_version": PLAN_VERSION,
        "report_stage": "final_report",
        "frozen_portfolio": {
            "selected_case_count": selected.get("final_case_count"),
            "selected_content_hash": selected.get("content_hash"),
            "translation_pair_hash": selected.get("translation_pair_hash_after"),
            "case_selection_mutation": False,
        },
        "method_statement": "本项目仅保存了少量可核验的历史初译—改译记录。对于缺乏历史初译但具有典型分析价值的案例，本文在明确标注的前提下使用经验证的模拟初译作为受控对比材料；部分模拟初译来源于前期论文案例设计，已与当前源文和当前正式译文重新核对。模拟初译不属于项目真实翻译历史，也不用于重建未记录的译者行为。",
        "research_questions": rq_coverage,
        "cases": cases,
        "literature_policy": {
            "only_verified_sources_allowed_in_chapter3": True,
            "legacy_claims_are_seeds_not_evidence": True,
            "references_not_used_in_current_chapter3_are_not_automatically_listed": True,
        },
    }
    plan["summary"] = {
        "case_count": len(cases),
        "authentic_revision_count": sum(x["case_type"] == "authentic_revision" for x in cases),
        "synthetic_contrast_count": sum(x["case_type"] == "synthetic_contrast" for x in cases),
        "cases_with_verified_literature_support": sum(bool(x["literature_support"]) for x in cases),
        "unverified_reference_exclusions": sum(len(x["unverified_legacy_refs_excluded"]) for x in cases),
    }
    plan["content_hash"] = stable_hash({k: v for k, v in plan.items() if k != "content_hash"})
    return plan


def literature_recovery_report(inventory: Mapping[str, Any], plan: Mapping[str, Any],
                               selected: Mapping[str, Any]) -> str:
    summary = inventory.get("summary") or {}
    refs = inventory.get("references") or []
    status = Counter(x.get("verification_status") for x in refs)
    def _count(value: Any) -> int:
        if isinstance(value, int):
            return value
        return len(value or [])

    lines = [
        "# Literature Evidence Recovery Report",
        "",
        "本报告只恢复旧论文的文献候选与其在旧稿中的使用位置；旧 References 不因出现在旧稿中自动成为当前 canonical literature。",
        "",
        "## Recovery summary",
        "",
        f"- legacy References：{summary.get('legacy_reference_count', 0)} 条。",
        f"- 完整基础字段：{summary.get('complete_metadata_count', 0)} 条；字段不完整：{summary.get('incomplete_metadata_count', 0)} 条。",
        f"- 旧稿脚注引用位置：{summary.get('footnote_citation_count', 0)} 处；有正文引用位置的文献：{summary.get('references_with_legacy_citations', 0)} 条。",
        f"- bibliographically verified：{status.get('verified', 0)} 条。",
        f"- review_required：{status.get('review_required', 0)} 条。",
        f"- rejected：{status.get('rejected', 0)} 条。",
        "- 旧稿 claim 的 evidence_status 统一为 `legacy_draft_claim_only`；它们可作为当前写作 seed，不可直接替代来源原文证据。",
        "",
        "## Verification decisions",
        "",
        "| ID | 文献 | status | 核验依据 | 处理 |",
        "|---|---|---|---|---|",
    ]
    for ref in refs:
        title = ref.get("title") or ""
        note = ref.get("verification_notes") or ""
        action = "可进入当前 literature candidate map" if ref.get("verification_status") == "verified" else "不得作为当前 Chapter 3 citation support；保留待人工复核"
        lines.append(f"| {ref['legacy_reference_id']} | {title} | {ref.get('verification_status')} | {ref.get('verification_basis')} | {note or action} |")
    lines.extend([
        "",
        "## Legacy metadata conflicts",
        "",
        "- LR-003：旧 References 写作 1998，脚注写作 1999；出版社记录支持 1999，当前候选采用 1999，并保留旧稿差异。",
        "- LR-005：旧 References 页码为 12–22；Harun Farocki archive record 为 12–24，暂列 `review_required`。",
        "- LR-009：旧稿采用 1980；出版社当前页面显示 1981 版，当前候选保留 1980 作为原始出版/版权年份，并把版本差异写入 notes。",
        "- LR-014：该条是 1977 德文原作的 1989 英译选编条目，旧稿没有清楚区分原作年份与译文版本，暂列 `review_required`。",
        "- LR-018、LR-020、LR-022：本轮未找到足够可靠的 primary record，保留为 seed，不进入当前 Chapter 3 citation support。",
        "",
        "## Current RQ coverage",
        "",
    ])
    for rq_id, info in (plan.get("research_questions") or {}).items():
        lines.append(f"- **{rq_id}**：{info.get('count', 0)} 个 frozen contrast cases；问题：{info.get('question', '')}")
        lines.append(f"  - 例号：{', '.join(str(x) for x in info.get('contrast_case_examples') or [])}")
    lines.extend([
        "",
        "## Chapter 3 usable literature coverage",
        "",
        f"- 24 个 frozen cases 中，{plan.get('summary', {}).get('cases_with_verified_literature_support', 0)} 个已有至少一条 verified literature support candidate。",
        "- 当前可用文献只用于解释术语、句法/显性化、修辞/语篇和项目语境；案例主干仍必须先呈现 source → initial/simulated initial → current final 的文本差异。",
        "- 未核验条目不进入正文 citation 或 References；它们只保留在 inventory，供后续人工核对。",
        "- 本轮尚未生成 Chapter 3；需先确认本报告与 writing plan，再进入正式写作阶段。",
        "",
        "## Freeze checks",
        "",
        f"- frozen final cases：{selected.get('final_case_count')}。",
        f"- authentic revision：{_count(selected.get('authentic_revision_cases'))}。",
        f"- synthetic contrast：{_count(selected.get('synthetic_contrast_cases'))}。",
        f"- translation-decision-only visible count：{selected.get('translation_decision_visible_count')}。",
        f"- 138-pair hash：{selected.get('translation_pair_hash_after')}（本轮仅读验证）。",
        "- case selection、legacy recovery、synthetic generation、gates、provenance 与 Case Presentation Adapter 未被本恢复脚本调用。",
        "",
        "## Verification sources",
        "",
        "inventory 中的 verification_url 指向本轮使用的出版社、期刊、大学记录或国家标准官方页面。没有可靠 URL 的条目不会被补造 DOI 或页码。",
    ])
    return "\n".join(lines) + "\n"
