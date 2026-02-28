"""Compute Word Error Rate (WER) on the People's Speech transcriptions."""
import json
from jiwer import wer, cer, process_words

with open("transcriptions.json") as f:
    results = json.load(f)

print("=== Word Error Rate (WER) — People's Speech ===\n")
print(f"{'File':<20} {'WER':>8} {'CER':>8}  Details")
print("-" * 90)

all_refs = []
all_hyps = []

for r in results:
    ref = r["reference"]
    hyp = r["voxtral"]

    # Normalize: lowercase, strip
    ref_norm = ref.lower().strip()
    hyp_norm = hyp.lower().strip()

    sample_wer = wer(ref_norm, hyp_norm)
    sample_cer = cer(ref_norm, hyp_norm)

    # Get detailed alignment
    detail = process_words(ref_norm, hyp_norm)
    n_ref = len(ref_norm.split())
    hits = detail.hits
    subs = detail.substitutions
    dels = detail.deletions
    ins = detail.insertions

    print(f"{r['file']:<20} {sample_wer:>7.1%} {sample_cer:>7.1%}  "
          f"H={hits} S={subs} D={dels} I={ins} (ref={n_ref} words)")

    all_refs.append(ref_norm)
    all_hyps.append(hyp_norm)

# Overall WER across all samples
overall_wer = wer(all_refs, all_hyps)
overall_cer = cer(all_refs, all_hyps)
overall_detail = process_words(all_refs, all_hyps)

print("-" * 90)
print(f"{'OVERALL':<20} {overall_wer:>7.1%} {overall_cer:>7.1%}  "
      f"H={overall_detail.hits} S={overall_detail.substitutions} "
      f"D={overall_detail.deletions} I={overall_detail.insertions}")
print(f"\nWER = (S + D + I) / N = "
      f"({overall_detail.substitutions} + {overall_detail.deletions} + {overall_detail.insertions}) "
      f"/ {overall_detail.hits + overall_detail.substitutions + overall_detail.deletions}")
