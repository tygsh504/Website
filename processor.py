import io
import os
import sys
import time
import torch
import numpy as np
from PIL import Image
from torchvision import transforms
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# --- FIX: Ensure the local custom model package is imported ---
# Get the directory of the current script, which is the project root.
# This ensures that we are using the local 'segmentation_models_pytorch' package
# located in the same directory, rather than a potentially installed one.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# The library has a nested structure `segmentation_models_pytorch/segmentation_models_pytorch`.
# We import the inner module which contains the model definitions.
import segmentation_models_pytorch.segmentation_models_pytorch as smp

# --- CONFIGURATION ---
MODEL_PATH = 'CP_best.pth' # Path to your best model
ENCODER_NAME = 'timm-efficientnet-b0'
INPUT_SHAPE = [640, 480] # [H, W] from test.py
SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive.metadata.readonly']

print("Initializing AI Background Processor...")

# 1. Setup Device & Model
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"Using device: {device}")

net = smp.EfficientUnetPlusPlus(
    encoder_name=ENCODER_NAME, 
    encoder_weights=None, 
    in_channels=3, 
    classes=1
)

# --- HOTFIX for 'act1' attribute error ---
# The custom EfficientUnetPlusPlus model implementation assumes access to an 'act1'
# attribute on the encoder, which is not present on the EfficientNetEncoder.
try:
    if not hasattr(net.encoder, 'act1'):
        if hasattr(net.encoder, '_swish'):
            net.encoder.act1 = net.encoder._swish
        elif hasattr(net.encoder, 'model') and hasattr(net.encoder.model, 'act1'):
            net.encoder.act1 = net.encoder.model.act1
        else:
            net.encoder.act1 = torch.nn.Identity()
except Exception as e:
    print(f"Warning: Could not apply hotfix for encoder 'act1' attribute. {e}")

# Load state dict handling DataParallel mapping if required
state_dict = torch.load(MODEL_PATH, map_location=device)
new_state_dict = {k[7:] if k.startswith('module.') else k: v for k, v in state_dict.items()}
net.load_state_dict(new_state_dict)
net.to(device)
net.eval()
print("Model Loaded Successfully.")

# 2. Setup Google Drive Service
def get_drive_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Failed to refresh token: {e}. Re-authenticating...")
                creds = None
                if os.path.exists('token.json'):
                    os.remove('token.json')
        
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

service = get_drive_service()

# 3. Processing Function
def process_and_upload(file_id, file_name, parent_id):
    try:
        # Download Image
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        # Load and Transform Image
        img = Image.open(fh).convert('RGB')
        original_size = img.size
        
        target_size = (INPUT_SHAPE[1], INPUT_SHAPE[0]) 
        img_resized = img.resize(target_size, Image.BILINEAR)
        img_tensor = transforms.ToTensor()(img_resized).unsqueeze(0).to(device, dtype=torch.float32)

        # Inference
        with torch.no_grad():
            outputs = net(img_tensor)
            probs = torch.sigmoid(outputs)
            pred_mask = (probs > 0.5).float().squeeze().cpu().numpy()
        
        # Convert predicted mask to PIL and resize back to original image size
        pred_bin = (pred_mask * 255).astype(np.uint8)
        mask_img = Image.fromarray(pred_bin, mode='L')
        mask_img = mask_img.resize(original_size, Image.NEAREST)

        # Save to temporary file
        temp_mask_path = 'temp_mask.png'
        mask_img.save(temp_mask_path)

        # Upload Mask back to Google Drive
        mask_name = f"mask_{os.path.splitext(file_name)[0]}.png"
        file_metadata = {
            'name': mask_name,
            'parents': [parent_id],
            'description': 'AI Segmentation Output'
        }
        
        media = MediaFileUpload(temp_mask_path, mimetype='image/png')
        service.files().create(body=file_metadata, media_body=media).execute()
        
        print(f"Success: Uploaded {mask_name}")
        os.remove(temp_mask_path)

    except Exception as e:
        print(f"Error processing {file_name}: {e}")

def mask_exists(parent_id, original_file_name):
    """Check if a mask for the given file already exists in Google Drive."""
    mask_name = f"mask_{os.path.splitext(original_file_name)[0]}.png"
    
    try:
        query = f"'{parent_id}' in parents and name='{mask_name}' and trashed=false"
        response = service.files().list(q=query, fields="files(id)").execute()
        if response.get('files'):
            print(f"Mask '{mask_name}' already exists. Skipping.")
            return True
    except Exception as e:
        print(f"Error checking for existing mask: {e}")
        # In case of error, assume mask does not exist to allow processing
    return False

# 4. Watcher Loop (Changes API)
def watch_drive():
    global service
    print("Listening for new image uploads in Google Drive...")
    processed_files = set() # Use a set for faster lookups
    
    try:
        response = service.changes().getStartPageToken().execute()
        saved_token = response.get('startPageToken')
    except Exception as e:
        print(f"Error starting watcher (token might be expired). Re-authenticating...")
        service = get_drive_service()
        response = service.changes().getStartPageToken().execute()
        saved_token = response.get('startPageToken')

    while True:
        try:
            response = service.changes().list(pageToken=saved_token, fields="newStartPageToken, changes(fileId)").execute()
            
            for change in response.get('changes', []):
                file_id = change.get('fileId')
                
                if file_id in processed_files:
                    continue
                
                try:
                    file_info = service.files().get(fileId=file_id, fields='id, name, parents, mimeType, trashed').execute()
                    
                    if file_info.get('trashed'):
                        continue

                    if file_info.get('mimeType', '').startswith('image/') and not file_info['name'].startswith('mask_'):
                        parent_id = file_info.get('parents', [None])[0]
                        
                        if parent_id and not mask_exists(parent_id, file_info['name']):
                            print(f"\nNew Image Detected: {file_info['name']} ({file_info['id']})")
                            process_and_upload(file_id, file_info['name'], parent_id)
                        
                        processed_files.add(file_id)
                        if len(processed_files) > 1000:
                            processed_files.pop() # Keep memory usage bounded
                except Exception:
                    # This can happen if the file is deleted before we get info, which is fine.
                    pass
                    
            if 'newStartPageToken' in response:
                saved_token = response['newStartPageToken']
                
            time.sleep(10) # Poll every 10 seconds
        except Exception as e:
            print(f"API connection lost or token expired during loop: {e}")
            print("Attempting to re-authenticate and resume...")
            try:
                service = get_drive_service()
            except Exception as auth_e:
                print(f"Failed to recover: {auth_e}")
            time.sleep(20) # Wait longer after a connection loss

if __name__ == '__main__':
    watch_drive()