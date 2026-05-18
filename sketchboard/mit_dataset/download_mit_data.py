import os
from datasets import load_dataset
from PIL import Image
from tqdm import tqdm

OUTPUT_DIR = r"c:\fyp-eagle-eye\sketchboard\mit_dataset\dataset"
DATASET_NAME = "Harvard-Edge/Wake-Vision"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(OUTPUT_DIR, "Humans"), exist_ok=True)
os.makedirs(os.path.join(OUTPUT_DIR, "NonHuman"), exist_ok=True)

print(f"Streaming dataset: {DATASET_NAME} (validation split)...")

# Use streaming to avoid downloading the massive 340GB dataset
try:
    ds = load_dataset(DATASET_NAME, split="validation", streaming=True)
except Exception as e:
    print(f"Error loading dataset: {e}")
    exit(1)

print(f"Saving 5000 images to {OUTPUT_DIR}...")

humans_count = 0
nonhumans_count = 0
target_per_class = 2500

for item in ds:
    # Stop if we have enough of both classes
    if humans_count >= target_per_class and nonhumans_count >= target_per_class:
        break
        
    try:
        image = item['image']
        label = item['person'] # 1 is person, 0 is no person
        
        # Balance classes
        if label == 1:
            if humans_count >= target_per_class: continue
            class_name = "Humans"
            humans_count += 1
            filename = f"human_{humans_count}.jpg"
        else:
            if nonhumans_count >= target_per_class: continue
            class_name = "NonHuman"
            nonhumans_count += 1
            filename = f"nonhuman_{nonhumans_count}.jpg"
            
        target_dir = os.path.join(OUTPUT_DIR, class_name)
        
        # Save image
        if image.mode != "RGB":
            image = image.convert("RGB")
            
        # Resize to 96x96 to save disk space and be more than enough for 48x48 training
        image = image.resize((96, 96))
        
        image.save(os.path.join(target_dir, filename))
        
        total_saved = humans_count + nonhumans_count
        if total_saved % 500 == 0:
            print(f"Saved {total_saved}/5000 images...")
            
    except Exception as e:
        # Ignore broken images
        pass

print(f"\nDownload Completed.")
print(f"Humans: {humans_count}, NonHuman: {nonhumans_count}")
print(f"Images saved in {OUTPUT_DIR}")
