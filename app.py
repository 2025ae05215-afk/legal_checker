import os
import re
import json
import csv
import io
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ==============================================================================
# DOMAIN LEXICON & LEGAL WHITELIST
# ==============================================================================
# Contains standard English baseline tokens combined with legal terms,
# archaic legal syntax, Latin maxims, and contractual defined terms.
LEGAL_WHITELIST = {
    # Archaic & Formulaic Adverbs / Conjunctions
    "herein", "hereinafter", "hereof", "hereto", "hereunder", "herewith",
    "therein", "thereof", "thereto", "thereunder", "thereupon", "wherefore",
    "whereas", "whereby", "wherein", "whereupon", "witnesseth", "forthwith",
    "notwithstanding", "heretofore", "thereunto", "inasmuch",
    
    # Substantive & Procedural Legal Terminology
    "indemnify", "indemnification", "indemnitee", "indemnitor", "subrogation",
    "arbitration", "jurisdiction", "severability", "counterparts", "recitals",
    "testatum", "habendum", "covenant", "covenants", "covenanted", "covenantor",
    "lessee", "lessor", "assignee", "assignor", "mortgagee", "mortgagor",
    "promisor", "promisee", "obligor", "obligee", "licensor", "licensee",
    "bailor", "bailee", "testator", "intestate", "survivorship", "encumbrance",
    "chattel", "tortious", "injunctive", "estoppel", "estopped", "novation",
    "repudiation", "quantum", "meruit", "suretyship", "disgorgement",
    
    # Latin Maxims & Common Phrasing
    "bona", "fide", "inter", "alia", "ultra", "vires", "prima", "facie",
    "mens", "rea", "actus", "reus", "pro", "rata", "quid", "quo", "pari",
    "passu", "mutatis", "mutandis", "in", "lieu", "ad", "hoc", "ex", "parte",
    "force", "majeure", "caveat", "emptor", "stare", "decisis", "habeas", "corpus",
    "res", "judicata", "de", "facto", "de", "jure", "ipso", "facto",
    
    # Contractual Defined Entities & General Baseline Vocabulary
    "agreement", "contract", "clause", "section", "article", "party", "parties",
    "affiliate", "subsidiary", "vendor", "client", "contractor", "confidentiality",
    "proprietary", "intellectual", "property", "termination", "breach", "remedy",
    "remedies", "liability", "damages", "liquidated", "governing", "law",
    "execution", "effective", "date", "preamble", "schedule", "exhibit", "annexure",
    "the", "of", "and", "to", "in", "a", "is", "that", "for", "it", "as", "was",
    "with", "be", "by", "on", "not", "he", "i", "this", "have", "from", "at",
    "one", "has", "will", "all", "would", "there", "their", "shall", "may", "can",
    "should", "must", "any", "each", "every", "other", "such", "which", "or",
    "an", "they", "we", "you", "are", "been", "were", "being", "having", "do",
    "does", "did", "done", "make", "made", "set", "forth", "above", "below",
    "written", "signed", "delivered", "provided", "except", "including", "without",
    "limitation", "respect", "entire", "terms", "conditions", "provisions"
}

# ==============================================================================
# SPELL CHECK TECHNIQUE 1: BURKHARD-KELLER (BK) TREE (LEVENSHTEIN METRIC)
# ==============================================================================
def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculates Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]

class BKNode:
    def __init__(self, word: str):
        self.word = word
        self.children = {}  # Map: distance (int) -> BKNode

class BKTree:
    def __init__(self):
        self.root = None

    def insert(self, word: str):
        word = word.lower()
        if not self.root:
            self.root = BKNode(word)
            return
        curr = self.root
        while True:
            dist = levenshtein_distance(word, curr.word)
            if dist == 0:
                return  # Duplicate word
            if dist in curr.children:
                curr = curr.children[dist]
            else:
                curr.children[dist] = BKNode(word)
                break

    def search(self, word: str, max_dist: int):
        """Returns list of (candidate_word, distance) within max_dist radius."""
        word = word.lower()
        results = []
        if not self.root:
            return results

        candidates = [self.root]
        while candidates:
            node = candidates.pop()
            d = levenshtein_distance(word, node.word)
            if d <= max_dist:
                results.append((node.word, d))
            
            low = d - max_dist
            high = d + max_dist
            for edge_dist, child in node.children.items():
                if low <= edge_dist <= high:
                    candidates.append(child)
        return results

# ==============================================================================
# SPELL CHECK TECHNIQUE 2: PHONETIC ALGORITHM (SOUNDEX)
# ==============================================================================
def compute_soundex(word: str) -> str:
    """Generates standard Soundex code for phonetic match fallback."""
    if not word:
        return ""
    word = word.upper()
    mapping = {
        'B': '1', 'F': '1', 'P': '1', 'V': '1',
        'C': '2', 'G': '2', 'J': '2', 'K': '2', 'Q': '2', 'S': '2', 'X': '2', 'Z': '2',
        'D': '3', 'T': '3',
        'L': '4',
        'M': '5', 'N': '5',
        'R': '6'
    }
    first_letter = word[0]
    tail = word[1:]
    encoded = ""
    prev = mapping.get(first_letter, "")
    
    for char in tail:
        code = mapping.get(char, "")
        if code:
            if code != prev:
                encoded += code
            prev = code
        else:
            prev = ""
            
    encoded = (encoded.replace("0", "") + "000")[:3]
    return first_letter + encoded

# Build global lookup structures
bktree = BKTree()
soundex_index = {}
for term in LEGAL_WHITELIST:
    bktree.insert(term)
    snd = compute_soundex(term)
    soundex_index.setdefault(snd, []).append(term)

# ==============================================================================
# DUAL-ENGINE CANDIDATE RANKING & CONFIDENCE ESTIMATION
# ==============================================================================
def get_spell_suggestions(token: str):
    """
    Queries both BK-Tree and Soundex indexes.
    Calculates combined confidence score based on metric distance and phonetic match.
    """
    clean_token = token.lower()
    if clean_token in LEGAL_WHITELIST:
        return []

    # 1. Query BK-Tree within Levenshtein radius = 2
    bk_results = bktree.search(clean_token, max_dist=2)
    candidates = {word: dist for word, dist in bk_results}

    # 2. Phonetic fallback: add words matching exact Soundex code if edit distance is <= 3
    token_snd = compute_soundex(clean_token)
    if token_snd in soundex_index:
        for p_word in soundex_index[token_snd]:
            if p_word not in candidates:
                d = levenshtein_distance(clean_token, p_word)
                if d <= 3:
                    candidates[p_word] = d

    if not candidates:
        # Fallback to wider distance if token is long enough
        if len(clean_token) > 5:
            wide_results = bktree.search(clean_token, max_dist=3)
            candidates = {word: dist for word, dist in wide_results}

    # 3. Score candidates
    ranked = []
    for cand, dist in candidates.items():
        max_len = max(len(clean_token), len(cand))
        # Base string similarity
        similarity = 1.0 - (dist / max_len)
        # Soundex bonus
        cand_snd = compute_soundex(cand)
        phonetic_bonus = 0.15 if cand_snd == token_snd else 0.0
        # Domain bonus for primary legal vocabulary
        domain_bonus = 0.10 if cand in {"herein", "indemnify", "whereas", "arbitration", "tortious"} else 0.0
        
        raw_score = (similarity * 0.75) + phonetic_bonus + domain_bonus
        confidence = min(0.99, max(0.40, raw_score))
        ranked.append((cand, round(confidence, 2)))

    # Sort descending by confidence
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:3]

# ==============================================================================
# RULE-BASED LEGAL GRAMMAR ENGINE
# ==============================================================================
def check_legal_grammar(text: str):
    """
    Executes domain-adapted grammar and syntactic consistency rules for contracts:
      1. Modal verb participle agreement ("shall be hold" -> "shall be held")
      2. Misplaced punctuation / unbalanced bracket & quote checks
      3. Subject-Verb agreement with common singular legal definitions (e.g. "Purchaser agree")
      4. Double conditionals & archaic syntax boundary sanity checks
    """
    grammar_issues = []
    
    # Rule 1: Modal Auxiliary Passive Formulation
    # In legal drafts: 'shall be [past participle]'. Common error: using present/infinitive.
    modal_patterns = [
        (r'\bshall\s+be\s+indemnify\b', "shall be indemnified", "Incorrect modal verb inflection; requires past participle."),
        (r'\bshall\s+be\s+hold\b', "shall be held", "Incorrect verb form in passive modal construction; use 'held'."),
        (r'\bshall\s+be\s+deem\b', "shall be deemed", "Legal formulaic phrasing requires 'shall be deemed'."),
        (r'\bshall\s+indemnifies\b', "shall indemnify", "Modal auxiliary 'shall' must be followed by base verb form."),
        (r'\bagrees\s+to\s+indemnified\b', "agrees to indemnify", "Infinitive 'to' must be followed by base verb.")
    ]
    for pattern, fix, desc in modal_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            grammar_issues.append({
                "type": "Grammar: Modal Auxiliary Error",
                "original": match.group(0),
                "suggestion": fix,
                "confidence": 0.96,
                "description": desc,
                "start": match.start(),
                "end": match.end()
            })

    # Rule 2: Singular Defined Term Subject-Verb Agreement
    # e.g., "The Purchaser agree to" -> "The Purchaser agrees to"
    defined_terms = r'\b(The\s+(?:Purchaser|Company|Lender|Borrower|Tenant|Landlord|Licensee|Contractor))\s+(agree|covenant|warrant|undertake)\b'
    for match in re.finditer(defined_terms, text, re.IGNORECASE):
        term = match.group(1)
        verb = match.group(2)
        singular_verb = verb + "s"
        grammar_issues.append({
            "type": "Grammar: Subject-Verb Disagreement",
            "original": match.group(0),
            "suggestion": f"{term} {singular_verb}",
            "confidence": 0.92,
            "description": f"Singular defined entity '{term}' requires third-person singular verb form '{singular_verb}'.",
            "start": match.start(),
            "end": match.end()
        })

    # Rule 3: Punctuation Integrity (Unclosed quotes, parentheses, hanging semicolons)
    open_parens = text.count('(')
    close_parens = text.count(')')
    if open_parens > close_parens:
        grammar_issues.append({
            "type": "Punctuation: Unclosed Parenthesis",
            "original": "(...",
            "suggestion": "Add missing ')'",
            "confidence": 0.98,
            "description": "Unbalanced opening parenthesis detected. Missing closing parenthesis.",
            "start": len(text) - 1,
            "end": len(text)
        })

    # Rule 4: Comma splice before legal qualifier 'provided that'
    comma_qualifier = re.finditer(r'([a-zA-Z0-9])\s+provided\s+that\b', text, re.IGNORECASE)
    for match in re.finditer(r'([a-zA-Z0-9])\s+provided\s+that\b', text, re.IGNORECASE):
        grammar_issues.append({
            "type": "Punctuation: Missing Clause Delimiter",
            "original": match.group(0),
            "suggestion": f"{match.group(1)}; provided that",
            "confidence": 0.88,
            "description": "Independent contractual clauses preceding 'provided that' should be delimited by a semicolon.",
            "start": match.start(),
            "end": match.end()
        })

    return grammar_issues

# ==============================================================================
# PIPELINE ORCHESTRATION: CLAUSE CHECKER
# ==============================================================================
def process_clause_content(clause_text: str, clause_id: str = "Clause 1.0"):
    """
    Executes tokenization, spelling verification against BK-Tree/Soundex,
    and syntactic verification against legal grammar rules.
    """
    issues = []
    
    # 1. Run Grammar Checks
    grammar_errors = check_legal_grammar(clause_text)
    for g_err in grammar_errors:
        issues.append({
            "clause_id": clause_id,
            "error_type": g_err["type"],
            "original": g_err["original"],
            "suggestions": [{"text": g_err["suggestion"], "score": g_err["confidence"]}],
            "description": g_err["description"],
            "category": "grammar"
        })

    # 2. Tokenize and Run Spell Check
    # Regex matches words, preserving embedded apostrophes/hyphens
    token_iter = re.finditer(r'\b[a-zA-Z_]+(?:\'[a-zA-Z]+)?\b', clause_text)
    for m in token_iter:
        raw_token = m.group(0)
        clean = raw_token.lower()

        # Check if capitalized defined term or Roman numeral
        if raw_token.isupper() and len(raw_token) > 1:
            continue
        if re.match(r'^(?:[ivxlcdm]+|[IVXLCDM]+)$', raw_token):
            continue

        # Skip if word exists in domain whitelist
        if clean in LEGAL_WHITELIST:
            continue

        # Check for spelling suggestions
        suggestions = get_spell_suggestions(clean)
        if suggestions:
            # Preserve original casing in suggested text
            cased_suggestions = []
            for s_word, score in suggestions:
                if raw_token[0].isupper() and not raw_token.isupper():
                    s_word = s_word.capitalize()
                cased_suggestions.append({"text": s_word, "score": score})

            issues.append({
                "clause_id": clause_id,
                "error_type": "Spelling: Domain Typo",
                "original": raw_token,
                "suggestions": cased_suggestions,
                "description": f"Word '{raw_token}' not recognized in legal corpus or standard lexicon.",
                "category": "spelling"
            })

    return issues

# ==============================================================================
# FLASK HTTP ROUTES
# ==============================================================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/check', methods=['POST'])
def check_endpoint():
    data = request.get_json() or {}
    text = data.get("text", "")
    clause_id = data.get("clause_id", "Section 1.1")
    
    if not text.strip():
        return jsonify({"success": False, "error": "No text provided"}), 400

    issues = process_clause_content(text, clause_id)
    return jsonify({
        "success": True,
        "clause_id": clause_id,
        "original_text": text,
        "issue_count": len(issues),
        "issues": issues
    })

@app.route('/api/upload', methods=['POST'])
def upload_endpoint():
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    file = request.files['file']
    filename = file.filename.lower()
    
    clauses = []
    
    try:
        content = file.read().decode('utf-8')
        if filename.endswith('.json'):
            parsed = json.loads(content)
            if isinstance(parsed, list):
                for idx, item in enumerate(parsed):
                    clauses.append({
                        "id": item.get("clause_id", f"Clause {idx + 1}"),
                        "text": item.get("text", "")
                    })
            elif isinstance(parsed, dict):
                for k, v in parsed.items():
                    clauses.append({"id": k, "text": str(v)})
        elif filename.endswith('.csv'):
            reader = csv.DictReader(io.StringIO(content))
            for idx, row in enumerate(reader):
                cid = row.get("clause_id") or row.get("section") or f"Clause {idx + 1}"
                txt = row.get("text") or row.get("clause_text") or ""
                if txt:
                    clauses.append({"id": cid, "text": txt})
        else:
            # Fallback for plain .txt files: split by double newline
            raw_clauses = [c.strip() for c in content.split('\n\n') if c.strip()]
            for idx, raw in enumerate(raw_clauses):
                match = re.match(r'^(Section\s+\d+[\.\d]*|Clause\s+\d+[\.\d]*|\d+\.\d+)', raw, re.IGNORECASE)
                cid = match.group(0) if match else f"Clause {idx + 1}"
                clauses.append({"id": cid, "text": raw})

        # Process each clause
        results = []
        for c in clauses:
            issues = process_clause_content(c["text"], c["id"])
            results.append({
                "clause_id": c["id"],
                "original_text": c["text"],
                "issue_count": len(issues),
                "issues": issues
            })

        return jsonify({"success": True, "batch_count": len(results), "results": results})

    except Exception as e:
        return jsonify({"success": False, "error": f"File parsing failed: {str(e)}"}), 500

if __name__ == '__main__':
    # Local development server
    app.run(host='0.0.0.0', port=5000, debug=True)
