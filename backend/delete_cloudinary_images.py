import cloudinary
import cloudinary.uploader
import cloudinary.api

# Configuration
cloudinary.config( 
  cloud_name = "dsq74osj5", 
  api_key = "454823543384692", 
  api_secret = "UPF9ZrxjhxYrttoVKerx2NeOPes",
  secure = True
)

folder_name = "eagleeye_intrusions"

print(f"Starting deletion of all images in folder '{folder_name}'...")

try:
    # Delete resources by prefix (which covers the folder)
    # Note: The prefix should match how the public_ids are stored, usually "folder/filename"
    result = cloudinary.api.delete_resources_by_prefix(folder_name)
    print("Deletion Result:", result)
    
    # Also attempt to delete the empty folder itself (optional, but clean)
    try:
        cloudinary.api.delete_folder(folder_name)
        print(f"Folder '{folder_name}' deleted.")
    except Exception as e:
        print(f"Note: Could not delete folder (might be non-empty or require different permissions): {e}")

except Exception as e:
    print(f"An error occurred: {e}")
