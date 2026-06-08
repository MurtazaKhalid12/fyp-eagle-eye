import os
import random
import shutil
from PIL import Image

# --- CONFIGURATION ---
SRC_HUMANS = r"c:\fyp-eagle-eye\sketchboard\dataset\Humans"
SRC_NON_HUMANS = r"c:\fyp-eagle-eye\sketchboard\dataset\NonHuman"

DEST_DIR = r"c:\fyp-eagle-eye\sketchboard\local_mobilenet_v1\dataset"
DEST_HUMANS = os.path.join(DEST_DIR, "Humans")
DEST_NON_HUMANS = os.path.join(DEST_DIR, "NonHuman")

SEED = 42
IMG_SIZE = (96, 96)

def main():
    print("=== EagleEye Local MobileNetV1 Grayscale 96x96 Dataset Prep ===")
    
    # 1. Clean destination directories
    if os.path.exists(DEST_DIR):
        print(f"Cleaning existing dataset folder: {DEST_DIR}")
        shutil.rmtree(DEST_DIR)
        
    os.makedirs(DEST_HUMANS, exist_ok=True)
    os.makedirs(DEST_NON_HUMANS, exist_ok=True)
    
    # 2. Get all human images
    human_files = [f for f in os.listdir(SRC_HUMANS) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    human_count = len(human_files)
    print(f"Found {human_count} human images. We will use ALL of them.")
    
    # 3. Get all non-human images and sample exactly human_count
    non_human_files = [f for f in os.listdir(SRC_NON_HUMANS) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    print(f"Found {len(non_human_files)} non-human images. Sampling exactly {human_count} for balance.")
    
    random.seed(SEED)
    selected_non_human_files = random.sample(non_human_files, human_count)
    
    # 4. Process Humans
    print("Processing Humans (Grayscale, 96x96)...")
    success_humans = 0
    for filename in human_files:
        src_path = os.path.join(SRC_HUMANS, filename)
        dest_path = os.path.join(DEST_HUMANS, filename)
        try:
            with Image.open(src_path) as img:
                # Convert to Grayscale ('L')
                gray_img = img.convert('L')
                resized_img = gray_img.resize(IMG_SIZE, Image.Resampling.LANCZOS)
                resized_img.save(dest_path, "JPEG", quality=95)
                success_humans += 1
        except Exception as e:
            print(f"Failed to process human {filename}: {e}")
            
    # 5. Process Non-Humans
    print("Processing Non-Humans (Grayscale, 96x96)...")
    success_non_humans = 0
    for filename in selected_non_human_files:
        src_path = os.path.join(SRC_NON_HUMANS, filename)
        dest_path = os.path.join(DEST_NON_HUMANS, filename)
        try:
            with Image.open(src_path) as img:
                gray_img = img.convert('L')
                resized_img = gray_img.resize(IMG_SIZE, Image.Resampling.LANCZOS)
                resized_img.save(dest_path, "JPEG", quality=95)
                success_non_humans += 1
        except Exception as e:
            print(f"Failed to process non-human {filename}: {e}")
            
    print(f"\nDataset prep complete:")
    print(f"  Humans: {success_humans} images saved to {DEST_HUMANS}")
    print(f"  Non-Humans: {success_non_humans} images saved to {DEST_NON_HUMANS}")

if __name__ == "__main__":
    main()
