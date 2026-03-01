from flask import Flask, render_template, request, redirect, url_for, session, flash
from supabase import create_client
import os

app = Flask(__name__)
# Secret key is required for Flask sessions to work securely
app.secret_key = "cropguard_super_secret_key" 

# --- Supabase Configuration ---
# Replace these with your actual Supabase project credentials
SUPABASE_URL = "https://jcdjuqikvspvxdmfixit.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpjZGp1cWlrdnNwdnhkbWZpeGl0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzNTY1NzEsImV4cCI6MjA4NzkzMjU3MX0.ki4bFOQgXcu9jRnOoG861QNcqmMyNRMtVK3wRVrV7Lk"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Routes ---

@app.route('/')
def root():
    """Redirects to dashboard if logged in, otherwise to login."""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user authentication."""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            # Authenticate with Supabase
            auth_response = supabase.auth.sign_in_with_password({"email": email, "password": password})
            
            # Save the user's email in the session cookie
            session['user'] = email 
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            # If login fails, show an error message on the page
            flash("Invalid email or password. Please try again.")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    """The main interface (Protected Route)."""
    if 'user' not in session:
        return redirect(url_for('login'))
    
    # Pass the user's email to the HTML template to display in the navbar
    return render_template('index.html', user_email=session['user'])

@app.route('/logout')
def logout():
    """Clears the session and logs the user out."""
    session.pop('user', None)
    return redirect(url_for('login'))

# Placeholder for your machine learning integration later
@app.route('/upload_leaf', methods=['POST'])
def upload_leaf():
    """Route to handle image uploads for the segmentation model."""
    if 'user' not in session:
        return redirect(url_for('login'))
    # Logic for processing the uploaded leaf image will go here
    pass

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """Handles new user registration."""
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        # 1. Check if passwords match
        if password != confirm_password:
            flash("Passwords do not match. Please try again.")
            return redirect(url_for('signup'))

        try:
            # 2. Register with Supabase
            # Note: Supabase stores the user in the 'auth.users' table automatically
            auth_response = supabase.auth.sign_up({
                "email": email, 
                "password": password,
                "options": {
                    "data": {
                        "full_name": full_name
                    }
                }
            })
            
            flash("Account created successfully! You can now log in.")
            return redirect(url_for('login'))
            
        except Exception as e:
            # Catch errors (e.g., email already exists)
            flash(f"Sign up failed: {str(e)}")
            return redirect(url_for('signup'))

    return render_template('signup.html')

if __name__ == '__main__':
    # debug=True allows the server to auto-reload when you change code
    app.run(debug=True, port=5000)