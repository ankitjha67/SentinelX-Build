#!/usr/bin/env bash
# Sentinel-X Project Setup
# Run this ONCE after cloning the repository.
set -e

echo "═══════════════════════════════════════════"
echo "  Sentinel-X — Project Setup"
echo "═══════════════════════════════════════════"

# 1. Clone camerax_provider (required for camera to work on Android)
if [ ! -d "camerax_provider" ]; then
    echo ""
    echo "[1/4] Cloning camerax_provider (Android CameraX bindings)..."
    git clone https://github.com/Android-for-Python/camerax_provider.git
    rm -rf camerax_provider/.git
    echo "  ✅ camerax_provider installed"
else
    echo "[1/4] camerax_provider already exists ✅"
fi

# 2. Verify critical file
if [ ! -f "camerax_provider/gradle_options.py" ]; then
    echo "  ❌ ERROR: camerax_provider/gradle_options.py not found!"
    echo "  Camera will NOT work without this file."
    exit 1
fi
echo "[2/4] gradle_options.py verified ✅"

# 3. Create directories
mkdir -p evidence models
echo "[3/4] Directories created ✅"

# 4. Verify structure
echo "[4/4] Verifying project structure..."
MISSING=0
for f in main.py service.py buildozer.spec camerax_provider/gradle_options.py; do
    if [ ! -f "$f" ]; then
        echo "  ❌ MISSING: $f"
        MISSING=1
    fi
done

if [ $MISSING -eq 0 ]; then
    echo ""
    echo "═══════════════════════════════════════════"
    echo "  ✅ Setup complete! Ready to build."
    echo ""
    echo "  Next steps:"
    echo "    1. pip install pytest && python -m pytest tests/ -v"
    echo "    2. pip install buildozer"
    echo "    3. buildozer -v android debug"
    echo "    4. adb install -r bin/*.apk"
    echo "═══════════════════════════════════════════"
else
    echo ""
    echo "  ❌ Setup incomplete. Fix missing files above."
    exit 1
fi
