import os
import shutil
import random
from pathlib import Path

# Configuration
DOWNLOAD_DIR = r"c:\fyp-eagle-eye\Downloaded_Dataset"
TARGET_DIR = r"c:\fyp-eagle-eye\Human_Detection_Dataset"
MAX_IMAGES_PER_CLASS = 1500  # Limit to keep training fast and balanced

def merge_datasets():
    print("Starting dataset merge...")
    
    # Define source paths (Auto-detect folder names)
    download_path = Path(DOWNLOAD_DIR)
    target_path = Path(TARGET_DIR)
    
    if not download_path.exists():
        print(f"Error: Download directory {DOWNLOAD_DIR} does not exist yet. Please wait for download to finish.")
        return

    # Find human/non-human folders in downloaded data
    # Common variations: '1'/'0', 'Human'/'NonHuman', 'human'/'nonhuman'
    
    src_human = None
    src_non_human = None
    
    for folder in download_path.iterdir():
        if not folder.is_dir(): continue
        name = folder.name.lower()
        if name in ['1', 'human', 'humans']:
            src_human = folder
        elif name in ['0', 'nonhuman', 'non-human', 'background']:
            src_non_human = folder
            
    if not src_human or not src_non_human:
        print(f"Could not automatically identify Human/Non-Human folders in {DOWNLOAD_DIR}.")
        print(f"Found folders: {[f.name for f in download_path.iterdir() if f.is_dir()]}")
        print("Please rename them to 'Human' and 'NonHuman' manually if needed.")
        return

    print(f"Found Human Source: {src_human}")
    print(f"Found Non-Human Source: {src_non_human}")
    
    # Destination Paths
    dest_human = target_path / "Humans"
    dest_non_human = target_path / "NonHuman"
    
    dest_human.mkdir(parents=True, exist_ok=True)
    dest_non_human.mkdir(parents=True, exist_ok=True)
    
    # Move/Copy Files
    copy_files(src_human, dest_human, "Human", MAX_IMAGES_PER_CLASS)
    copy_files(src_non_human, dest_non_human, "Non-Human", MAX_IMAGES_PER_CLASS)
    
    print("\n✅ Merge Complete!")
    print(f"Total Humans in Dataset: {len(list(dest_human.glob('*')))}")
    print(f"Total Non-Humans in Dataset: {len(list(dest_non_human.glob('*')))}")

def copy_files(src, dest, label, max_count):
    files = list(src.glob("*.*"))
    random.shuffle(files) # Shuffle to get random selection
    
    count = 0
    existing_count = len(list(dest.glob("*.*")))
    
    print(f"\nProcessing {label} images...")
    print(f"Source has {len(files)} images.")
    
    for f in files:
        if count >= max_count:
            break
            
        # Create unique filename to avoid overwrites
        new_name = f"downloaded_{label}_{f.name}"
        dest_file = dest / new_name
        
        try:
            shutil.copy2(f, dest_file)
            count += 1
            if count % 100 == 0:
                print(f"Copied {count} images...", end='\r')
        except Exception as e:
            print(f"Error copying {f.name}: {e}")
            
    print(f"Added {count} images to {dest}.")

if __name__ == "__main__":
    merge_datasets()
