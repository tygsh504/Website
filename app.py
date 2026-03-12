import io
import os
import os.path 
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv
from supabase import create_client

# Google API Libraries
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = "cropguard_super_secret_key"

# --- Supabase Configuration ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL and Key must be set in environment variables.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Google Drive Configuration (OAuth 2.0) ---
SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive.metadata.readonly']
DATABASE_FOLDER_ID = '1fHZKA6JMf1cJyxWM8dGEEBAPmxyQiDJY' 

def get_drive_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('drive', 'v3', credentials=creds)

def get_or_create_folder(name, parent_id):
    service = get_drive_service()
    query = f"name = '{name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, fields="files(id)").execute()
    
    files = results.get('files', [])
    if files:
        return files[0]['id']
    else:
        file_metadata = {'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

# --- Authentication Routes ---

@app.route('/')
def root():
    user_name = session.get('user_name')
    return render_template('index.html', user_name=user_name)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        try:
            auth_response = supabase.auth.sign_in_with_password({"email": email, "password": password})
            if auth_response.user:
                session['user'] = email
                user_metadata = auth_response.user.user_metadata
                session['user_name'] = user_metadata.get('full_name') if user_metadata else email.split('@')[0]
                
                user_folder_name = email.split('@')[0]
                session['user_folder_id'] = get_or_create_folder(user_folder_name, DATABASE_FOLDER_ID)
                
                return redirect(url_for('root'))
        except Exception as e:
            flash("Invalid email or password. Please try again.")
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for('signup'))
        try:
            supabase.auth.sign_up({
                "email": email, "password": password,
                "options": {"data": {"full_name": full_name}}
            })
            flash("Account created! You can now log in.")
            return redirect(url_for('login'))
        except Exception as e:
            flash(f"Sign up failed: {str(e)}")
            return redirect(url_for('signup'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('root'))

# --- UPLOAD & HISTORY ROUTES ---

@app.route('/upload')
def upload_menu():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('upload_menu.html', user_name=session.get('user_name'))

@app.route('/upload/image', methods=['GET', 'POST'])
def upload_image():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        service = get_drive_service()
        latitude = request.form.get('latitude', 'Unknown')
        longitude = request.form.get('longitude', 'Unknown')
        files = request.files.getlist('leaf_files')
        
        if files and len(files) > 0 and files[0].filename != '':
            today = datetime.now().strftime('%Y-%m-%d')
            date_folder_id = get_or_create_folder(today, session['user_folder_id'])
            
            uploaded_count = 0
            for file in files:
                if file.filename and file.mimetype.startswith('image/'):
                    # Save location in the file description
                    file_metadata = {
                        'name': file.filename,
                        'parents': [date_folder_id],
                        'description': f"Lat: {latitude}, Long: {longitude}"
                    }
                    media = MediaIoBaseUpload(io.BytesIO(file.read()), mimetype=file.mimetype)
                    service.files().create(body=file_metadata, media_body=media).execute()
                    uploaded_count += 1
            
            if uploaded_count > 0:
                flash(f"Successfully uploaded {uploaded_count} images to your Drive.")
            else:
                flash("No valid images were uploaded.")
            return redirect(url_for('upload_image'))
            
    return render_template('upload_image.html', user_name=session.get('user_name'))

@app.route('/history')
def history():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    service = get_drive_service()
    query = f"'{session['user_folder_id']}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    folders = service.files().list(q=query, fields="files(id, name)").execute().get('files', [])
    
    history_data = []
    for folder in folders:
        file_query = f"'{folder['id']}' in parents and trashed = false"
        files = service.files().list(q=file_query, fields="files(id, name, thumbnailLink, webViewLink, description)").execute().get('files', [])
        if files:
            history_data.append({'date': folder['name'], 'files': files})
    
    history_data.sort(key=lambda x: x['date'], reverse=True)
    return render_template('history.html', history_data=history_data, user_name=session.get('user_name'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)