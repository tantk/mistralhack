"""Compute WER with text normalization — handles number formats, punctuation, etc."""
import json
import re
from jiwer import wer, cer, process_words

# Number word to digit mapping
WORD_TO_NUM = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
    "million": "1000000",
}

def normalize_text(text):
    """Normalize text for fair WER comparison."""
    t = text.lower().strip()
    # Remove punctuation
    t = re.sub(r'[^\w\s]', '', t)
    # Collapse whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    # Normalize common number words to digits
    # Handle compound numbers like "twenty one" -> "21"
    # First, replace "point X" with "0.X"
    t = re.sub(r'\bpoint\s+(\w+)', lambda m: f"0.{WORD_TO_NUM.get(m.group(1), m.group(1))}", t)
    # Replace standalone number words
    words = t.split()
    normalized = []
    i = 0
    while i < len(words):
        word = words[i]
        if word in WORD_TO_NUM:
            # Accumulate number words
            num_parts = []
            while i < len(words) and words[i] in WORD_TO_NUM:
                num_parts.append(words[i])
                i += 1
            # Simple conversion for common patterns
            normalized.append(convert_number_words(num_parts))
        else:
            normalized.append(word)
            i += 1
    return ' '.join(normalized)

def convert_number_words(parts):
    """Convert a list of number words to a digit string."""
    if not parts:
        return ""
    # Simple approach: evaluate the number
    total = 0
    current = 0
    for p in parts:
        val = int(WORD_TO_NUM[p])
        if val == 100:
            current = (current if current else 1) * 100
        elif val == 1000:
            current = (current if current else 1) * 1000
            total += current
            current = 0
        elif val == 1000000:
            current = (current if current else 1) * 1000000
            total += current
            current = 0
        elif val >= 10 and val <= 90 and val % 10 == 0:
            current += val
        else:
            current += val
    total += current
    return str(total)

with open("transcriptions.json") as f:
    results = json.load(f)

print("=== WER with Text Normalization — People's Speech ===\n")
print(f"{'File':<20} {'Raw WER':>8} {'Norm WER':>9} {'Norm CER':>9}")
print("-" * 55)

all_refs_raw = []
all_hyps_raw = []
all_refs_norm = []
all_hyps_norm = []

for r in results:
    ref_raw = r["reference"].lower().strip()
    hyp_raw = r["voxtral"].lower().strip()
    ref_norm = normalize_text(r["reference"])
    hyp_norm = normalize_text(r["voxtral"])

    raw_wer = wer(ref_raw, hyp_raw)
    norm_wer = wer(ref_norm, hyp_norm)
    norm_cer_val = cer(ref_norm, hyp_norm)

    print(f"{r['file']:<20} {raw_wer:>7.1%} {norm_wer:>8.1%} {norm_cer_val:>8.1%}")

    all_refs_raw.append(ref_raw)
    all_hyps_raw.append(hyp_raw)
    all_refs_norm.append(ref_norm)
    all_hyps_norm.append(hyp_norm)

raw_overall = wer(all_refs_raw, all_hyps_raw)
norm_overall = wer(all_refs_norm, all_hyps_norm)
norm_cer_overall = cer(all_refs_norm, all_hyps_norm)

print("-" * 55)
print(f"{'OVERALL':<20} {raw_overall:>7.1%} {norm_overall:>8.1%} {norm_cer_overall:>8.1%}")
print(f"\nImprovement: {raw_overall:.1%} -> {norm_overall:.1%} "
      f"({(raw_overall - norm_overall) / raw_overall * 100:.0f}% reduction in WER)")

# Show some normalization examples
print("\nNormalization examples:")
for r in results[:3]:
    ref_norm = normalize_text(r["reference"])
    hyp_norm = normalize_text(r["voxtral"])
    print(f"\n  Ref raw:  {r['reference'][:80]}")
    print(f"  Ref norm: {ref_norm[:80]}")
    print(f"  Hyp norm: {hyp_norm[:80]}")
