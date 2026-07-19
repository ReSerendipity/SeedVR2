# SeedVR2 - Project Constraints

## Hard Constraints
- Application must run independently without ComfyUI environment
- **SeedVR2 model only supports NVIDIA CUDA GPU. CPU inference is NOT supported.**
- Development environment must use WinPython as the base runtime
- All batch files must use pure ASCII English to avoid encoding issues in Windows cmd.exe
- Model loading must strictly follow workflow parameters to prevent memory overflow
- If memory exceeds 90%, immediately terminate the model
- I/O components (embeddings, norms, etc.) must remain on GPU and not be offloaded to CPU RAM
- WebUI settings must exactly match workflow parameters, with each settings section corresponding to a ComfyUI node
- Default parameters (model, resolution, tile size, etc.) in WebUI must match workflow defaults
- Resolution must be set to 2160 in both WebUI and workflow JSON

## Engineering Conventions
- 3B model uses models.dit_v2.nadit architecture with num_layers=32, vid_dim=2560, mlp_type=swiglu
- 7B model uses models.dit.nadit architecture with num_layers=36, vid_dim=3072, mlp_type=normal
- window_method list in config must be automatically expanded to match num_layers length
- Web server uses native jinja2.Environment for template rendering instead of Starlette's Jinja2Templates
- Model loading must include memory pre-check: available memory >= 1.5 times model size
- Memory monitoring must include pre-load check and post-inference release

## Lessons Learned
- Starlette 1.0.0 has compatibility issues with Jinja2 3.1.6 template caching mechanism
- BlockSwap's _protect_model_from_move prevents model.to("cpu") execution, causing VRAM leaks after DiT inference
- swap_io_components=true in config.yaml causes memory overflow by offloading I/O components to CPU RAM
