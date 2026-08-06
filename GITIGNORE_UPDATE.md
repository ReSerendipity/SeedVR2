GITIGNORE update recommendation for ReSerendipity/seedvr2

The repository's .gitignore already includes many standard rules. Below are recommended snippets to ensure runtime artifacts and model weights are ignored.

Suggested additions (append to .gitignore if not present):

# model weights
*.safetensors
*.pth
*.ckpt
*.bin
*.onnx
*.gguf

# outputs / audio
outputs/
*.wav
*.mp3
*.flac

# runtime / logs
logs/
log.txt
data/*.db
*.db
.env
.env.*

# virtualenv / bundled env
WPy64-*/
python/

Instructions:
1) To apply locally, run:
   git checkout -b fix/update-gitignore
   # append the snippet to .gitignore (or edit as desired)
   git add .gitignore
   git commit -m "chore: augment .gitignore to ignore runtime and model artifacts"
   git push origin HEAD

2) Open a PR to merge.
