"""Test the custom transcription service and compare with Voxtral API."""
import json
import time
import requests
from jiwer import wer, cer, process_words
import re

SERVICE_URL = "https://tan.tail2e1adb.ts.net/api/transcribe"

def normalize_text(t):
    t = t.lower().strip()
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

# Load existing Voxtral results
with open("transcriptions.json") as f:
    voxtral_results = json.load(f)

print("=" * 80)
print("Comparing: Your Service vs Voxtral API (People's Speech)")
print("=" * 80)
print()

service_refs_norm, service_hyps_norm = [], []
voxtral_refs_norm, voxtral_hyps_norm = [], []

print(f"{'File':<20} {'Svc WER':>8} {'Vox WER':>8}  Service Output")
print("-" * 80)

for r in voxtral_results:
    filepath = f"audio_samples/{r['file']}"

    t0 = time.time()
    with open(filepath, "rb") as f:
        resp = requests.post(SERVICE_URL, files={"audio": f})
    elapsed = time.time() - t0

    service_text = resp.json()["text"]

    ref_norm = normalize_text(r["reference"])
    svc_norm = normalize_text(service_text)
    vox_norm = normalize_text(r["voxtral"])

    svc_wer = wer(ref_norm, svc_norm)
    vox_wer = wer(ref_norm, vox_norm)

    service_refs_norm.append(ref_norm)
    service_hyps_norm.append(svc_norm)
    voxtral_refs_norm.append(ref_norm)
    voxtral_hyps_norm.append(vox_norm)

    winner = "<" if svc_wer < vox_wer else ">" if svc_wer > vox_wer else "="
    print(f"{r['file']:<20} {svc_wer:>7.1%} {vox_wer:>7.1%} {winner} {service_text[:50]}")

svc_overall = wer(service_refs_norm, service_hyps_norm)
vox_overall = wer(voxtral_refs_norm, voxtral_hyps_norm)
svc_cer = cer(service_refs_norm, service_hyps_norm)
vox_cer = cer(voxtral_refs_norm, voxtral_hyps_norm)

print("-" * 80)
print(f"{'OVERALL':<20} {svc_overall:>7.1%} {vox_overall:>7.1%}")
print()
print(f"{'Metric':<25} {'Your Service':>15} {'Voxtral API':>15}")
print("-" * 55)
print(f"{'WER (normalized)':<25} {svc_overall:>14.1%} {vox_overall:>14.1%}")
print(f"{'CER (normalized)':<25} {svc_cer:>14.1%} {vox_cer:>14.1%}")
