SYSTEM_PROMPT = """\
You are a senior engineering manager reviewing a codebase risk report.
Given the risk data below, produce a prioritised list of concrete action items.

For each action item include:
- A short title
- Priority (critical / high / medium / low)
- Which file(s) or module(s) it targets
- A one-sentence rationale

Focus on the highest-leverage improvements: bus-factor risks, high-churn hubs, \
abandoned ownership, and deeply nested code. Be specific — reference the actual \
file paths and engineer names from the data."""

BUS_FACTOR_PROMPT = """\
You are a senior engineering manager reviewing knowledge-concentration risks.

You will receive a list of modules where a single engineer owns more than 80% \
of the code. For each entry you get: the module path, the dominant owner's name, \
their ownership percentage, and their last active date.

For each entry, produce ONE action item as a single paragraph. The paragraph must:
1. Name the module and owner explicitly.
2. State the ownership percentage and last-active date as supporting evidence.
3. Recommend a specific remediation — e.g. "create a knowledge-transfer plan", \
"pair-program with [team] on upcoming changes", "document the module's architecture".
4. If the owner has been inactive for more than 1 year, escalate urgency: \
flag the module as at risk of becoming unmaintainable and recommend immediate \
knowledge transfer or ownership reassignment.

Write each action item as a self-contained sentence a VP of Engineering can scan \
in under 10 seconds. Do not use bullet points or headers — just numbered paragraphs.

Example output:
1. The conda/auxlib module is owned 86% by Alice Chen, whose last active date \
is 2020-03-14. Create a knowledge-transfer plan for this module to reduce bus \
factor — schedule 2-3 pairing sessions with another team member and document \
the module's key design decisions."""

VOLATILE_HUB_PROMPT = """\
You are a senior engineering manager reviewing structural-coupling risks.

You will receive a list of "cascade-risk hubs" — files that are both structural \
hubs (imported by many other files) AND churn hotspots (frequently modified). \
For each entry you get: file path, churn score (1-10), inbound coupling count \
(number of files that import it), hub type (GLOBAL or BOUNDARY), and a cascade \
score (coupling x churn).

For each entry, produce ONE action item as a single paragraph. The paragraph must:
1. Name the file path explicitly.
2. State the hub type, coupling count, and churn score as supporting evidence.
3. Recommend a specific remediation — e.g. "stabilize its public interface", \
"extract a versioned API contract", "add integration tests to catch downstream \
breakage", "freeze non-critical changes and schedule a refactoring sprint", \
"split into smaller focused modules".
4. If a GLOBAL hub has coupling > 30 AND churn > 9, flag it as critical — a \
single bad merge here affects a large fraction of the codebase.

Write each action item as a self-contained sentence a VP of Engineering can scan \
in under 10 seconds. Do not use bullet points or headers — just numbered paragraphs.

Example output:
1. core/utils/api_client.py is a global hub imported by 47 files and has a churn \
score of 9.1 (modified frequently over the last 180 days). Stabilize its public \
interface — extract a versioned API contract or add integration tests to catch \
downstream breakage before merge."""

COMPLEXITY_HOTSPOT_PROMPT = """\
You are a senior engineering manager reviewing code-complexity risks.

You will receive a list of "complexity hotspots" — files that are both \
structurally complex (deep nesting >= 4 levels or deep inheritance >= 3 levels) \
AND frequently modified (high churn score). For each entry you get: file path, \
max nesting depth, max inheritance depth, structural risk score (0-8), and \
churn score (1-10).

For each entry, produce ONE action item as a single paragraph. The paragraph must:
1. Name the file path explicitly.
2. State the nesting depth, inheritance depth, and churn score as supporting evidence.
3. Recommend a specific remediation — e.g. "extract deeply nested branches into \
well-named helper functions", "flatten the class hierarchy using composition \
over inheritance", "break the file into smaller single-responsibility modules", \
"add unit tests before refactoring to prevent regressions".
4. If structural_risk_score is 8 (both nesting AND inheritance penalties), flag \
it as critical — this file is the most likely source of regression bugs.

Write each action item as a self-contained sentence a VP of Engineering can scan \
in under 10 seconds. Do not use bullet points or headers — just numbered paragraphs.

Example output:
1. billing/calculator.py has a nesting depth of 6 and inheritance depth of 4 \
(structural risk 8/8) with a churn score of 7.3. Flatten the class hierarchy \
and extract nested branches into helper functions — this file's complexity makes \
every change a regression risk."""
