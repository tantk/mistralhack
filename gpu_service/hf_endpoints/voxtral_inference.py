"""
Voxtral Realtime 4B inference engine.

Loads directly from Mistral-format consolidated.safetensors — no transformers
dependency. Adapted from voxtral.c/python_simple_implementation.py with CUDA
and FP16 support for T4 GPUs.
"""

import json
import math
import os
import base64
from typing import Iterator

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from safetensors import safe_open

# ============================================================================
# Config (from params.json)
# ============================================================================

# Encoder
ENC_DIM = 1280
ENC_LAYERS = 32
ENC_HEADS = 32
ENC_HEAD_DIM = 64
ENC_HIDDEN = 5120
ENC_KV_HEADS = 32
ENC_WINDOW = 750
ENC_NORM_EPS = 1e-5
ENC_ROPE_THETA = 1_000_000.0

# Decoder
DEC_DIM = 3072
DEC_LAYERS = 26
DEC_HEADS = 32
DEC_HEAD_DIM = 128
DEC_HIDDEN = 9216
DEC_KV_HEADS = 8
DEC_WINDOW = 8192
DEC_NORM_EPS = 1e-5
DEC_ROPE_THETA = 1_000_000.0
VOCAB_SIZE = 131072

# Audio
SAMPLE_RATE = 16000
FRAME_RATE = 12.5
NUM_MEL_BINS = 128
HOP_LENGTH = 160
WINDOW_SIZE = 400
GLOBAL_LOG_MEL_MAX = 1.5
DOWNSAMPLE_FACTOR = 4

# Ada norm
ADA_NORM_DIM = 32

# Streaming
N_LEFT_PAD_TOKENS = 32
TRANSCRIPTION_DELAY_MS = 480

# Special tokens
TOKEN_BOS = 1
TOKEN_EOS = 2
TOKEN_STREAMING_PAD = 32
TOKEN_BEGIN_AUDIO = 25
TOKEN_AUDIO = 24

# Derived constants
RAW_AUDIO_LENGTH_PER_TOK = int(SAMPLE_RATE // FRAME_RATE)  # 1280
AUDIO_LENGTH_PER_TOK = RAW_AUDIO_LENGTH_PER_TOK // HOP_LENGTH  # 8


def _num_delay_tokens():
    delay_len = int(TRANSCRIPTION_DELAY_MS / 1000.0 * SAMPLE_RATE)
    n = delay_len
    if n % HOP_LENGTH != 0:
        n = math.ceil(n / HOP_LENGTH - 1)
    else:
        n = n // HOP_LENGTH
    return math.ceil(n / AUDIO_LENGTH_PER_TOK)


N_DELAY_TOKENS = _num_delay_tokens()
N_RIGHT_PAD_TOKENS = (N_DELAY_TOKENS + 1) + 10  # 17

# ============================================================================
# Mel filter bank
# ============================================================================


def _hertz_to_mel(freq):
    min_log_hertz = 1000.0
    min_log_mel = 15.0
    logstep = 27.0 / np.log(6.4)
    mels = 3.0 * freq / 200.0
    if isinstance(freq, np.ndarray):
        log_region = freq >= min_log_hertz
        mels[log_region] = min_log_mel + np.log(freq[log_region] / min_log_hertz) * logstep
    elif freq >= min_log_hertz:
        mels = min_log_mel + np.log(freq / min_log_hertz) * logstep
    return mels


def _mel_to_hertz(mels):
    min_log_hertz = 1000.0
    min_log_mel = 15.0
    logstep = np.log(6.4) / 27.0
    freq = 200.0 * mels / 3.0
    log_region = mels >= min_log_mel
    freq[log_region] = min_log_hertz * np.exp(logstep * (mels[log_region] - min_log_mel))
    return freq


def _compute_mel_filters():
    num_frequency_bins = 1 + WINDOW_SIZE // 2  # 201
    fft_freqs = np.linspace(0, SAMPLE_RATE // 2, num_frequency_bins)
    mel_min = _hertz_to_mel(0.0)
    mel_max = _hertz_to_mel(8000.0)
    mel_freqs = np.linspace(mel_min, mel_max, NUM_MEL_BINS + 2)
    filter_freqs = _mel_to_hertz(mel_freqs)
    filter_diff = np.diff(filter_freqs)
    slopes = np.expand_dims(filter_freqs, 0) - np.expand_dims(fft_freqs, 1)
    down_slopes = -slopes[:, :-2] / filter_diff[:-1]
    up_slopes = slopes[:, 2:] / filter_diff[1:]
    fb = np.maximum(np.zeros(1), np.minimum(down_slopes, up_slopes))
    enorm = 2.0 / (filter_freqs[2:NUM_MEL_BINS + 2] - filter_freqs[:NUM_MEL_BINS])
    fb *= np.expand_dims(enorm, 0)
    return fb  # [201, 128]


# ============================================================================
# Mel spectrogram
# ============================================================================


def _compute_mel_spectrogram(audio, mel_filters, device):
    """audio: 1D tensor on device, mel_filters: [freq_bins, mel_bins] on device."""
    window = torch.hann_window(WINDOW_SIZE, device=device)
    stft = torch.stft(audio, WINDOW_SIZE, HOP_LENGTH, window=window, return_complex=True)
    magnitudes = stft[..., :-1].abs() ** 2
    mel_spec = mel_filters.T @ magnitudes
    log_spec = torch.clamp(mel_spec, min=1e-10).log10()
    log_spec = torch.maximum(log_spec, torch.tensor(GLOBAL_LOG_MEL_MAX, device=device) - 8.0)
    log_spec = (log_spec + 4.0) / 4.0
    return log_spec  # [128, frames]


# ============================================================================
# Audio streaming padding
# ============================================================================


def _pad_audio_streaming(audio_array):
    mult_of = RAW_AUDIO_LENGTH_PER_TOK
    n_samples = len(audio_array)
    align_pad = (mult_of - (n_samples % mult_of)) % mult_of
    right_pad = align_pad + N_RIGHT_PAD_TOKENS * mult_of
    left_pad = N_LEFT_PAD_TOKENS * mult_of
    return np.pad(audio_array, (left_pad, right_pad))


# ============================================================================
# Weight loading helpers
# ============================================================================


def _get_weight(sf_file, name, device, dtype=None):
    t = sf_file.get_tensor(name)
    if t.dtype == torch.bfloat16:
        t = t.float()
    t = t.to(device)
    if dtype is not None:
        t = t.to(dtype)
    return t


def _get_weight_optional(sf_file, name, device, dtype=None):
    try:
        return _get_weight(sf_file, name, device, dtype)
    except Exception:
        return None


def _permute_qk_weight(w, n_heads, head_dim):
    attn_in = n_heads * head_dim
    attn_out = w.shape[1]
    return (
        w.view(n_heads, head_dim // 2, 2, attn_out)
        .transpose(1, 2)
        .reshape(attn_in, attn_out)
    )


def _permute_qk_bias(b, n_heads, head_dim):
    attn_in = n_heads * head_dim
    return (
        b.view(n_heads, head_dim // 2, 2)
        .transpose(1, 2)
        .reshape(attn_in)
    )


# ============================================================================
# RMSNorm
# ============================================================================


class _RMSNorm(nn.Module):
    def __init__(self, weight, eps=1e-5):
        super().__init__()
        self.weight = weight
        self.eps = eps

    def forward(self, x):
        rms = torch.rsqrt(x.float().pow(2).mean(-1, keepdim=True) + self.eps)
        return (x.float() * rms * self.weight.float()).to(x.dtype)


# ============================================================================
# RoPE
# ============================================================================


def _compute_rope_freqs(positions, head_dim, theta, device):
    freqs = 1.0 / (theta ** (torch.arange(0, head_dim, 2, device=device).float() / head_dim))
    angles = positions.float().unsqueeze(-1) * freqs.unsqueeze(0)
    return torch.cos(angles), torch.sin(angles)


def _apply_rope(x, cos_f, sin_f, n_heads, head_dim, is_neox_style=False):
    seq_len = x.shape[0]
    x = x.view(seq_len, n_heads, head_dim)
    cos_f = cos_f.unsqueeze(1)
    sin_f = sin_f.unsqueeze(1)

    if is_neox_style:
        x1, x2 = x.chunk(2, dim=-1)
        o1 = x1 * cos_f - x2 * sin_f
        o2 = x2 * cos_f + x1 * sin_f
        out = torch.cat([o1, o2], dim=-1)
    else:
        x1 = x[..., ::2]
        x2 = x[..., 1::2]
        o1 = x1 * cos_f - x2 * sin_f
        o2 = x2 * cos_f + x1 * sin_f
        out = torch.stack([o1, o2], dim=-1).flatten(-2)

    return out.view(seq_len, n_heads * head_dim)


# ============================================================================
# Causal Attention
# ============================================================================


def _causal_attention(q, k, v, n_heads, n_kv_heads, head_dim, window,
                      q_start_pos=0, kv_start_pos=0):
    seq_q = q.shape[0]
    seq_kv = k.shape[0]
    gqa_ratio = n_heads // n_kv_heads
    device = q.device
    orig_dtype = q.dtype

    q = q.view(seq_q, n_heads, head_dim).transpose(0, 1).unsqueeze(0)
    k = k.view(seq_kv, n_kv_heads, head_dim).transpose(0, 1).unsqueeze(0)
    v = v.view(seq_kv, n_kv_heads, head_dim).transpose(0, 1).unsqueeze(0)

    if gqa_ratio > 1:
        k = k.repeat_interleave(gqa_ratio, dim=1)
        v = v.repeat_interleave(gqa_ratio, dim=1)

    qi_abs = (q_start_pos + torch.arange(seq_q, device=device)).unsqueeze(1)
    kv_abs = (kv_start_pos + torch.arange(seq_kv, device=device)).unsqueeze(0)
    attn_mask = (kv_abs <= qi_abs) & (kv_abs >= (qi_abs - (window - 1)))

    out = F.scaled_dot_product_attention(
        q.float(), k.float(), v.float(),
        attn_mask=attn_mask.unsqueeze(0).unsqueeze(0),
        scale=1.0 / math.sqrt(head_dim),
        dropout_p=0.0,
    ).to(orig_dtype)

    return out.squeeze(0).transpose(0, 1).contiguous().view(seq_q, n_heads * head_dim)


# ============================================================================
# Causal Conv1d
# ============================================================================


def _causal_conv1d(x, weight, bias, stride):
    kernel_size = weight.shape[2]
    effective_ks = kernel_size
    padding_total = effective_ks - stride

    n_frames = (x.shape[-1] - effective_ks + padding_total) / stride + 1
    target_length = (math.ceil(n_frames) - 1) * stride + (effective_ks - padding_total)
    extra_padding = int(target_length - x.shape[-1])

    x = F.pad(x, (padding_total, extra_padding), mode='constant')
    return F.conv1d(x, weight, bias, stride=stride)


# ============================================================================
# TimeEmbedding
# ============================================================================


def _compute_time_embedding(t_value, dim, device, theta=10000.0):
    half_dim = dim // 2
    inv_freq = torch.exp(
        -math.log(theta) * torch.arange(half_dim, device=device).float() / half_dim
    )
    emb = t_value * inv_freq
    return torch.cat([emb.cos(), emb.sin()])


# ============================================================================
# Encoder forward
# ============================================================================


def _encoder_forward(mel, sf_file, device, compute_dtype):
    """mel: [128, frames] on device -> [seq, 1280] on device."""
    prefix = "mm_streams_embeddings.embedding_module.whisper_encoder"

    mel_3d = mel.unsqueeze(0)
    conv0_w = _get_weight(sf_file, f"{prefix}.conv_layers.0.conv.weight", device, compute_dtype)
    conv0_b = _get_weight(sf_file, f"{prefix}.conv_layers.0.conv.bias", device, compute_dtype)
    conv1_w = _get_weight(sf_file, f"{prefix}.conv_layers.1.conv.weight", device, compute_dtype)
    conv1_b = _get_weight(sf_file, f"{prefix}.conv_layers.1.conv.bias", device, compute_dtype)

    h = F.gelu(_causal_conv1d(mel_3d.to(compute_dtype), conv0_w, conv0_b, stride=1))
    h = F.gelu(_causal_conv1d(h, conv1_w, conv1_b, stride=2))
    h = h.squeeze(0).transpose(0, 1)  # [seq, 1280]
    conv_len = h.shape[0]

    trunc = conv_len % DOWNSAMPLE_FACTOR
    if trunc > 0:
        h = h[trunc:]
    seq_len = h.shape[0]

    positions = torch.arange(seq_len, device=device)
    rope_cos, rope_sin = _compute_rope_freqs(positions, ENC_HEAD_DIM, ENC_ROPE_THETA, device)

    for layer in range(ENC_LAYERS):
        lp = f"{prefix}.transformer.layers.{layer}"

        attn_norm_w = _get_weight(sf_file, f"{lp}.attention_norm.weight", device)
        norm = _RMSNorm(attn_norm_w, ENC_NORM_EPS)
        x_norm = norm(h).to(compute_dtype)

        wq = _get_weight(sf_file, f"{lp}.attention.wq.weight", device, compute_dtype)
        wq_b = _get_weight(sf_file, f"{lp}.attention.wq.bias", device, compute_dtype)
        wk = _get_weight(sf_file, f"{lp}.attention.wk.weight", device, compute_dtype)
        wv = _get_weight(sf_file, f"{lp}.attention.wv.weight", device, compute_dtype)
        wv_b = _get_weight(sf_file, f"{lp}.attention.wv.bias", device, compute_dtype)
        wo = _get_weight(sf_file, f"{lp}.attention.wo.weight", device, compute_dtype)
        wo_b = _get_weight(sf_file, f"{lp}.attention.wo.bias", device, compute_dtype)

        q = F.linear(x_norm, wq, wq_b)
        k = F.linear(x_norm, wk)
        v = F.linear(x_norm, wv, wv_b)

        q = _apply_rope(q, rope_cos, rope_sin, ENC_HEADS, ENC_HEAD_DIM, is_neox_style=False)
        k = _apply_rope(k, rope_cos, rope_sin, ENC_KV_HEADS, ENC_HEAD_DIM, is_neox_style=False)

        attn_out = _causal_attention(q, k, v, ENC_HEADS, ENC_KV_HEADS, ENC_HEAD_DIM, ENC_WINDOW)

        h = h + F.linear(attn_out, wo, wo_b)

        ffn_norm_w = _get_weight(sf_file, f"{lp}.ffn_norm.weight", device)
        ffn_norm = _RMSNorm(ffn_norm_w, ENC_NORM_EPS)
        x_norm = ffn_norm(h).to(compute_dtype)

        w1 = _get_weight(sf_file, f"{lp}.feed_forward.w1.weight", device, compute_dtype)
        w2 = _get_weight(sf_file, f"{lp}.feed_forward.w2.weight", device, compute_dtype)
        w2_b = _get_weight(sf_file, f"{lp}.feed_forward.w2.bias", device, compute_dtype)
        w3 = _get_weight(sf_file, f"{lp}.feed_forward.w3.weight", device, compute_dtype)

        gate = F.silu(F.linear(x_norm, w1))
        up = F.linear(x_norm, w3)
        h = h + F.linear(gate * up, w2, w2_b)

    final_norm_w = _get_weight(sf_file, f"{prefix}.transformer.norm.weight", device)
    final_norm = _RMSNorm(final_norm_w, ENC_NORM_EPS)
    h = final_norm(h)

    return h  # [seq, 1280]


# ============================================================================
# Adapter forward
# ============================================================================


def _adapter_forward(enc_out, sf_file, device, compute_dtype):
    """enc_out: [seq, 1280] -> [seq/4, 3072]."""
    prefix = "mm_streams_embeddings.embedding_module"
    w0 = _get_weight(sf_file, f"{prefix}.audio_language_projection.0.weight", device, compute_dtype)
    w1 = _get_weight(sf_file, f"{prefix}.audio_language_projection.2.weight", device, compute_dtype)

    seq_len = enc_out.shape[0]
    ds = enc_out.reshape(seq_len // DOWNSAMPLE_FACTOR, ENC_DIM * DOWNSAMPLE_FACTOR)

    out = F.gelu(F.linear(ds.to(compute_dtype), w0))
    out = F.linear(out, w1)

    return out  # [seq/4, 3072]


# ============================================================================
# Decoder
# ============================================================================


class _Decoder:
    def __init__(self, sf_file, device, compute_dtype):
        self.sf = sf_file
        self.device = device
        self.compute_dtype = compute_dtype
        self.tok_embeddings = _get_weight(
            sf_file,
            "mm_streams_embeddings.embedding_module.tok_embeddings.weight",
            device, compute_dtype,
        )
        self.final_norm = _get_weight(sf_file, "norm.weight", device)
        self.kv_cache = {}

        self.layers = []
        for i in range(DEC_LAYERS):
            self.layers.append(self._load_layer(i))

    def _load_layer(self, i):
        sf = self.sf
        lp = f"layers.{i}"
        device = self.device
        dtype = self.compute_dtype

        return {
            'attention_norm': _get_weight(sf, f"{lp}.attention_norm.weight", device),
            'ffn_norm': _get_weight(sf, f"{lp}.ffn_norm.weight", device),
            'wq': _get_weight(sf, f"{lp}.attention.wq.weight", device, dtype),
            'wk': _get_weight(sf, f"{lp}.attention.wk.weight", device, dtype),
            'wv': _get_weight(sf, f"{lp}.attention.wv.weight", device, dtype),
            'wo': _get_weight(sf, f"{lp}.attention.wo.weight", device, dtype),
            'w1': _get_weight(sf, f"{lp}.feed_forward.w1.weight", device, dtype),
            'w2': _get_weight(sf, f"{lp}.feed_forward.w2.weight", device, dtype),
            'w3': _get_weight(sf, f"{lp}.feed_forward.w3.weight", device, dtype),
            'ada_down': _get_weight(sf, f"{lp}.ada_rms_norm_t_cond.0.weight", device, dtype),
            'ada_up': _get_weight(sf, f"{lp}.ada_rms_norm_t_cond.2.weight", device, dtype),
        }

    def embed_token(self, token_id):
        return self.tok_embeddings[token_id]

    def embed_tokens(self, token_ids):
        return self.tok_embeddings[token_ids]

    def _layer_forward(self, h, layer_idx, pos, kv_seq_len, t_cond=None):
        L = self.layers[layer_idx]
        seq_len = h.shape[0]
        dtype = self.compute_dtype
        device = self.device

        if h.dtype != dtype:
            h = h.to(dtype)

        norm = _RMSNorm(L['attention_norm'], DEC_NORM_EPS)
        x_norm = norm(h).to(dtype)

        q = F.linear(x_norm, L['wq'])
        k = F.linear(x_norm, L['wk'])
        v = F.linear(x_norm, L['wv'])

        positions = torch.arange(pos, pos + seq_len, device=device)
        rope_cos, rope_sin = _compute_rope_freqs(positions, DEC_HEAD_DIM, DEC_ROPE_THETA, device)
        q = _apply_rope(q.float(), rope_cos, rope_sin, DEC_HEADS, DEC_HEAD_DIM, is_neox_style=False).to(dtype)
        k = _apply_rope(k.float(), rope_cos, rope_sin, DEC_KV_HEADS, DEC_HEAD_DIM, is_neox_style=False).to(dtype)

        if layer_idx not in self.kv_cache:
            k_cache = k
            v_cache = v
        else:
            k_cache, v_cache = self.kv_cache[layer_idx]
            k_cache = torch.cat([k_cache, k], dim=0)
            v_cache = torch.cat([v_cache, v], dim=0)

        if k_cache.shape[0] > DEC_WINDOW:
            k_cache = k_cache[-DEC_WINDOW:]
            v_cache = v_cache[-DEC_WINDOW:]

        self.kv_cache[layer_idx] = (k_cache, v_cache)
        full_k, full_v = self.kv_cache[layer_idx]

        kv_start_pos = (pos + seq_len - 1) - (full_k.shape[0] - 1)
        attn_out = _causal_attention(
            q, full_k, full_v,
            DEC_HEADS, DEC_KV_HEADS, DEC_HEAD_DIM,
            DEC_WINDOW,
            q_start_pos=pos,
            kv_start_pos=kv_start_pos,
        )

        attn_proj = F.linear(attn_out, L['wo'])
        h = h + attn_proj

        ffn_norm = _RMSNorm(L['ffn_norm'], DEC_NORM_EPS)
        h_norm = ffn_norm(h).to(dtype)

        if t_cond is not None:
            t_cond_dt = t_cond.to(dtype)
            ada_hidden = F.gelu(F.linear(t_cond_dt, L['ada_down']))
            ada_scale = F.linear(ada_hidden, L['ada_up'])
            h_norm = h_norm * (1 + ada_scale.unsqueeze(0))

        gate = F.silu(F.linear(h_norm, L['w1']))
        up = F.linear(h_norm, L['w3'])
        h = h + F.linear(gate * up, L['w2'])

        return h

    def prefill(self, input_embeds, t_cond):
        self.kv_cache = {}
        h = input_embeds.to(self.compute_dtype)
        seq_len = h.shape[0]

        for layer in range(DEC_LAYERS):
            h = self._layer_forward(h, layer, 0, seq_len, t_cond=t_cond)

        return h

    def forward_one(self, embed, pos, t_cond):
        h = embed.unsqueeze(0) if embed.dim() == 1 else embed
        h = h.to(self.compute_dtype)

        for layer in range(DEC_LAYERS):
            h = self._layer_forward(h, layer, pos, pos + 1, t_cond=t_cond)

        norm = _RMSNorm(self.final_norm, DEC_NORM_EPS)
        h = norm(h)

        logits = F.linear(h.float().squeeze(0), self.tok_embeddings.float())
        return logits


# ============================================================================
# Tokenizer
# ============================================================================


def _load_tokenizer(model_dir):
    tekken_path = os.path.join(model_dir, "tekken.json")
    with open(tekken_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    vocab = data["vocab"]
    config = data.get("config", {})
    n_special = int(config.get("default_num_special_tokens", 1000))
    special_ids = {int(st["rank"]) for st in data.get("special_tokens", []) if "rank" in st}

    bytes_cache = {}

    def token_bytes(token_id: int) -> bytes:
        b = bytes_cache.get(token_id)
        if b is not None:
            return b
        if token_id < 0:
            bytes_cache[token_id] = b""
            return b""
        if token_id < n_special or token_id in special_ids:
            bytes_cache[token_id] = b""
            return b""
        vocab_id = token_id - n_special
        if vocab_id < 0 or vocab_id >= len(vocab):
            bytes_cache[token_id] = b""
            return b""
        b = base64.b64decode(vocab[vocab_id]["token_bytes"])
        bytes_cache[token_id] = b
        return b

    def decode(token_ids):
        out = bytearray()
        for token_id in map(int, token_ids):
            if token_id < n_special or token_id in special_ids:
                continue
            out += token_bytes(token_id)
        return out.decode("utf-8", errors="replace")

    return decode


# ============================================================================
# VoxtralModel — singleton inference engine
# ============================================================================


class VoxtralModel:
    """Load Voxtral from Mistral-format safetensors and run inference on CUDA."""

    def __init__(self, model_dir: str):
        self.model_dir = model_dir
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        # FP16 for T4 (no good bf16 support); float32 on CPU
        self.compute_dtype = torch.float16 if self.device.type == "cuda" else torch.float32

        sf_path = os.path.join(model_dir, "consolidated.safetensors")
        self._sf_file = safe_open(sf_path, framework="pt")

        # Precompute mel filters on device
        self._mel_filters = torch.tensor(
            _compute_mel_filters(), dtype=torch.float32, device=self.device
        )

        # Preload decoder (holds all layer weights on GPU)
        self._decoder = _Decoder(self._sf_file, self.device, self.compute_dtype)

        # Load tokenizer
        self._decode = _load_tokenizer(model_dir)

    def _prepare(self, audio_16k: np.ndarray):
        """Audio array -> (adapter_out, prompt_ids, t_cond) all on device."""
        prompt_ids = [TOKEN_BOS] + [TOKEN_STREAMING_PAD] * (N_LEFT_PAD_TOKENS + N_DELAY_TOKENS)
        padded = _pad_audio_streaming(audio_16k).astype(np.float32)

        audio_tensor = torch.tensor(padded, dtype=torch.float32, device=self.device)
        mel = _compute_mel_spectrogram(audio_tensor, self._mel_filters, self.device)

        if mel.shape[1] % 2 != 0:
            mel = mel[:, 1:]

        with torch.no_grad():
            enc_out = _encoder_forward(mel, self._sf_file, self.device, self.compute_dtype)
            adapter_out = _adapter_forward(enc_out, self._sf_file, self.device, self.compute_dtype)

        t_cond = _compute_time_embedding(float(N_DELAY_TOKENS), DEC_DIM, self.device)

        return adapter_out, prompt_ids, t_cond

    def transcribe(self, audio_16k: np.ndarray) -> str:
        """Full pipeline: 16 kHz float32 mono audio -> transcribed text."""
        adapter_out, prompt_ids, t_cond = self._prepare(audio_16k)

        n_audio = adapter_out.shape[0]
        L = len(prompt_ids)

        prompt_ids_t = torch.tensor(prompt_ids, dtype=torch.long, device=self.device)
        prefix_text_embeds = self._decoder.embed_tokens(prompt_ids_t)
        prefix_embeds = adapter_out[:L] + prefix_text_embeds

        with torch.no_grad():
            if L > 1:
                _ = self._decoder.prefill(prefix_embeds[:-1], t_cond)
            logits = self._decoder.forward_one(prefix_embeds[-1], pos=L - 1, t_cond=t_cond)
            token = int(logits.argmax().item())

        generated = [token]

        with torch.no_grad():
            for pos in range(L, n_audio):
                if token == TOKEN_EOS:
                    break
                embed = adapter_out[pos] + self._decoder.embed_token(token)
                logits = self._decoder.forward_one(embed, pos=pos, t_cond=t_cond)
                token = int(logits.argmax().item())
                generated.append(token)

        if generated and generated[-1] == TOKEN_EOS:
            generated = generated[:-1]

        return self._decode(generated).strip()

    def transcribe_stream(self, audio_16k: np.ndarray) -> Iterator[str]:
        """Streaming pipeline: yields decoded text fragments as tokens are generated."""
        adapter_out, prompt_ids, t_cond = self._prepare(audio_16k)

        n_audio = adapter_out.shape[0]
        L = len(prompt_ids)

        prompt_ids_t = torch.tensor(prompt_ids, dtype=torch.long, device=self.device)
        prefix_text_embeds = self._decoder.embed_tokens(prompt_ids_t)
        prefix_embeds = adapter_out[:L] + prefix_text_embeds

        with torch.no_grad():
            if L > 1:
                _ = self._decoder.prefill(prefix_embeds[:-1], t_cond)
            logits = self._decoder.forward_one(prefix_embeds[-1], pos=L - 1, t_cond=t_cond)
            token = int(logits.argmax().item())

        if token != TOKEN_EOS:
            text = self._decode([token])
            if text:
                yield text

        with torch.no_grad():
            for pos in range(L, n_audio):
                if token == TOKEN_EOS:
                    break
                embed = adapter_out[pos] + self._decoder.embed_token(token)
                logits = self._decoder.forward_one(embed, pos=pos, t_cond=t_cond)
                token = int(logits.argmax().item())
                if token != TOKEN_EOS:
                    text = self._decode([token])
                    if text:
                        yield text
