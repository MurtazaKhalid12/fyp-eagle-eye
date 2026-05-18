import os
import shutil
from pathlib import Path

# Paths
SKETCHBOARD = Path(__file__).resolve().parent.parent
ESP_DATASET = SKETCHBOARD / "dataset"
MIT_DATASET = SKETCHBOARD / "mit_dataset" / "dataset"
MERGED_DATASET = SKETCHBOARD / "mit_dataset" / "merged_dataset"

def merge_folders():
    # Create the merged directory
    if MERGED_DATASET.exists():
        print(f"Warning: {MERGED_DATASET} already exists. Cleaning it first...")
        shutil.rmtree(MERGED_DATASET)
    
    os.makedirs(MERGED_DATASET / "Humans", exist_ok=True)
    os.makedirs(MERGED_DATASET / "NonHuman", exist_ok=True)

    copied_count = 0

    # 1. Copy ESP Dataset
    print(f"Copying ESP dataset from {ESP_DATASET}...")
    for class_name in ["Humans", "NonHuman"]:
        src_dir = ESP_DATASET / class_name
        dest_dir = MERGED_DATASET / class_name
        if src_dir.exists():
            for file in os.listdir(src_dir):
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    # Prefix with 'esp_' to avoid name collisions
                    shutil.copy2(src_dir / file, dest_dir / f"esp_{file}")
                    copied_count += 1
    
    # 2. Copy MIT Dataset
    print(f"Copying MIT dataset from {MIT_DATASET}...")
    for class_name in ["Humans", "NonHuman"]:
        src_dir = MIT_DATASET / class_name
        dest_dir = MERGED_DATASET / class_name
        if src_dir.exists():
            for file in os.listdir(src_dir):
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    shutil.copy2(src_dir / file, dest_dir / file)
                    copied_count += 1

    print(f"\nDone! Successfully merged {copied_count} total images into {MERGED_DATASET}.")
    print("Your original datasets were not modified.")

if __name__ == "__main__":
    merge_folders()
