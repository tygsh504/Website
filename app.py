from flask import Flask, render_template, request, redirect, url_for, session, flash
from supabase import create_client
import os

app = Flask(__name__)
app.secret_key = "cropguard_super_secret_key" 

# --- Supabase Configuration ---
SUPABASE_URL = "https://jcdjuqikvspvxdmfixit.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpjZGp1cWlrdnNwdnhkbWZpeGl0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzNTY1NzEsImV4cCI6MjA4NzkzMjU3MX0.ki4bFOQgXcu9jRnOoG861QNcqmMyNRMtVK3wRVrV7Lk"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Routes ---

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
    return redirect(url_for('root'))

# --- UPLOAD ROUTES ---

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
        leaf_image = request.files.get('leaf_image')
        lat = request.form.get('latitude')
        lng = request.form.get('longitude')
        
        if leaf_image and leaf_image.filename != '':
            flash(f"Successfully uploaded {leaf_image.filename}. Location tagged at: {lat}, {lng}")
            return redirect(url_for('upload_image'))
            
    return render_template('upload_image.html', user_name=session.get('user_name'))

@app.route('/upload/folder', methods=['GET', 'POST'])
def upload_folder():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        leaf_folder = request.files.getlist('leaf_folder')
        lat = request.form.get('latitude')
        lng = request.form.get('longitude')
        
        if leaf_folder and len(leaf_folder) > 0 and leaf_folder[0].filename != '':
            flash(f"Successfully uploaded {len(leaf_folder)} images from folder. Location tagged at: {lat}, {lng}")
            return redirect(url_for('upload_folder'))
            
    return render_template('upload_folder.html', user_name=session.get('user_name'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)