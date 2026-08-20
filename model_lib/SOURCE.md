# Models Source Baseline

This directory contains third-party model implementations derived from ByteDance's open-source projects. All files retain original copyright notices and are licensed under Apache-2.0 per upstream terms.

## Upstream Sources

### NaDiT (Native Resolution Diffusion Transformer)

- **Upstream**: Bytedance SeedVR2 / NaDiT
- **Repository**: https://github.com/Bytedance/SeedVR2 (official, may be private or archived)
- **License**: Apache-2.0 (Copyright 2025 Bytedance Ltd. and/or its affiliates)
- **Vendored Files**: `model_lib/dit/*`

**File Mapping**:
```
model_lib/dit/
├── __init__.py          # Re-exports get_block, NaDiT, NaDiTConfig
├── attention.py         # Attention mechanisms (torch normal + FA2 varlen)
├── embedding.py         # Timestep embeddings
├── mlp.py               # Feedforward networks
├── mm.py                # Multimodal wrapper (video/text dual-branch)
├── modulation.py        # AdaLN-Zero adaptive modulation
├── normalization.py     # Norm factory (LayerNorm, RMSNorm, FusedNorm)
├── patch.py             # 3D Patch embedder/decoder
├── rope.py              # 3D RoPE positional encoding
├── window.py            # Spatiotemporal window partitioning
├── na.py                # Variable-length sequence tools
├── nadit.py             # NaDiT main model definition
├── blocks/              # Standard DiT transformer blocks
└── nablocks/            # NaDiT transformer blocks
```

**Modifications**: Implementation adapted for SeedVR2-specific configurations (window size, latent dimension). Original architecture preserved.

---

### Stable Diffusion 3 Video VAE (Causal Video AutoencoderKL)

- **Upstream**: Stability AI / ByteDance SD3 VAE
- **License**: Apache-2.0 (Copyright 2023 HuggingFace Team; Copyright 2025 ByteDance Ltd.)
- **Vendored Files**: `model_lib/video_vae_v3/*`

**Purpose**: Causal 3D Video Autoencoder for temporal video compression/decompression in the SeedVR2 pipeline. Supports tiled decoding for memory efficiency.

---

### DiT v2 (Optional Extension)

- **Status**: Future extension placeholder for additional DiT variants
- **Note**: Not yet implemented; directory reserved for potential extensions

---

## Weight Download Strategy

Model weights (not source code) are downloaded separately via `scripts/download_model.py`:

```bash
# Download 3B model + VAE + text embeddings
python scripts/download_model.py --size 3b

# Download 7B or 7B-Sharp
python scripts/download_model.py --size 7b
python scripts/download_model.py --size 7b_sharp
```

Weights come from HuggingFace repository `Reserendipity/SeedVR2` or mirrors. See `NOTICE` file for full attribution.

## Compliance Checklist

When distributing this project:

- [ ] Include `NOTICE` file with all third-party attributions
- [ ] Preserve copyright headers in `model_lib/dit/*` and `model_lib/video_vae_v3/*`
- [ ] Provide link to upstream repositories where possible
- [ ] Ensure downstream users know weight licenses are separate from code license

## Version Tracking

To track changes in upstream model implementations:

1. Periodically check if new commits exist at upstream repos (if accessible)
2. Review `docs/repo-analysis/` for technical reports on similar models
3. Document any modifications made to adapt model APIs to local pipeline

---

*Last updated*: 2026-08-17  
*Baseline commit*: Not tracked locally (source extracted from official release package)
