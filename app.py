import io
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from supabase import create_client
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

app = Flask(__name__)
app.secret_key = "cropguard_super_secret_key"

# --- Supabase Configuration ---
SUPABASE_URL = "https://jcdjuqikvspvxdmfixit.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpjZGp1cWlrdnNwdnhkbWZpeGl0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzNTY1NzEsImV4cCI6MjA4NzkzMjU3MX0.ki4bFOQgXcu9jRnOoG861QNcqmMyNRMtVK3wRVrV7Lk"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Google Drive Configuration ---
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'service_account.json'
# Your specific Website Database ID
DATABASE_FOLDER_ID = '1fHZKA6JMf1cJyxWM8dGEEBAPmxyQiDJY' 

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
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
            session['user'] = email
            
            # Extract the full name from Supabase metadata
            user_metadata = auth_response.user.user_metadata
            session['user_name'] = user_metadata.get('full_name') if user_metadata else email.split('@')[0]
            
            # Cross-check/Create user folder in Google Drive based on email prefix
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
            flash("Passwords do not match. Please try again.")
            return redirect(url_for('signup'))
        try:
            auth_response = supabase.auth.sign_up({
                "email": email, "password": password,
                "options": {"data": {"full_name": full_name}}
            })
            flash("Account created successfully! You can now log in.")
            return redirect(url_for('login'))
        except Exception as e:
            flash(f"Sign up failed: {str(e)}")
            return redirect(url_for('signup'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('user_name', None)
    session.pop('user_folder_id', None)
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
        file = request.files.get('leaf_image')
        
        if file and file.filename != '':
            service = get_drive_service()
            # Get/Create Date Folder inside User Folder
            today = datetime.now().strftime('%Y-%m-%d')
            date_folder_id = get_or_create_folder(today, session['user_folder_id'])
            
            # Upload file
            file_metadata = {'name': file.filename, 'parents': [date_folder_id]}
            media = MediaIoBaseUpload(io.BytesIO(file.read()), mimetype=file.mimetype)
            service.files().create(body=file_metadata, media_body=media).execute()
            
            flash(f"Successfully uploaded {file.filename} to Drive.")
            return redirect(url_for('upload_image'))
            
    return render_template('upload_image.html', user_name=session.get('user_name'))

@app.route('/upload/folder', methods=['GET', 'POST'])
def upload_folder():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        files = request.files.getlist('leaf_folder')
        
        if files and len(files) > 0 and files[0].filename != '':
            service = get_drive_service()
            today = datetime.now().strftime('%Y-%m-%d')
            date_folder_id = get_or_create_folder(today, session['user_folder_id'])
            
            for file in files:
                if file.filename:
                    file_metadata = {'name': file.filename, 'parents': [date_folder_id]}
                    media = MediaIoBaseUpload(io.BytesIO(file.read()), mimetype=file.mimetype)
                    service.files().create(body=file_metadata, media_body=media).execute()
            
            flash(f"Successfully uploaded {len(files)} images from folder to Drive.")
            return redirect(url_for('upload_folder'))
            
    return render_template('upload_folder.html', user_name=session.get('user_name'))

@app.route('/history')
def history():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    service = get_drive_service()
    # Fetch all date folders for this user
    query = f"'{session['user_folder_id']}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    folders = service.files().list(q=query, fields="files(id, name)").execute().get('files', [])
    
    history_data = []
    for folder in folders:
        # Fetch files inside each date folder
        file_query = f"'{folder['id']}' in parents and trashed = false"
        files = service.files().list(q=file_query, fields="files(id, name, thumbnailLink, webViewLink)").execute().get('files', [])
        if files:
            history_data.append({'date': folder['name'], 'files': files})
    
    # Sort history by date descending
    history_data.sort(key=lambda x: x['date'], reverse=True)
    return render_template('history.html', history_data=history_data, user_name=session.get('user_name'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)