import numpy as np
from gpu_service.config import (
    EMBEDDING_BACKEND,
    SPEECHBRAIN_MODEL,
    SPEECHBRAIN_CACHE,
    FUNASR_MODEL,
)

_extractor = None


def _load_speechbrain():
    from speechbrain.inference.speaker import SpeakerRecognition
    return ("speechbrain", SpeakerRecognition.from_hparams(
        source=SPEECHBRAIN_MODEL,
        savedir=SPEECHBRAIN_CACHE,
    ))


def _load_funasr():
    from funasr import AutoModel
    return ("funasr", AutoModel(model=FUNASR_MODEL))


def get_extractor():
    global _extractor
    if _extractor is None:
        if EMBEDDING_BACKEND == "funasr":
            _extractor = _load_funasr()
        else:
            _extractor = _load_speechbrain()
    return _extractor


def extract_embedding(audio_16k: np.ndarray) -> np.ndarray:
    """
    Extract a 192-d L2-normalized speaker embedding from 16 kHz mono audio.
    """
    backend, model = get_extractor()

    if backend == "funasr":
        result = model.generate(input=audio_16k, output_dir=None)
        raw_emb = result[0]["spk_embedding"]
        # FunASR may return a GPU tensor — move to CPU before numpy conversion
        if hasattr(raw_emb, "cpu"):
            raw_emb = raw_emb.cpu().numpy()
        emb = np.array(raw_emb).flatten()
    else:
        import torch
        waveform = torch.from_numpy(audio_16k).unsqueeze(0).float()
        emb = model.encode_batch(waveform).squeeze().detach().cpu().numpy()

    # L2 normalize
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return emb
