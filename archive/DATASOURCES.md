# Audio & Speech Datasets for Transcription and Diarization

## Datasets Used in This Project

### 1. MLCommons/peoples_speech (Transcription)
- **URL**: https://huggingface.co/datasets/MLCommons/peoples_speech
- **Purpose**: Transcription quality evaluation (WER)
- **Language**: English
- **Size**: 30,000+ hours total, 7 configs
- **Config used**: `microset` (336 samples, ~90 MB parquet)
- **Audio format**: FLAC, 16kHz mono
- **Columns**: `id`, `audio`, `duration_ms`, `text`
- **License**: CC-BY / CC-BY-SA
- **Notes**: Sourced from archive.org. Has clean and dirty subsets. We used 10 samples from the microset for WER evaluation.

### 2. diarizers-community/ami (Diarization)
- **URL**: https://huggingface.co/datasets/diarizers-community/ami
- **Purpose**: Diarization quality evaluation (DER)
- **Language**: English
- **Size**: ~100 hours of meetings
- **Configs**: `ihm` (individual headset mic), `sdm` (single distant mic)
- **Config used**: `ihm/test` shard 0 (6 meetings, 295 MB)
- **Columns**: `audio`, `timestamps_start`, `timestamps_end`, `speakers`
- **Speakers per meeting**: 4
- **License**: CC-BY-4.0
- **Notes**: AMI Meeting Corpus — scenario-based business meetings. Each row is a full meeting with speaker annotations. No text transcripts in this version (annotations are speaker labels + timestamps only).

## Other Datasets Found (Not Used)

### 3. facebook/voxpopuli
- **URL**: https://huggingface.co/datasets/facebook/voxpopuli
- **Purpose**: Multi-speaker speech recognition
- **Language**: 16 languages (English included)
- **Size**: Large (test shard ~936 MB for English alone)
- **Columns**: `audio_id`, `language`, `audio`, `raw_text`, `normalized_text`, `gender`, `speaker_id`, `is_gold_transcript`
- **Notes**: European Parliament recordings. Each row is a single-speaker segment (not multi-speaker audio). Good for ASR, less ideal for diarization testing since segments are pre-split by speaker.

### 4. diarizers-community/callhome
- **URL**: https://huggingface.co/datasets/diarizers-community/callhome
- **Purpose**: Speaker diarization benchmark
- **Languages**: English, German, Japanese, Spanish, Mandarin
- **Size**: ~20 hours per language, ~425 MB per parquet shard
- **Speakers per call**: 2
- **Columns**: `audio`, `timestamps_start`, `timestamps_end`, `speakers`
- **Notes**: CALLHOME telephone conversation corpus. 2-speaker phone calls. Average 12.58% overlapped speech. Classic diarization benchmark.

### 5. diarizers-community/voxconverse
- **URL**: https://huggingface.co/datasets/diarizers-community/voxconverse
- **Purpose**: Multi-speaker diarization
- **Language**: English
- **Size**: 7.3 GB total, 448 clips
- **Splits**: dev (216), test (232)
- **Columns**: `audio`, `timestamps_start`, `timestamps_end`, `speakers`
- **Notes**: Multi-speaker clips from YouTube videos. Variable number of speakers. Preprocessed for pyannote compatibility.

### 6. KBLab/rixvox (Swedish Parliament)
- **URL**: https://huggingface.co/datasets/KBLab/rixvox
- **Purpose**: Speech recognition with speaker metadata
- **Language**: Swedish
- **Size**: 5,493 hours, 835,044 samples, ~1.2 TB
- **Speakers**: 1,165 unique speakers
- **Columns**: `audio`, `text`, `speaker`, `party`, `gender`, `birth_year`, `electoral_district`, `debatedate`, `start`, `end`, `duration`, `bleu_score`
- **Notes**: Swedish Parliament (Riksdag) debates 2003-2023. Rich speaker metadata. Very large — streaming recommended.

### 7. biglam/hansard_speech (UK Parliament)
- **URL**: https://huggingface.co/datasets/biglam/hansard_speech
- **Purpose**: Speech recognition with speaker metadata
- **Language**: English
- **Columns**: Speaker display name, party, constituency, date
- **Notes**: UK Parliament Hansard records.

### 8. CLAPv2/Europarl-st (European Parliament)
- **URL**: https://huggingface.co/datasets/CLAPv2/Europarl-st
- **Purpose**: Speech translation
- **Language**: Multilingual
- **Columns**: Paired audio-text for speech translation
- **Notes**: European Parliament debates 2008-2012. Designed for speech translation tasks.

### 9. coastalcph/eu_debates (European Parliament)
- **URL**: https://huggingface.co/datasets/coastalcph/eu_debates
- **Purpose**: Parliamentary proceedings analysis
- **Size**: ~87k individual speeches (2009-2023)
- **Columns**: Time-stamped speeches, speaker name, euro-party, speaker role, debate date/title
- **Notes**: Text-focused (not audio). Useful for NLP on parliamentary debates.

## Dataset Collections

### Speaker Diarization Datasets Collection
- **URL**: https://huggingface.co/collections/diarizers-community/speaker-diarization-datasets-66261b8d571552066e003788
- **Contents**: CallHome (5 languages), AMI, VoxConverse, Simsamu (French)
- **Notes**: All preprocessed for compatibility with pyannote segmentation models.

## Summary Table

| Dataset | Task | Language | Speakers | Size | Has Text | Has Speaker Labels |
|---------|------|----------|----------|------|----------|--------------------|
| [peoples_speech](https://huggingface.co/datasets/MLCommons/peoples_speech) | ASR | English | 1 | 90 MB (microset) | Yes | No |
| [ami](https://huggingface.co/datasets/diarizers-community/ami) | Diarization | English | 4/meeting | 295 MB (test shard) | No | Yes |
| [voxpopuli](https://huggingface.co/datasets/facebook/voxpopuli) | ASR | 16 langs | 1/segment | ~936 MB (en test) | Yes | Yes (per segment) |
| [callhome](https://huggingface.co/datasets/diarizers-community/callhome) | Diarization | 5 langs | 2/call | ~425 MB/lang | No | Yes |
| [voxconverse](https://huggingface.co/datasets/diarizers-community/voxconverse) | Diarization | English | Multi | 7.3 GB | No | Yes |
| [rixvox](https://huggingface.co/datasets/KBLab/rixvox) | ASR | Swedish | 1,165 total | 1.2 TB | Yes | Yes |
| [hansard_speech](https://huggingface.co/datasets/biglam/hansard_speech) | ASR | English | Many | — | Yes | Yes |
| [europarl-st](https://huggingface.co/datasets/CLAPv2/Europarl-st) | Translation | Multi | — | — | Yes | — |
| [eu_debates](https://huggingface.co/datasets/coastalcph/eu_debates) | NLP | Multi | Many | ~87k speeches | Yes (text only) | Yes |
| [diarization collection](https://huggingface.co/collections/diarizers-community/speaker-diarization-datasets-66261b8d571552066e003788) | Diarization | Multi | Multi | — | — | Yes |
