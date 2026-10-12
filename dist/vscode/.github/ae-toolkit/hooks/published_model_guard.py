#!/usr/bin/env python3
"""Pause edits that redefine a published model until the requester replies.

Instructions alone did not hold this boundary on smaller models: they described
a column as public and contract-enforced in their own words, then changed what
it means. This gate makes the stop mechanical. A model is published when its
YAML or folder config grants public access or enforces a contract, or when an
exposure, semantic model, metric, or LookML view reads it.

The gate also runs when the requester sends a message. It counts messages and
notes whether the latest one asks to rename, remove, retype, or redefine
something, or to change how it is counted or calculated. Under such a request,
every attempt to change a published model's SQL or YAML, by any edit tool or
shell command, is denied with the consumers it found until the requester sends
another message. Requests to refactor, make incremental, document, or test are
not paused: they change how a model is built, not what it means.

The message text is never stored. Where the message hook does not run, the gate
pauses the first SQL edit and reads the transcript for a reply; when it cannot
tell, or cannot finish reading the project in its time budget, it allows the
action and says so rather than blocking edits it cannot judge.
Set `guard_published_models: false` in `.ae/project.yml` to turn it off.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Hooks are invoked by absolute path from an arbitrary working directory, so the
# sibling module is not importable without this.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import host_contract  # noqa: E402

SCAN_BUDGET_SECONDS = 3.0
STATE_DIR = Path(tempfile.gettempdir()) / "ae-toolkit-guard"
SKIPPED_DIRS = frozenset(
    {".git", "target", "dbt_packages", "logs", "node_modules", "__pycache__", ".venv", "venv", ".cursor"}
)
EDIT_TOOLS = frozenset({"write", "delete", "strreplace", "edit", "multiedit", "search_replace"})
SHELL_TOOL_NAMES = frozenset({"shell", *host_contract.SHELL_TOOLS})
PATH_KEYS = re.compile(r"path|file|target", re.IGNORECASE)
MAX_INPUT_DEPTH = 4

# Programs whose arguments are read, not written. A segment run by anything else
# has its file arguments treated as write targets.
READ_ONLY_PROGRAMS = frozenset(
    {
        "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "wc", "diff",
        "ls", "stat", "file", "nl", "sort", "uniq", "cut", "bat", "echo", "printf", "awk",
        "sed", "perl", "dbt", "dbtf", "python3", "python", "jq", "yq", "find", "tree",
    }
)
READ_ONLY_GIT = frozenset({"diff", "log", "show", "status", "blame", "grep", "ls-files"})
# Programs from the read-only set that write in place when given these flags.
IN_PLACE = re.compile(r"(?:^|\s)-(?:i\S*|pi\S*|-in-place\S*)(?=\s|$)")
REDIRECT_TARGET = re.compile(r"(?:\d?>>?|&>>?)\s*([^\s;&|<>]+)")
SEGMENT_SPLIT = re.compile(r"\|\||&&|[;&|\n]")
TOKEN_SPLIT = re.compile(r"[\s;&|<>()'\",=`]+")
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

MODELS_KEY = re.compile(r"^(\s*)models\s*:\s*(?:#.*)?$")
ENTRY_NAME = re.compile(r"^(\s*)-\s+name\s*:\s*['\"]?([A-Za-z0-9_]+)")
PUBLIC_ACCESS = re.compile(r"^\s*\+?access\s*:\s*['\"]?public\b", re.IGNORECASE | re.MULTILINE)
CONTRACT_KEY = re.compile(r"^\s*\+?contract\s*:", re.IGNORECASE | re.MULTILINE)
ENFORCED_TRUE = re.compile(r"\benforced\s*:\s*true\b", re.IGNORECASE)
REF_CALL = re.compile(r"ref\(\s*['\"]([A-Za-z0-9_]+)['\"]")
NOT_A_CONSUMER = re.compile(r"^\s*-?\s*(?:to|input)\s*:\s*ref\(", re.IGNORECASE)
MODEL_PATHS = re.compile(r"^\s*model-paths\s*:\s*\[([^\]]*)\]", re.MULTILINE)
GUARD_OFF = re.compile(r"^\s*guard_published_models\s*:\s*(?:false|off|no)\b", re.IGNORECASE | re.MULTILINE)
VERSION_SUFFIX = re.compile(r"_v\d+$")

PROMPT_EVENTS = frozenset({"beforesubmitprompt", "userpromptsubmit"})
# A request may edit a published model without a pause only when it plainly asks
# for work that keeps what consumers receive: a build change, documentation,
# tests, or an added column. Meaning changes are phrased too many ways to list,
# so a request that is neither is treated as one. Each clause is judged on its
# own, so "refactor it, and while you're in there exclude test accounts" pauses.
CLAUSE_SPLIT = re.compile(
    r"(?i)(?<=[.!?])\s+(?=[A-Z])|\bwhile\s+you(?:'re|\s+are)\s+(?:in\s+there|there|at\s+it)\b|\band\s+also\b|\balso\b|\bplus\b|\+|;|\n"
    r"|\bthen\b|\band\s+(?=(?:make|have|change|switch|use|swap|drop|remove|rename|exclude|only|add|update)\b)"
)
# The requester saying the output stays the same.
SAME_OUTPUT = re.compile(
    r"""(?ix)
    \b(?:must|should|has\s+to|have\s+to|needs?\s+to|will)\s+(?:not\s+(?:change|move|differ)|stay|remain|match
       |come\s+out\s+the\s+same|be\s+(?:exactly\s+)?(?:the\s+same|identical|unchanged))\b
    | \bwithout\s+(?:changing|moving|altering|affecting)\b
    | \b(?:no|zero|without)\s+(?:\w+\s+){0,2}changes?\b | \bno\s+edits\b | \bjust\s+(?:the\s+)?analysis\b
    | \bdon'?t\s+(?:fix|edit|change)\b[^?!\n]{0,10}\byet\b | \bwith\s+the\s+current\s+(?:column\s+)?types\b
    | \bsame\s+(?:output|results?|values?|numbers?|rows|data|columns?|order)\b
    | \b(?:results?|output|values?|numbers?)\s+(?:stay\s+|are\s+|must\s+be\s+)?(?:identical|unchanged|the\s+same)\b
    | \bidentical\s+(?:results?|output|values?)\b | \brow[-\s]for[-\s]row\b | \bbyte[-\s]for[-\s]byte\b
    | \b(?:don'?t|do\s+not|never)\s+(?:change|touch|alter|modify)\b(?!\s+(?:the\s+|our\s+|any\s+)?(?:db|database|warehouse|prod\w*|snowflake|bigquery|databricks|redshift|postgres\w*|duckdb|dev\s+target|target|cluster)\b)
    | \bleave\b[^?!\n]{0,40}\b(?:alone|as[-\s]is|untouched|unchanged)\b | \b(?:column\s+names?|columns)\s+stay\b
    | \bjust\s+explain\b | \bwhat\b[^?!\n]{0,60}\bmean | \b(?:is|are)\s+already\b
    | \b(?:should|must|needs?\s+to)\s+be\s+(?:easier|simpler|cleaner|faster|quicker|more\s+readable|readable)\b | \breport\s+back\b | \bsummari[sz]e\s+for\s+me\b
    """
)
# Spans where a change word acts on something consumers never see: a CTE, an
# alias, a test, a selector, an explanation. They are removed before matching.
BUILD_OBJECT_ACTION = re.compile(
    r"""(?ix)
    \brenam\w*\s+(?:the\s+|a\s+|this\s+)?(?:local\s+)?(?:macro\s+)?(?:[`'"]?[\w.]+[`'"]?\s+)?(?:cte|alias|argument|arg|variable|var|param\w*)\b
    | \brenam\w*\s+(?:the\s+)?file\b[^?!\n]*\bkeep\w*\b[^?!\n]*
    | \bwithout\s+\w+ing\b[^?!\n]{0,40}
    | \b(?:tests?|selectors?|checks?|lint\w*|ci)\b(?!\s+(?:accounts?|users?|kitchens?|orders?|customers?|data|rows|records|stores?|merchants?|transactions?|tenants?))[^?!\n]{0,80}\b(?:exclud\w*|filter\w*|where|only)\b[^?!\n]*
    | \b(?:filter\w*|where|exclusion)\b[^?!\n]{0,60}\b(?:tests?|checks?)\b(?!\s+(?:accounts?|users?|kitchens?|orders?|customers?|data|rows|records|stores?|merchants?|transactions?|tenants?))[^?!\n]*
    | \bdescription\b[^?!\n]*
    | \b(?:remove|delete|drop|strip)\b[^?!\n]{0,20}\b(?:semicolons?|commas?|spaces|newlines|imports?|deprecated|warnings?)\b[^?!\n]*
    | \brenam\w*\s+(?:the\s+)?\S*\s*(?:sub)?(?:folder|directory|path|schema\.yml)\b[^?!\n]*
    | \b(?:convert|replace|swap|port)\b[^?!\n]{0,60}\bto\s+use\s+(?:dbt_utils|a\s+macro|the\s+macro|macros?)\b[^?!\n]*
    | \b(?:document|documenting|explain|explaining|describe|describing)\b[^?!\n]{0,10}\b(?:why|how|what|the|that)\b[^?!\n]*
    | \b(?:remove|delete|drop)\s+(?:the\s+|an?\s+|this\s+)?(?:unused|dead|commented[-\s]out|stale|redundant|extra|debug|obsolete)\b[^?!\n]{0,40}
    | \b(?:remove|delete|drop)\b[^?!\n]{0,20}(?:\{\{\s*log|\bdebug\b|\bprint\b)[^?!\n]{0,40}
    | \b(?:freshness|warn_after|error_after|warn_if|error_if)\b[^?!\n]*
    | \b(?:move|hoist|pull|extract)\b[^?!\n]{0,40}\binto\s+(?:an?\s+)?(?:project\s+)?(?:var|variable|macro)\b[^?!\n]*
    | \b(?:remove|delete|drop)\s+(?:the\s+|an?\s+|this\s+)?(?:import|ctes?|comments?|whitespace|override|log)\b[^?!\n]{0,40}
    | \b(?:do\s+not|don'?t|never)\s+(?:alter|change|touch|modify)\b(?!\s+(?:the\s+|our\s+|any\s+)?(?:db|database|warehouse|prod\w*|snowflake|bigquery|databricks|redshift|postgres\w*|duckdb|dev\s+target|target|cluster)\b)[^?!\n]*
    """
)
# Unambiguous asks to change a published interface or what it contains.
STRONG_MEANING = re.compile(
    r"""(?ix)
    \brenam(?:e|es|ing)\b(?!\s+(?:the\s+|a\s+|this\s+)?(?:cte|ctes|alias|aliases|variable|macro|branch|tag|folder|directory|file)\b)
       (?!\s+\S*(?:/|\.ya?ml|\.sql|\.md)\b)
    | \b(?:drop|remove|delete|deprecate|retire)\b[^?!\n]{0,30}\b(?:column|field|metric|measure|dimension|attribute)s?\b
    | \b(?:drop|remove|delete|deprecate|retire)\s+(?:the\s+)?`?[a-z]+_[a-z0-9_]+`?(?!\s*(?:config|test|cte|macro|ref|tag|call))
    | `?\b[a-z]+_[a-z0-9_]+`?\b[^?!\n]{0,30}\b(?:leaves?\s+(?:\w+\s+){0,3}out|skips?|omits?|ignores?|excludes?|drops?|no\s+longer\s+(?:count|includ)\w*|stops?\s+count\w*)\b(?!\s+(?:the\s+)?(?:tests?|ci|checks?|lint\w*|config|step)\b)
    | \b(?:have|make|get|let)\s+(?:that|this|the|those|these)\s+(?:metric|measure|kpi|number|average|rate|total|count|dimension)s?\s+(?:\w+\s+){0,2}(?:leave|skip|exclude|omit|ignore|drop|stop\s+count\w*|no\s+longer)\b
    | \b(?:filter|exclud)\w*\b[^?!\n]{0,40}\b(?:out\s+of|from)\s+(?:the\s+)?`?[a-z]+_[a-z0-9_]+`?(?!\s*(?:config|test|cte|macro|ref|tag|call))
    | \b(?:retype|recast)\b | \bcast\b[^?!\n]{0,40}\b(?:to|as)\b | \bmake\b[^?!\n]{0,30}\ba\s+(?:string|integer|int|number|date|timestamp|boolean|varchar|decimal)\b
    | \b(?:change|switch|convert|move|make)\b[^?!\n]{0,40}\b(?:data\s+type|grain|timezone|time\s+zone|currency)\b
    | \bper[-\s](?:day|hour|week|month|user|order|session)\s+instead\s+of\b
    | \b(?:exclude[sd]?|excluding|ignor(?:e|es|ed|ing)|filter(?:ing)?\s+out|net\s+out|pull\b[^?!\n]{0,30}\bout\s+of|double[-\s]?count)
    | \b(?:to|into|in)\s+(?:usd|eur|gbp|jpy|cad|aud|utc|local\s+time)\b
    | \b(?:remove|drop|delete|get\s+rid\s+of)\b[^?!\n]{0,20}\b(?:duplicates?|dupes|rows|records)\b(?!\s+(?:tests?|ctes?|ya?ml|config|blocks?|definitions?|entr(?:y|ies)))
    | \binstead\s+of\s+\d | \bfrom\s+\d+\s*(?:days?|min\w*|hours?|%)?\s+to\s+\d
    | \bfilter(?:ing|ed|s)?\s+(?:to|down\s+to)\b | \b(?:to|on)\s+\w+(?:\s+\w+)?\s+only\b
    | \bversion\s+of\b | \b(?:team'?s?|finance'?s?|ops'?|their)\s+(?:version|definition)\b
    | \bstop\s+(?:count|includ|treat|track|report|exclud|show|us|apply|deduct|subtract|add|charg|bill|flagg|mark|consider)\w*ing\b
    | \b(?:drop|remove|exclude|strip)\b[^?!\n]{0,50}\bfrom\b[^?!\n]{0,30}\b(?:totals?|counts?|metrics?|revenue|sums?|numbers|rates?|kpis?)\b
    | \b(?:cap|caps|capped|clamp)\b[^?!\n]{0,30}\bat\b | \b(?:threshold|cutoff)\b[^?!\n]{0,30}\b(?:to|from|at)\s+\d
    | \bat\s+\d+(?:\.\d+)?\s+(?:rather|instead|not)\b
    | \bset\s+`?\w+_\w+`?\s+to\b
    | \bsourced\s+from\b | \buse\s+`?\w+_\w+`?\s+(?:for|as)\b
    | \b(?:retain|keep)\s+(?:the|only)\b[^?!\n]{0,40}\b(?:highest|lowest|latest|earliest|first|last|most|least|newest|oldest|max\w*|min\w*)\b
    | \bto\s+the\s+(?:existing\s+)?(?:primary|unique|surrogate|natural)\s+key\b
    | \b(?:change|switch)\b[^?!\n]{0,20}\b(?:primary|unique|surrogate|natural)\s+key\b
    | \b(?:trim|lowercase|uppercase|lower-?case|upper-?case|normali[sz]e|standardi[sz]e|title-?case)\b(?!\s+(?:keywords?|sql|identifiers?|functions?))
    | \btakes?\s+precedence\b | \bbackfill\b[^?!\n]{0,40}\bfrom\b
    | \b(?:be|get|are|is)\s+(?:removed|excluded|dropped|filtered(?:\s+out)?|deleted|ignored|hidden)\b
    | \b(?:remove|drop|exclude|strip|filter\s+out|take\s+out)\b[^?!\n]{0,80}\bfrom\s+(?:the\s+)?(?!docs?\b|ya?ml\b|readme\b|descriptions?\b|tests?\b|selectors?\b|ci\b|requirements\b|packages?\b|the\s+docs\b)\w+
    | \banchor\w*\b[^?!\n]{0,30}\bon\b
    | \bhash(?:ed|ing)?\b[^?!\n]{0,30}\b(?:emails?|names?|phones?|ids?|pii)\b | \bmask(?:ed|ing)?\b
    | \bso\s+(?:that\s+)?(?:we|it|they|the\s+\w+)\s+(?:get|gets|include|includes|show|shows|counts?|match|matches|reflects?|stops?|picks?\s+up)\b
    | \b(?:take|pull)\s+out\b[^?!\n]{0,40}\b(?:filter|date|cutoff|condition|where)\b
    | \bonly\b[^?!\n]{0,40}\b(?:include|count|keep|use|consider|allow)s?\b
    | \b(?:count|counts|counted|counting)\b[^?!\n]{0,40}\b(?:as|toward|towards)\b(?!\s+(?:a|the)\s+test)
    | \btreat(?:s|ed|ing)?\b[^?!\n]{0,40}\bas\b
    | \binclud(?:e|es|ing)\b[^?!\n]{0,40}\b(?:tax|fees?|refunds?|discounts?|shipping|returns?|cancell?ations?)\b
    | \binclud(?:e|es|ing)\b[^?!\n]{0,60}\bin\s+(?:the\s+)?(?:denominator|numerator|count|total|metric|rate)\b
    | \b(?:divide|divided)\s+by\b | \bsubtract\w* | \bnet\s+of\b | \b(?:denominator|numerator)\b
    | \b(?:inner|left|right|full)\s+join\b(?![^?!\n]{0,40}\b(?:produces?|ever|check|whether)\b)
    | \bgoing\s+forward\b | \bfrom\s+now\s+on\b | \bredefin | \b(?:new|different|finance|official)\s+(?:version|definition)\b
    | \b(?:collapse|dedupe|deduplicate|dedup|fold|remap)\b | \bwins?\s+over\b
    | \b(?:read|pull|come|source)\w*\s+from\s+the\s+(?:new|newer|other|carrier|finance)\b
    | \bunique_key\b[^?!\n]{0,20}\bto\b(?![^?!\n]{0,20}\bsame\b)
    | \battribution\s+window\b | \bbump\b[^?!\n]{0,30}\b(?:window|threshold|lookback|days|limit|rate)\b
    | \b(?:lookback|window)\s+(?:to|of)\s+\d
    """
)
# Words that point at a change in meaning unless the requester says the output stays the same.
WEAK_MEANING = re.compile(
    r"""(?ix)
    \b(?:should|needs?\s+to|must|has\s+to|ought\s+to)\s+(?:be|use|come|start|end|count|include|reflect|only|now|mean|equal|show)\b
    | \binstead\s+of\b | \brather\s+than\b | \bnot\s+the\b | \bmeans?\b | \bbased\s+on\b
    | \bdefinition\b | \blogic\b | \bcalculat | \bcomput(?:e|es|ed|ing|ation) | \bformula
    | \b(?:wrong|incorrect|inaccurate|off\s+by|overstat|understat|inflat|too\s+(?:high|low)|doesn'?t\s+match)
    | \b(?:merge|combine|consolidate)\b | \bswap\b | \b(?:precedence|priority)\b | \bround(?:ed|ing)?\b
    | \b(?:usd|eur|gbp|jpy|cad|aud|utc|local\s+time)\b
    """
)
# Words for work that keeps what consumers receive.
BUILD_ONLY = re.compile(
    r"""(?ix)
    materiali[sz] | \bincremental | \bpartition | \bcluster(?:_by|ing|ed)?\b | \bperformance | \bfaster | \bspeed | \bslow
    | \boptimi[sz] | \btimes?\s+out | \brebuild | \brefactor | \brestructur | \blayer | \breorgani[sz]
    | \bclean\s+up | \breadab | \bconfig | \btests? | \btesting | \bci\b | \bdoc(?:s|ument|umentation|ument\w*)?
    | \bdescri(?:be|ption) | \bcomment | \bmeta\b | \bowner | \btags? | \bgrants? | \bfreshness | \bexposure | \breadme
    | \btypo | \bcompile | \bsyntax | \bparse | \blint | \bsqlfluff | \bformat | \bindent | \bwhitespace | \bjinja
    | \bmacro | \berror | \bdebug | \blog\(\) | \bvar\b | \bvars\b | \bhard[-\s]?cod | \bselect\s+\* | \bcolumn\s+list
    | \bon_schema_change | \bincremental_strategy | \bview\b | \btable\b | \bcte | \bsubquer | \bya?ml\b | \bfolder
    | \bdirectory | \brefs?\b | \blineage | \bcompare | \bnew\s+(?:model|mart|column|field|metric|measure|dimension|kpi|ratio|source|entit)
    | \badd(?:s|ed|ing)?\b | \bbuild\b | \bcreate\b | \bgenerate\b | \breview\b | \bexplain | \btrace | \binvestigat
    | \bwhy\b | \bcheck\b | \bpackage | \bupgrade | \bversion\b | \bcompiles?\b | \bcallers?\b | \bephemeral | \bdbt\s+contract | \bcontract\s+on\b | \bwalk\s+me\s+through | \bdag\b | \bfind\b | \bfile\b | \balias | \bmove\b | \bmodels/ | \bcontract\s+enforc\w* | \benforc\w*\s+(?:the\s+)?contract | \bvariable | \bhoist | \bunique_key | \bstrategy | \bcount\s+(?:how\s+many|the\s+rows) | \bdev\s+target | \bprod\b
    | \bbreak\b[^?!\n]{0,20}\bup\b | \bsplit\s+(?:it|this|the\s+model|\w+\s+into\s+(?:two|three|\d|several|a\s+few|smaller))\b
    """
)


class OverBudget(Exception):
    """Reading the project took longer than a gate on every edit may take."""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _check_budget(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise OverBudget


CONTRAST = re.compile(r"(?i)\b(?:rather\s+than|instead\s+of)\b")
APPROVAL_CLAIM = re.compile(
    r"(?i)\b(?:signed[\s-]+off|(?:has|have|had|already|both|all)\s+(?:\w+\s+){0,2}approved"
    r"|approved\s+(?:this|the|it|that)\b|gave\s+(?:us\s+)?(?:the\s+|a\s+)?(?:go[\s-]?ahead|ok|okay|green\s+light)"
    r"|agreed\s+to\s+(?:this|the|it)\b)"
)
UNMET_APPROVAL = re.compile(
    r"(?i)(?:\bnot|n't|\bnever|\byet\s+to|\bbefore|\buntil|\bonce|\bif|\bwhen|\bwhether|\bwill|\bneeds?\s+to)"
    r"(?:\s+\w+){0,3}\s*$"
)


def claims_approval(prompt: str) -> bool:
    """Whether the request says the change has already been approved by someone."""
    return any(
        not UNMET_APPROVAL.search(prompt[max(0, match.start() - 40) : match.start()])
        for match in APPROVAL_CLAIM.finditer(prompt)
    )


def asks_to_redefine(prompt: str) -> bool:
    """Whether a request could change what a published model means, not only how it is built."""
    clauses = [BUILD_OBJECT_ACTION.sub(" refactor ", clause) for clause in CLAUSE_SPLIT.split(prompt) if clause and clause.strip()]
    if any(STRONG_MEANING.search(clause) for clause in clauses):
        return True
    if SAME_OUTPUT.search(prompt):
        return False
    if any(
        (WEAK_MEANING.search(clause) or CONTRAST.search(clause)) and not BUILD_ONLY.search(clause)
        for clause in clauses
    ):
        return True
    return not BUILD_ONLY.search(" ".join(clauses))


RENAMED_NAME = re.compile(
    r"(?i)\brenam\w*\s+(?:the\s+)?(?:column\s+|field\s+|metric\s+|measure\s+)?[`'\"]?([a-z][a-z0-9_]*)[`'\"]?"
    r"\s+(?:to|as|into)\s+[`'\"]?([a-z][a-z0-9_]*)[`'\"]?"
)
REMOVED_NAME = re.compile(
    r"(?i)\b(?:drop|remove|delete|deprecate|retire)\s+(?:the\s+)?(?:column\s+|field\s+)?[`'\"]?([a-z][a-z0-9]*_[a-z0-9_]*)[`'\"]?"
)
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _name_hash(name: str) -> str:
    return hashlib.sha256(name.lower().encode("utf-8")).hexdigest()[:16]


def held_names(prompt: str) -> dict[str, list[str]] | None:
    """When a request's only meaning change is renaming or removing named fields, those names.

    The rest of such a request (a refactor, docs) can go ahead as long as each
    edit leaves the named fields as they are, so the names are what the gate
    holds. They are kept as hashes, never as text.
    """
    old: list[str] = []
    new: list[str] = []
    remainders: list[str] = []
    for clause in CLAUSE_SPLIT.split(prompt):
        if not clause or not clause.strip():
            continue
        for match in RENAMED_NAME.finditer(clause):
            old.append(match.group(1))
            new.append(match.group(2))
        remainder = REMOVED_NAME.sub(lambda match: old.append(match.group(1)) or " ", RENAMED_NAME.sub(" ", clause))
        remainder = BUILD_OBJECT_ACTION.sub(" refactor ", remainder)
        if STRONG_MEANING.search(remainder) or (
            (WEAK_MEANING.search(remainder) or CONTRAST.search(remainder)) and not BUILD_ONLY.search(remainder)
        ):
            return None
        remainders.append(remainder)
    if not old or not BUILD_ONLY.search(" ".join(remainders)):
        return None
    return {"old": sorted({_name_hash(name) for name in old}), "new": sorted({_name_hash(name) for name in new})}


def post_edit_text(payload: dict[str, Any], target: Path, tool: str) -> str | None:
    """The file as this edit would leave it, when the edit says so."""
    tool_input = host_contract.extract_tool_input(payload)
    if not isinstance(tool_input, dict):
        return None
    if tool == "delete":
        return ""
    for key in ("content", "contents", "file_text"):
        if isinstance(tool_input.get(key), str):
            return tool_input[key]
    current = _read(target)
    edits = tool_input.get("edits") if isinstance(tool_input.get("edits"), list) else [tool_input]
    for edit in edits:
        old, new = (edit.get("old_string"), edit.get("new_string")) if isinstance(edit, dict) else (None, None)
        if not isinstance(old, str) or not isinstance(new, str) or old not in current:
            return None
        current = current.replace(old, new) if edit.get("replace_all") else current.replace(old, new, 1)
    return current if edits else None


def keeps_held_names(text: str | None, held: dict[str, list[str]]) -> bool:
    if text is None:
        return False
    present = {_name_hash(token) for token in IDENTIFIER.findall(text)}
    return set(held["old"]) <= present and not set(held["new"]) & present


def project_root_for(path: Path) -> Path | None:
    for parent in [path.parent, *path.parent.parents]:
        if (parent / "dbt_project.yml").is_file():
            return parent
    return None


def guard_disabled(project_root: Path, roots: list[Path]) -> bool:
    for base in [project_root, *roots]:
        if GUARD_OFF.search(_read(base / ".ae" / "project.yml")):
            return True
    return False


def _model_paths(project_root: Path) -> list[str]:
    match = MODEL_PATHS.search(_read(project_root / "dbt_project.yml"))
    if not match:
        return ["models"]
    paths = [item.strip().strip("'\"").strip("/") for item in match.group(1).split(",")]
    return [path for path in paths if path] or ["models"]


def model_for(path: Path, project_root: Path) -> tuple[str, tuple[str, ...]] | None:
    """The model a SQL file defines, and its folder parts under the model path."""
    if path.suffix.lower() != ".sql":
        return None
    try:
        relative = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return None
    if any(part in SKIPPED_DIRS for part in relative.parts):
        return None
    for model_path in _model_paths(project_root):
        prefix = tuple(Path(model_path).parts)
        if relative.parts[: len(prefix)] == prefix:
            return path.stem, tuple(relative.parts[len(prefix) : -1])
    return None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def model_blocks(text: str) -> dict[str, str]:
    """Map each model entry under a `models:` key to the text of its block."""
    blocks: dict[str, str] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        section = MODELS_KEY.match(lines[index])
        index += 1
        if not section:
            continue
        section_indent = len(section.group(1))
        entry_indent: int | None = None
        current: str | None = None
        collected: list[str] = []
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                indent = _indent(line)
                if indent < section_indent or (indent == section_indent and not stripped.startswith("-")):
                    break
                entry = ENTRY_NAME.match(line)
                if entry and (entry_indent is None or len(entry.group(1)) == entry_indent):
                    if current:
                        blocks[current] = "\n".join(collected)
                    entry_indent = len(entry.group(1))
                    current = entry.group(2)
                    collected = []
            if current:
                collected.append(line)
            index += 1
        if current:
            blocks[current] = "\n".join(collected)
    return blocks


def _block_reasons(block: str) -> list[str]:
    reasons = []
    if PUBLIC_ACCESS.search(block):
        reasons.append("public access")
    if CONTRACT_KEY.search(block) and ENFORCED_TRUE.search(block):
        reasons.append("an enforced contract")
    return reasons


def folder_reasons(project_root: Path, folder: tuple[str, ...]) -> list[str]:
    """Access and contract settings inherited from `dbt_project.yml` folder config."""
    lines = _read(project_root / "dbt_project.yml").splitlines()
    reasons: set[str] = set()
    stack: list[tuple[int, str]] = []
    in_models = False
    models_indent = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = _indent(line)
        if not in_models:
            if MODELS_KEY.match(line):
                in_models, models_indent, stack = True, indent, []
            continue
        if indent <= models_indent:
            in_models = False
            if MODELS_KEY.match(line):
                in_models, models_indent, stack = True, indent, []
            continue
        key_match = re.match(r"^\s*([^:#]+?)\s*:\s*(.*)$", line)
        if not key_match:
            continue
        key, value = key_match.group(1).strip().strip("'\""), key_match.group(2)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        # The first key under `models:` names the project; the rest are folders.
        path = [name for _, name in stack[1:] if not name.startswith("+")]
        if folder[: len(path)] != tuple(path):
            stack.append((indent, key))
            continue
        parent = stack[-1][1] if stack else ""
        if key == "+access" and value.strip().strip("'\"").lower() == "public":
            reasons.add("public access set for its folder in dbt_project.yml")
        if key == "+contract" and ENFORCED_TRUE.search(value):
            reasons.add("an enforced contract set for its folder in dbt_project.yml")
        if key == "enforced" and parent == "+contract" and value.strip().lower().startswith("true"):
            reasons.add("an enforced contract set for its folder in dbt_project.yml")
        stack.append((indent, key))
    return sorted(reasons)


def _walk(project_root: Path, deadline: float):
    for directory, subdirectories, files in os.walk(project_root):
        _check_budget(deadline)
        subdirectories[:] = [name for name in subdirectories if name not in SKIPPED_DIRS]
        for name in files:
            if name.lower().endswith((".yml", ".yaml", ".lkml")):
                yield Path(directory) / name


def published_reasons(project_root: Path, model: str, folder: tuple[str, ...], deadline: float) -> list[str]:
    names = {model, VERSION_SUFFIX.sub("", model)}
    reasons: list[str] = []
    consumers: list[str] = []
    for path in _walk(project_root, deadline):
        text = _read(path)
        relative = str(path.relative_to(project_root))
        if path.suffix.lower() == ".lkml":
            for line in text.splitlines():
                if "sql_table_name" in line and any(re.search(rf"\b{re.escape(name)}\b", line) for name in names):
                    consumers.append(f"LookML in {relative}")
                    break
            continue
        if path.name != "dbt_project.yml":
            for name, block in model_blocks(text).items():
                if name in names:
                    reasons.extend(_block_reasons(block))
        kind = (
            "exposure"
            if re.search(r"^\s*exposures\s*:", text, re.MULTILINE)
            else "semantic model"
            if re.search(r"^\s*semantic_models\s*:", text, re.MULTILINE)
            else "metric"
            if re.search(r"^\s*metrics\s*:", text, re.MULTILINE)
            else "reference"
        )
        for line in text.splitlines():
            if NOT_A_CONSUMER.match(line):
                continue
            if any(found in names for found in REF_CALL.findall(line)):
                consumers.append(f"{kind} in {relative}")
                break
    reasons.extend(folder_reasons(project_root, folder))
    if consumers:
        reasons.append("read by " + ", ".join(sorted(set(consumers))))
    return list(dict.fromkeys(reasons))


def published_index(project_root: Path, deadline: float) -> dict[str, list[str]]:
    """Why each model in the project is published, from one pass over its YAML and LookML."""
    reasons: dict[str, list[str]] = {}
    consumers: dict[str, set[str]] = {}
    for path in _walk(project_root, deadline):
        text = _read(path)
        relative = str(path.relative_to(project_root))
        if path.suffix.lower() == ".lkml":
            for line in text.splitlines():
                if "sql_table_name" in line:
                    for token in re.findall(r"[A-Za-z0-9_]+", line):
                        consumers.setdefault(token, set()).add(f"LookML in {relative}")
            continue
        if path.name != "dbt_project.yml":
            for name, block in model_blocks(text).items():
                reasons.setdefault(name, []).extend(_block_reasons(block))
        kind = (
            "exposure"
            if re.search(r"^\s*exposures\s*:", text, re.MULTILINE)
            else "semantic model"
            if re.search(r"^\s*semantic_models\s*:", text, re.MULTILINE)
            else "metric"
            if re.search(r"^\s*metrics\s*:", text, re.MULTILINE)
            else "reference"
        )
        for line in text.splitlines():
            if not NOT_A_CONSUMER.match(line):
                for found in REF_CALL.findall(line):
                    consumers.setdefault(found, set()).add(f"{kind} in {relative}")
    for name, found in consumers.items():
        reasons.setdefault(name, []).append("read by " + ", ".join(sorted(found)))
    return {name: list(dict.fromkeys(found)) for name, found in reasons.items() if found}


def _strings_under_path_keys(value: Any, depth: int = 0) -> list[str]:
    found: list[str] = []
    if depth > MAX_INPUT_DEPTH:
        return found
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(nested, str) and PATH_KEYS.search(str(key)):
                found.append(nested)
            elif isinstance(nested, (dict, list)):
                found.extend(_strings_under_path_keys(nested, depth + 1))
    elif isinstance(value, list):
        for nested in value:
            if isinstance(nested, str):
                found.append(nested)
            else:
                found.extend(_strings_under_path_keys(nested, depth + 1))
    return found


def _resolve(candidate: str, bases: list[Path]) -> list[Path]:
    candidate = os.path.expanduser(candidate)
    expanded = [candidate] if os.path.isabs(candidate) else [str(base / candidate) for base in bases]
    paths: list[Path] = []
    for item in expanded:
        if any(char in item for char in "*?["):
            paths.extend(Path(match) for match in glob.glob(item, recursive=True))
        else:
            paths.append(Path(item))
    return paths


def _bases(payload: dict[str, Any], cwd: str | None = None) -> list[Path]:
    bases = [Path(cwd)] if cwd else []
    roots = payload.get("workspace_roots") or []
    bases.extend(Path(root) for root in roots if isinstance(root, str) and root)
    return bases or [Path.cwd()]


GUARDED_SUFFIXES = (".sql", ".yml", ".yaml", ".lkml")
CONSUMER_DEFINITION = re.compile(r"^\s*(?:semantic_models|metrics|saved_queries)\s*:", re.MULTILINE)


def edit_targets(payload: dict[str, Any]) -> list[Path]:
    tool_input = host_contract.extract_tool_input(payload)
    bases = _bases(payload, payload.get("cwd") if isinstance(payload.get("cwd"), str) else None)
    targets: list[Path] = []
    for value in _strings_under_path_keys(tool_input):
        if value.lower().endswith(GUARDED_SUFFIXES) or any(char in value for char in "*?["):
            targets.extend(_resolve(value, bases))
    return targets


def yaml_models(path: Path, project_root: Path) -> list[tuple[str, tuple[str, ...]]]:
    """Models a properties file declares, each with the folder of its SQL file."""
    if path.suffix.lower() not in {".yml", ".yaml"} or path.name == "dbt_project.yml":
        return []
    try:
        relative = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return []
    if any(part in SKIPPED_DIRS for part in relative.parts):
        return []
    found = []
    for name in model_blocks(_read(path)):
        sql = next(iter(path.parent.glob(f"{name}.sql")), None)
        model = model_for(sql, project_root) if sql else None
        found.append(model or (name, ()))
    return found


SNAPSHOT_BLOCK = re.compile(r"\{%-?\s*snapshot\s+([A-Za-z0-9_]+)\s*-?%\}")
SNAPSHOT_IDENTITY = ("unique_key", "strategy", "updated_at")
CONFIG_VALUE = r"\s*=\s*(\[[^\]]*\]|'[^']*'|\"[^\"]*\")"


def snapshot_identity(text: str) -> tuple[str, dict[str, str | None], set[str]] | None:
    """A snapshot's name, the settings that match stored rows, and its check columns."""
    block = SNAPSHOT_BLOCK.search(text)
    if not block:
        return None
    values: dict[str, str | None] = {}
    for key in SNAPSHOT_IDENTITY:
        found = re.search(rf"\b{key}{CONFIG_VALUE}", text)
        values[key] = re.sub(r"\s+", "", found.group(1)).replace('"', "'") if found else None
    found = re.search(rf"\bcheck_cols{CONFIG_VALUE}", text)
    columns = set(re.findall(r"['\"]([^'\"]+)['\"]", found.group(1))) if found else set()
    return block.group(1), values, columns


def snapshot_readers(project_root: Path, name: str, target: Path, deadline: float) -> list[str]:
    readers: set[str] = set()
    for directory, subdirectories, files in os.walk(project_root):
        _check_budget(deadline)
        subdirectories[:] = [entry for entry in subdirectories if entry not in SKIPPED_DIRS and not entry.startswith(".")]
        for entry in files:
            path = Path(directory) / entry
            if path == target or not entry.lower().endswith((".sql", ".yml", ".yaml")):
                continue
            if name in REF_CALL.findall(_read(path)):
                readers.add(path.relative_to(project_root).as_posix())
    return sorted(readers)


def snapshot_reasons(target: Path, after: str | None, project_root: Path, deadline: float) -> dict[str, list[str]]:
    """An edit that changes how a read snapshot matches the history it has stored."""
    if target.suffix.lower() != ".sql":
        return {}
    identity = snapshot_identity(_read(target))
    if identity is None:
        return {}
    name, values, columns = identity
    if after is not None:
        new = snapshot_identity(after)
        if new is not None and new[0] == name and new[1] == values and columns <= new[2]:
            return {}
    readers = snapshot_readers(project_root, name, target, deadline)
    if not readers:
        return {}
    return {name: [f"stored history read by {', '.join(readers)}; changing how it matches rows splits or orphans that history"]}


EXPOSURES_KEY = re.compile(r"^\s*exposures\s*:", re.MULTILINE)


def _consumer_refs(text: str) -> set[str]:
    return {found for line in text.splitlines() if not NOT_A_CONSUMER.match(line) for found in REF_CALL.findall(line)}


def dropped_exposure_refs(target: Path, after: str | None) -> list[str]:
    """Models an exposures file would stop listing; every listed model when the result is unknown."""
    before = _read(target)
    if target.suffix.lower() not in {".yml", ".yaml"} or not EXPOSURES_KEY.search(before):
        return []
    return sorted(_consumer_refs(before) - (_consumer_refs(after) if after is not None else set()))


def downstream_models(
    project_root: Path, model: str, deadline: float
) -> list[tuple[str, tuple[str, ...]]]:
    """Every model that reads `model`, directly or through other models."""
    readers: dict[str, set[str]] = {}
    folders: dict[str, tuple[str, ...]] = {}
    for model_path in _model_paths(project_root):
        for directory, subdirectories, files in os.walk(project_root / model_path):
            _check_budget(deadline)
            subdirectories[:] = [name for name in subdirectories if name not in SKIPPED_DIRS]
            for name in files:
                if not name.lower().endswith(".sql"):
                    continue
                path = Path(directory) / name
                found = model_for(path, project_root)
                if not found:
                    continue
                folders[found[0]] = found[1]
                for parent in set(REF_CALL.findall(_read(path))):
                    readers.setdefault(parent, set()).add(found[0])
    seen: list[str] = []
    queue = list(readers.get(model, ()))
    while queue:
        current = queue.pop(0)
        if current in seen or current == model:
            continue
        seen.append(current)
        queue.extend(readers.get(current, ()))
    return [(name, folders.get(name, ())) for name in seen]


def consumer_definition(path: Path, project_root: Path) -> str | None:
    """A semantic model, metric, or LookML file: what consumers read is defined there."""
    try:
        relative = path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return None
    if path.suffix.lower() == ".lkml":
        return relative
    if path.suffix.lower() in {".yml", ".yaml"} and CONSUMER_DEFINITION.search(_read(path)):
        return relative
    return None


def _segment_writes(segment: str) -> list[str]:
    tokens = [token for token in segment.split() if not ENV_ASSIGNMENT.match(token)]
    if not tokens:
        return []
    program = os.path.basename(tokens[0])
    if program == "git" and len(tokens) > 1 and tokens[1] in READ_ONLY_GIT:
        return []
    if program in READ_ONLY_PROGRAMS and not IN_PLACE.search(segment) and program not in {"python3", "python"}:
        return []
    if program in {"python3", "python"} and not re.search(r"open\(|write|Path\(", segment):
        return []
    return [token for token in TOKEN_SPLIT.split(segment) if token and not token.startswith("-")]


def shell_targets(payload: dict[str, Any]) -> list[Path]:
    command = host_contract.extract_command(payload) or ""
    tool_input = host_contract.extract_tool_input(payload)
    cwd = tool_input.get("cwd") if isinstance(tool_input, dict) else None
    bases = _bases(payload, cwd if isinstance(cwd, str) and cwd else None)
    candidates = REDIRECT_TARGET.findall(command)
    for segment in SEGMENT_SPLIT.split(command):
        candidates.extend(_segment_writes(segment.strip()))
    targets: list[Path] = []
    for candidate in candidates:
        candidate = candidate.strip("'\"`")
        if candidate.lower().endswith(GUARDED_SUFFIXES) or any(char in candidate for char in "*?["):
            targets.extend(_resolve(candidate, bases))
    return targets


def user_turns(transcript_path: Any) -> int | None:
    """How many messages the requester has sent, or None when it cannot be read."""
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    text = _read(Path(transcript_path))
    if not text:
        return None
    count = parsed = 0
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        parsed += 1
        if isinstance(entry, dict) and (entry.get("role") == "user" or entry.get("type") == "user"):
            count += 1
    return count if parsed and count else None


def _state_path(conversation: str) -> Path:
    return STATE_DIR / f"{hashlib.sha256(conversation.encode('utf-8')).hexdigest()[:24]}.json"


def _load_state(conversation: str) -> dict[str, Any]:
    try:
        state = json.loads(_state_path(conversation).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save_state(conversation: str, state: dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _state_path(conversation).write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def _allow(message: str = "", reason: str = "not-published") -> dict[str, str]:
    decision = {"permission": "allow", "reason_code": reason}
    if message:
        decision["user_message"] = message
    return decision


def _conversation(payload: dict[str, Any]) -> str | None:
    conversation = payload.get("conversation_id") or payload.get("session_id") or payload.get("transcript_path")
    return conversation if isinstance(conversation, str) and conversation else None


def is_prompt_event(payload: dict[str, Any]) -> bool:
    event = str(payload.get("hook_event_name") or "").lower()
    return event in PROMPT_EVENTS or ("prompt" in payload and not payload.get("tool_name"))


def record_prompt(payload: dict[str, Any]) -> None:
    """Count the requester's messages and note whether the latest asks to redefine."""
    conversation = _conversation(payload)
    if conversation is None:
        return
    state = _load_state(conversation)
    prompt = payload.get("prompt")
    state["_prompts"] = int(state.get("_prompts") or 0) + 1
    state["_redefining"] = asks_to_redefine(prompt) if isinstance(prompt, str) else True
    held = held_names(prompt) if isinstance(prompt, str) and state["_redefining"] else None
    if held:
        state["_held"] = held
    else:
        state.pop("_held", None)
    state["_approval_claimed"] = bool(state["_redefining"] and isinstance(prompt, str) and claims_approval(prompt))
    _save_state(conversation, state)


def decide(payload: dict[str, Any]) -> dict[str, str]:
    name = host_contract.tool_name(payload).lower().replace("-", "_")
    if name in EDIT_TOOLS:
        targets = edit_targets(payload)
    elif name in SHELL_TOOL_NAMES:
        targets = shell_targets(payload)
    else:
        return _allow(reason="not-applicable")

    conversation = _conversation(payload)
    state = _load_state(conversation) if conversation else {}
    prompt_aware = "_prompts" in state
    roots = _bases(payload)
    deadline = time.monotonic() + SCAN_BUDGET_SECONDS
    # Stored snapshot history cannot be rebuilt, so this holds however the
    # request is phrased.
    guarded: dict[str, list[str]] = {}
    try:
        for target in dict.fromkeys(targets):
            project = project_root_for(target) if target.is_file() else None
            if project is not None and not guard_disabled(project, roots):
                guarded.update(snapshot_reasons(target, post_edit_text(payload, target, name), project, deadline))
    except OverBudget:
        return _allow("AE could not finish checking snapshot readers in time, so this action was allowed.", "guard-over-budget")
    snapshots = set(guarded)
    if prompt_aware and not state.get("_redefining") and not guarded:
        return _allow(reason="not-a-redefinition")

    for target in dict.fromkeys(targets):
        if prompt_aware and not state.get("_redefining"):
            break
        # A model that does not exist yet has no consumers to break.
        if not target.is_file():
            continue
        project = project_root_for(target)
        if project is None or guard_disabled(project, roots):
            continue
        held = state.get("_held") if prompt_aware else None
        if held and keeps_held_names(post_edit_text(payload, target, name), held):
            continue
        model = model_for(target, project)
        # Without the request in view, a YAML edit is most likely a description
        # or a test, so properties files are guarded only under a redefinition.
        models = [model] if model else yaml_models(target, project) if prompt_aware else []
        after = post_edit_text(payload, target, name) if models and not model else None
        if after is not None:
            before_blocks, after_blocks = model_blocks(_read(target)), model_blocks(after)
            models = [entry for entry in models if before_blocks.get(entry[0]) != after_blocks.get(entry[0])]
        try:
            for model_name, folder in models:
                reasons = published_reasons(project, model_name, folder, deadline)
                # Under a redefinition, changing what feeds a published model
                # changes what its consumers receive just as surely.
                if not reasons and prompt_aware:
                    readers = downstream_models(project, model_name, deadline)
                    index = published_index(project, deadline) if readers else {}
                    for reader, reader_folder in readers:
                        reader_reasons = [
                            *index.get(reader, []),
                            *index.get(VERSION_SUFFIX.sub("", reader), []),
                            *folder_reasons(project, reader_folder),
                        ]
                        if reader_reasons:
                            reasons = [f"feeds the published model `{reader}`, which has {'; '.join(reader_reasons)}"]
                            break
                if reasons:
                    guarded[model_name] = reasons
            definition = consumer_definition(target, project) if prompt_aware and not model else None
            if definition:
                guarded[definition] = ["defines what a semantic layer or BI tool reads"]
            if prompt_aware and not model:
                relative = target.resolve().relative_to(project.resolve()).as_posix()
                for dropped in dropped_exposure_refs(target, post_edit_text(payload, target, name)):
                    guarded.setdefault(dropped, []).append(f"read by an exposure in {relative} that this edit stops listing")
        except OverBudget:
            return _allow(
                f"AE could not finish checking whether {target.name} is published in time, so this action "
                "was allowed.",
                "guard-over-budget",
            )
    if not guarded:
        return _allow()

    if conversation is None:
        return _allow(
            "AE could not identify this conversation, so it could not pause edits to published models.",
            "guard-unidentified",
        )
    # A stated approval is checked by the agent against every consumer, not by
    # the gate: only the agent can tell whose owners the request names. The
    # first edit is held once so the consumer list arrives before any change.
    if prompt_aware and state.get("_approval_claimed"):
        unchecked = {model: reasons for model, reasons in guarded.items() if state.get(f"_checked:{model}") != state["_prompts"]}
        if not unchecked:
            return _allow(reason="approval-claimed")
        for model in unchecked:
            state[f"_checked:{model}"] = state["_prompts"]
        _save_state(conversation, state)
        described = "; ".join(f"`{model}` ({', '.join(reasons)})" for model, reasons in unchecked.items())
        return {
            "permission": "deny",
            "reason_code": "approval-check",
            "user_message": f"AE is checking that the stated approval covers every consumer of {', '.join(unchecked)}.",
            "agent_message": (
                f"Before this edit: the request says the change is approved. Published: {described}. An approval "
                "covers only the consumers whose owners the request names. List each consumer above and whether "
                "the request names its owner as approving. If every one is covered, make the same edit again and "
                "it will go through; then name in your summary each consumer whose numbers move. If any one is not "
                "covered, edit nothing: name that consumer, what it would receive, and an option that leaves it "
                "unchanged, and end with one direct question."
            ),
        }

    replies = state["_prompts"] if prompt_aware else user_turns(payload.get("transcript_path"))
    blocked: dict[str, list[str]] = {}
    unconfirmed: list[str] = []
    for model, reasons in guarded.items():
        entry = state.get(model)
        if not isinstance(entry, dict):
            state[model] = {"turns": replies}
            blocked[model] = reasons
        elif entry.get("turns") is None:
            if replies is None:
                unconfirmed.append(model)
            else:
                entry["turns"] = replies
                blocked[model] = reasons
        elif replies is None:
            unconfirmed.append(model)
        elif replies <= entry["turns"]:
            blocked[model] = reasons
    _save_state(conversation, state)

    if blocked and set(blocked) <= snapshots:
        described = "; ".join(f"`{model}` ({', '.join(reasons)})" for model, reasons in blocked.items())
        return {
            "permission": "deny",
            "reason_code": "snapshot-history-change",
            "user_message": f"AE paused a change to how the snapshot {', '.join(blocked)} matches its stored history until you reply.",
            "agent_message": (
                f"AE paused this edit. {described}. Changing `unique_key`, `strategy`, `updated_at`, or removing a "
                "check column changes how every stored row is matched, and the history cannot be rebuilt from the "
                "source; a full refresh deletes it. Do not make this change by any other route. End your turn with: "
                "what the stored history would lose and who reads it, an option that keeps it (a new snapshot beside "
                "the old one with the corrected key, or a reviewed migration of the stored rows), and one direct "
                "question asking which to apply."
            ),
        }
    if blocked:
        described = "; ".join(f"`{model}` ({', '.join(reasons)})" for model, reasons in blocked.items())
        models = ", ".join(blocked)
        if prompt_aware and state.get("_held"):
            return {
                "permission": "deny",
                "reason_code": "published-name-change",
                "user_message": f"AE held the rename or removal in an edit to the published model {models} until you reply.",
                "agent_message": (
                    f"AE paused this edit. Published: {described}. The only part of the request that changes what "
                    "consumers receive is renaming or removing the fields it names. Do the rest of the request now: "
                    "make this edit again with each of those fields left exactly as it is, under its current name, "
                    "and without the new name. That edit goes through. Do not rename or remove those fields by any "
                    "other route, including an alias, a shell command, another tool, or a new file. Then end your "
                    "turn by reporting the rest of the work as done and asking the requester to approve the rename "
                    "or removal, naming the consumers it affects and a compatibility option such as keeping the old "
                    "column alongside the new one for a period."
                ),
            }
        return {
            "permission": "deny",
            "reason_code": "published-model-change",
            "user_message": f"AE paused an edit to the published model {models} until you reply.",
            "agent_message": (
                f"AE paused this edit. Published: {described}. "
                + (
                    "The request changes what this model means, and that changes what those consumers receive. "
                    if prompt_aware
                    else "Changing this logic can change what those consumers receive. "
                )
                + "Retrying will be denied the same way until "
                "the requester replies, so do not retry, and do not make the change by any other route, "
                "including shell commands, another tool, or a new file. End your turn with the plan instead: "
                "what would change, which consumers it affects and how, and an option that leaves today's "
                "consumers unchanged, such as the new definition as a new column or a versioned model beside "
                "the old one; then end with one direct question asking which to apply. If the change leaves every "
                "published column's name, type, grain, and values as they are, say that in one line and ask for "
                "a go-ahead instead of a plan. Edits to this model go through after the requester replies."
            ),
        }
    if unconfirmed:
        return _allow(
            f"AE could not confirm a reply since it paused edits to {', '.join(unconfirmed)}, so this edit "
            "was allowed. Review the change.",
            "guard-unconfirmed",
        )
    return _allow(reason="approved-after-reply")


def main() -> int:
    try:
        host = host_contract.host_from_argv(sys.argv[1:])
    except ValueError:
        host = "cursor"
    payload: Any = None
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if isinstance(payload, dict) and is_prompt_event(payload):
            try:
                record_prompt(payload)
            except Exception:  # noqa: BLE001 - counting must never hold up a message
                pass
            print(json.dumps({"continue": True}))
            return 0
        decision = decide(payload) if isinstance(payload, dict) else _allow(reason="unreadable-input")
    except Exception:  # noqa: BLE001 - a broken guard must not block every edit
        decision = _allow("AE's published-model guard hit an internal error and allowed this action.", "guard-error")
    _log_decision(payload, decision)
    print(host_contract.render(decision, host))
    return 0


def _log_decision(payload: Any, decision: dict[str, str]) -> None:
    """One line per guarded-tool call, so "why was this allowed" has an answer.

    Kept beside the conversation's state under the same hashed name, and holds
    no identity: the tool, the outcome, and the file names it was about.
    """
    if not isinstance(payload, dict) or decision.get("reason_code") == "not-applicable":
        return
    conversation = payload.get("conversation_id") or payload.get("session_id") or payload.get("transcript_path")
    if not isinstance(conversation, str) or not conversation:
        return
    try:
        name = host_contract.tool_name(payload).lower().replace("-", "_")
        targets = edit_targets(payload) if name in EDIT_TOOLS else shell_targets(payload)
        line = {
            "tool": name,
            "permission": decision.get("permission"),
            "reason": decision.get("reason_code"),
            "files": sorted({target.name for target in targets})[:10],
        }
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with _state_path(conversation).with_suffix(".log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
    except Exception:  # noqa: BLE001 - logging must never change the decision
        pass


if __name__ == "__main__":
    raise SystemExit(main())
