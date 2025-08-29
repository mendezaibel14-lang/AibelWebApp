from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, flash
import pyodbc
from azure.storage.blob import BlobServiceClient
import os
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import json
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from textblob import TextBlob
import cv2
import tempfile

app = Flask(__name__)
app.secret_key = 'b9e4f7a1c02d8e93f67a4c5d2e8ab91ff4763a6d85c24550'

AZURE_SQL_SERVER = "aibel.database.windows.net"
AZURE_SQL_DATABASE = "Aibel1234"
AZURE_SQL_USERNAME = "Mendezaibel123"
AZURE_SQL_PASSWORD = "Romelulukaku@123"

AZURE_STORAGE_CONNECTION_STRING = "DefaultEndpointsProtocol=https;AccountName=aibel123;AccountKey=8MJJTc9DoVL8TUObU9SRNcCFl4+4YiWvWXG2wVOSnyQ3FuswKsJXdOfHJKd6t+OIp2fyKjGM/y7m+AStwqWABQ==;EndpointSuffix=core.windows.net"
AZURE_STORAGE_CONTAINER = "data"



login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, user_type):
        self.id = id
        self.username = username
        self.user_type = user_type

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, user_type FROM users WHERE id = ?", user_id)
    user_data = cursor.fetchone()
    conn.close()
    if user_data:
        return User(user_data[0], user_data[1], user_data[2])
    return None

def get_db_connection():
    connection_string = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={AZURE_SQL_SERVER};DATABASE={AZURE_SQL_DATABASE};UID={AZURE_SQL_USERNAME};PWD={AZURE_SQL_PASSWORD}'
    return pyodbc.connect(connection_string)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' AND xtype='U')
        CREATE TABLE users (
            id INT IDENTITY(1,1) PRIMARY KEY,
            username NVARCHAR(50) UNIQUE NOT NULL,
            email NVARCHAR(100) UNIQUE NOT NULL,
            password_hash NVARCHAR(255) NOT NULL,
            user_type NVARCHAR(10) NOT NULL,
            created_at DATETIME DEFAULT GETDATE()
        )
    ''')

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='videos' AND xtype='U')
        CREATE TABLE videos (
            id INT IDENTITY(1,1) PRIMARY KEY,
            title NVARCHAR(200) NOT NULL,
            publisher NVARCHAR(100) NOT NULL,
            producer NVARCHAR(100) NOT NULL,
            genre NVARCHAR(50) NOT NULL,
            age_rating NVARCHAR(10) NOT NULL,
            video_url NVARCHAR(500) NOT NULL,
            thumbnail_url NVARCHAR(500),
            creator_id INT NOT NULL,
            created_at DATETIME DEFAULT GETDATE(),
            FOREIGN KEY (creator_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ratings' AND xtype='U')
        CREATE TABLE ratings (
            id INT IDENTITY(1,1) PRIMARY KEY,
            video_id INT NOT NULL,
            user_id INT NOT NULL,
            rating INT NOT NULL,
            created_at DATETIME DEFAULT GETDATE(),
            FOREIGN KEY (video_id) REFERENCES videos(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='comments' AND xtype='U')
        CREATE TABLE comments (
            id INT IDENTITY(1,1) PRIMARY KEY,
            video_id INT NOT NULL,
            user_id INT NOT NULL,
            comment NVARCHAR(500) NOT NULL,
            sentiment NVARCHAR(10),
            created_at DATETIME DEFAULT GETDATE(),
            FOREIGN KEY (video_id) REFERENCES videos(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    conn.commit()
    conn.close()

blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)

@app.route('/')
def home():
    return render_template_string(HOME_TEMPLATE)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        user_type = request.form['user_type']

        password_hash = generate_password_hash(password)

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, user_type) VALUES (?, ?, ?, ?)",
                username, email, password_hash, user_type
            )
            conn.commit()
            conn.close()
            flash('Registration successful!', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Username or email already exists!', 'error')

    return render_template_string(REGISTER_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password_hash, user_type FROM users WHERE username = ?", username)
        user_data = cursor.fetchone()
        conn.close()

        if user_data and check_password_hash(user_data[2], password):
            user = User(user_data[0], user_data[1], user_data[3])
            login_user(user)
            if user.user_type == 'creator':
                return redirect(url_for('creator_dashboard'))
            else:
                return redirect(url_for('consumer_dashboard'))
        else:
            flash('Invalid credentials!', 'error')

    return render_template_string(LOGIN_TEMPLATE)

@app.route('/creator-dashboard')
@login_required
def creator_dashboard():
    if current_user.user_type != 'creator':
        return redirect(url_for('login'))
    return render_template_string(CREATOR_DASHBOARD_TEMPLATE)

@app.route('/consumer-dashboard')
@login_required
def consumer_dashboard():
    if current_user.user_type != 'consumer':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT v.id,
                          v.title,
                          v.publisher,
                          v.producer,
                          v.genre,
                          v.age_rating,
                          v.video_url,
                          AVG(CAST(r.rating AS FLOAT)) as avg_rating,
                          v.thumbnail_url
                   FROM videos v
                   LEFT JOIN ratings r ON v.id = r.video_id
                   GROUP BY v.id, v.title, v.publisher, v.producer, v.genre, v.age_rating, v.video_url, v.created_at, v.thumbnail_url
                   ORDER BY v.created_at DESC
                   ''')
    videos = cursor.fetchall()

    # Fetch user ratings
    user_ratings = {}
    cursor.execute('''
        SELECT video_id, rating
        FROM ratings
        WHERE user_id = ?
    ''', current_user.id)
    for row in cursor.fetchall():
        user_ratings[row[0]] = row[1]

    # Fetch comments
    comments_dict = {}
    cursor.execute('''
        SELECT c.video_id, u.username, c.comment, c.created_at, c.sentiment
        FROM comments c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.created_at DESC
    ''')
    all_comments = cursor.fetchall()
    for comment in all_comments:
        vid = comment[0]
        if vid not in comments_dict:
            comments_dict[vid] = []
        comments_dict[vid].append({
            'username': comment[1],
            'comment': comment[2],
            'created_at': comment[3].strftime('%Y-%m-%d %H:%M:%S'),
            'sentiment': comment[4]
        })

    conn.close()

    return render_template_string(CONSUMER_DASHBOARD_TEMPLATE, videos=videos, user_ratings=user_ratings, comments=comments_dict)

@app.route('/upload-video', methods=['POST'])
@login_required
def upload_video():
    if current_user.user_type != 'creator':
        return redirect(url_for('login'))

    title = request.form['title']
    publisher = request.form['publisher']
    producer = request.form['producer']
    genre = request.form['genre']
    age_rating = request.form['age_rating']
    video_file = request.files['video']

    if video_file:
        filename = secure_filename(video_file.filename)
        blob_name = f"{uuid.uuid4()}_{filename}"

        try:
            # Save video to temp file
            with tempfile.NamedTemporaryFile(delete=False) as temp_video:
                video_file.save(temp_video.name)
                temp_video_path = temp_video.name

            # Upload video
            blob_client = blob_service_client.get_blob_client(
                container=AZURE_STORAGE_CONTAINER,
                blob=blob_name
            )
            with open(temp_video_path, "rb") as f:
                blob_client.upload_blob(f, overwrite=True)
            video_url = blob_client.url

            # Generate thumbnail
            thumbnail_url = None
            cap = cv2.VideoCapture(temp_video_path)
            success, frame = cap.read()
            if success:
                thumbnail_blob_name = f"{uuid.uuid4()}_thumb.jpg"
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_thumb:
                    cv2.imwrite(temp_thumb.name, frame)
                    temp_thumb_path = temp_thumb.name

                blob_client_thumb = blob_service_client.get_blob_client(
                    container=AZURE_STORAGE_CONTAINER,
                    blob=thumbnail_blob_name
                )
                with open(temp_thumb_path, "rb") as f:
                    blob_client_thumb.upload_blob(f, overwrite=True)
                thumbnail_url = blob_client_thumb.url

                os.unlink(temp_thumb_path)

            cap.release()
            os.unlink(temp_video_path)

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO videos (title, publisher, producer, genre, age_rating, video_url, thumbnail_url, creator_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                title, publisher, producer, genre, age_rating, video_url, thumbnail_url, current_user.id
            )
            conn.commit()
            conn.close()

            flash('Video uploaded successfully!', 'success')
        except Exception as e:
            flash(f'Upload failed: {str(e)}', 'error')

    return redirect(url_for('creator_dashboard'))

@app.route('/rate-video', methods=['POST'])
@login_required
def rate_video():
    if current_user.user_type != 'consumer':
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    video_id = data['video_id']
    rating = data['rating']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM ratings WHERE video_id = ? AND user_id = ?", video_id, current_user.id)
    existing = cursor.fetchone()

    if existing:
        cursor.execute("UPDATE ratings SET rating = ? WHERE video_id = ? AND user_id = ?",
                       rating, video_id, current_user.id)
    else:
        cursor.execute("INSERT INTO ratings (video_id, user_id, rating) VALUES (?, ?, ?)",
                       video_id, current_user.id, rating)

    conn.commit()

    # Fetch new average
    cursor.execute("SELECT AVG(CAST(rating AS FLOAT)) FROM ratings WHERE video_id = ?", video_id)
    new_avg = cursor.fetchone()[0]

    conn.close()

    return jsonify({'success': True, 'avg_rating': new_avg})

@app.route('/add-comment', methods=['POST'])
@login_required
def add_comment():
    if current_user.user_type != 'consumer':
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    video_id = data['video_id']
    comment_text = data['comment']

    # Perform sentiment analysis
    blob = TextBlob(comment_text)
    polarity = blob.sentiment.polarity
    if polarity > 0:
        sentiment = 'positive'
    elif polarity < 0:
        sentiment = 'negative'
    else:
        sentiment = 'neutral'

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO comments (video_id, user_id, comment, sentiment) VALUES (?, ?, ?, ?)",
                   video_id, current_user.id, comment_text, sentiment)
    conn.commit()
    conn.close()

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({'success': True, 'comment': {'username': current_user.username, 'comment': comment_text, 'created_at': created_at, 'sentiment': sentiment}})

@app.route('/search-videos')
@login_required
def search_videos():
    query = request.args.get('q', '')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT v.id,
                          v.title,
                          v.publisher,
                          v.producer,
                          v.genre,
                          v.age_rating,
                          v.video_url,
                          AVG(CAST(r.rating AS FLOAT)) as avg_rating,
                          v.thumbnail_url
                   FROM videos v
                            LEFT JOIN ratings r ON v.id = r.video_id
                   WHERE v.title LIKE ?
                      OR v.genre LIKE ?
                      OR v.publisher LIKE ?
                   GROUP BY v.id, v.title, v.publisher, v.producer, v.genre, v.age_rating, v.video_url, v.thumbnail_url
                   ''', f'%{query}%', f'%{query}%', f'%{query}%')
    videos = cursor.fetchall()

    video_list = [{
        'id': v[0], 'title': v[1], 'publisher': v[2], 'producer': v[3],
        'genre': v[4], 'age_rating': v[5], 'video_url': v[6], 'avg_rating': v[7], 'thumbnail_url': v[8]
    } for v in videos]

    # Fetch user ratings
    user_ratings = {}
    cursor.execute('''
        SELECT video_id, rating
        FROM ratings
        WHERE user_id = ?
    ''', current_user.id)
    for row in cursor.fetchall():
        user_ratings[row[0]] = row[1]

    for video in video_list:
        video['user_rating'] = user_ratings.get(video['id'], 0)

    # Fetch comments
    comments_dict = {}
    if video_list:
        video_ids = [v['id'] for v in video_list]
        placeholders = ','.join(['?'] * len(video_ids))
        cursor.execute(f'''
            SELECT c.video_id, u.username, c.comment, c.created_at, c.sentiment
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.video_id IN ({placeholders})
            ORDER BY c.created_at DESC
        ''', video_ids)
        all_comments = cursor.fetchall()
        for comment in all_comments:
            vid = comment[0]
            if vid not in comments_dict:
                comments_dict[vid] = []
            comments_dict[vid].append({
                'username': comment[1],
                'comment': comment[2],
                'created_at': comment[3].strftime('%Y-%m-%d %H:%M:%S'),
                'sentiment': comment[4]
            })

    for video in video_list:
        video['comments'] = comments_dict.get(video['id'], [])

    conn.close()

    return jsonify(video_list)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


HOME_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StreamVibe - Premium Video Platform</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Georgia', serif;
            background: linear-gradient(45deg, #f5f5f0 0%, #ffffff 50%, #f0ebe5 100%);
            color: #3e2723;
            line-height: 1.6;
        }

        .header-section {
            background: rgba(255, 255, 255, 0.95);
            box-shadow: 0 4px 20px rgba(139, 69, 19, 0.1);
            padding: 1rem 0;
            position: fixed;
            width: 100%;
            top: 0;
            z-index: 1000;
            backdrop-filter: blur(10px);
        }

        .header-content {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .brand-name {
            font-size: 2.5rem;
            font-weight: bold;
            color: #8b4513;
            text-shadow: 2px 2px 4px rgba(139, 69, 19, 0.1);
            font-family: 'Times New Roman', serif;
        }

        .nav-buttons {
            display: flex;
            gap: 1rem;
        }

        .nav-btn {
            padding: 0.8rem 2rem;
            background: #8b4513;
            color: white;
            text-decoration: none;
            border-radius: 25px;
            font-weight: 600;
            transition: all 0.3s ease;
            border: 2px solid #8b4513;
        }

        .nav-btn:hover {
            background: transparent;
            color: #8b4513;
            transform: translateY(-2px);
        }

        .main-hero {
            margin-top: 100px;
            padding: 5rem 2rem;
            text-align: center;
            background: radial-gradient(circle, rgba(139, 69, 19, 0.05) 0%, transparent 70%);
        }

        .hero-title {
            font-size: 4.5rem;
            font-weight: 300;
            color: #5d4037;
            margin-bottom: 2rem;
            font-family: 'Times New Roman', serif;
            text-shadow: 1px 1px 3px rgba(139, 69, 19, 0.1);
        }

        .hero-subtitle {
            font-size: 1.4rem;
            color: #6d4c41;
            margin-bottom: 3rem;
            max-width: 700px;
            margin-left: auto;
            margin-right: auto;
            font-style: italic;
        }

        .action-buttons {
            display: flex;
            justify-content: center;
            gap: 2rem;
            margin-bottom: 5rem;
        }

        .primary-action {
            padding: 1.2rem 3rem;
            background: linear-gradient(135deg, #8b4513 0%, #a0522d 100%);
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-size: 1.2rem;
            font-weight: 600;
            box-shadow: 0 8px 25px rgba(139, 69, 19, 0.3);
            transition: all 0.3s ease;
            border: none;
        }

        .primary-action:hover {
            transform: translateY(-3px);
            box-shadow: 0 12px 35px rgba(139, 69, 19, 0.4);
        }

        .secondary-action {
            padding: 1.2rem 3rem;
            background: transparent;
            color: #8b4513;
            text-decoration: none;
            border: 2px solid #8b4513;
            border-radius: 8px;
            font-size: 1.2rem;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .secondary-action:hover {
            background: #8b4513;
            color: white;
            transform: translateY(-3px);
        }

        .features-section {
            background: white;
            padding: 5rem 2rem;
            box-shadow: inset 0 10px 30px rgba(139, 69, 19, 0.05);
        }

        .features-container {
            max-width: 1200px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 3rem;
        }

        .feature-card {
            background: linear-gradient(135deg, #f8f4f0 0%, #fff 100%);
            padding: 3rem;
            border-radius: 15px;
            text-align: center;
            border: 1px solid rgba(139, 69, 19, 0.1);
            box-shadow: 0 10px 30px rgba(139, 69, 19, 0.08);
            transition: all 0.3s ease;
        }

        .feature-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 15px 40px rgba(139, 69, 19, 0.15);
        }

        .feature-symbol {
            font-size: 3rem;
            color: #8b4513;
            margin-bottom: 1.5rem;
            display: block;
        }

        .feature-heading {
            font-size: 1.5rem;
            color: #5d4037;
            margin-bottom: 1rem;
            font-weight: 600;
        }

        .feature-text {
            color: #6d4c41;
            font-size: 1.1rem;
        }

        .footer-area {
            background: #3e2723;
            color: white;
            text-align: center;
            padding: 2rem;
        }

        .footer-text {
            font-size: 1rem;
            opacity: 0.9;
        }

        @media (max-width: 768px) {
            .hero-title {
                font-size: 2.8rem;
            }

            .action-buttons {
                flex-direction: column;
                align-items: center;
            }

            .features-container {
                grid-template-columns: 1fr;
            }

            .header-content {
                flex-direction: column;
                gap: 1rem;
            }
        }
    </style>
</head>
<body>
    <header class="header-section">
        <div class="header-content">
            <div class="brand-name">StreamVibe</div>
            <nav class="nav-buttons">
                <a href="{{ url_for('login') }}" class="nav-btn">Sign In</a>
                <a href="{{ url_for('register') }}" class="nav-btn">Join Now</a>
            </nav>
        </div>
    </header>

    <main class="main-hero">
        <h1 class="hero-title">Premium Streaming Experience</h1>
        <p class="hero-subtitle">Discover exceptional video content curated for discerning viewers. Join our community of creators and enthusiasts.</p>

        <div class="action-buttons">
            <a href="{{ url_for('register') }}" class="primary-action">Begin Your Journey</a>
            <a href="{{ url_for('login') }}" class="secondary-action">Member Access</a>
        </div>
    </main>

    <section class="features-section">
        <div class="features-container">
            <div class="feature-card">
                <span class="feature-symbol">📚</span>
                <h3 class="feature-heading">Curated Library</h3>
                <p class="feature-text">Handpicked content from talented creators worldwide, ensuring quality and variety in every viewing experience.</p>
            </div>
            <div class="feature-card">
                <span class="feature-symbol">🎭</span>
                <h3 class="feature-heading">Artistic Excellence</h3>
                <p class="feature-text">Platform dedicated to showcasing premium video content with sophisticated recommendation algorithms.</p>
            </div>
            <div class="feature-card">
                <span class="feature-symbol">🤝</span>
                <h3 class="feature-heading">Community Hub</h3>
                <p class="feature-text">Connect with like-minded individuals through thoughtful discussions and meaningful content interactions.</p>
            </div>
        </div>
    </section>

    <footer class="footer-area">
        <p class="footer-text">© 2024 StreamVibe. Elevating digital entertainment experiences.</p>
    </footer>
</body>
</html>
'''

REGISTER_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StreamVibe - Create Account</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Georgia', serif;
            background: linear-gradient(135deg, #f5f5f0 0%, #ffffff 50%, #f0ebe5 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .signup-container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(139, 69, 19, 0.15);
            overflow: hidden;
            width: 90%;
            max-width: 1000px;
            display: grid;
            grid-template-columns: 1.2fr 1fr;
            min-height: 600px;
        }

        .form-section {
            padding: 3rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }

        .form-title {
            font-size: 2.5rem;
            color: #5d4037;
            margin-bottom: 0.5rem;
            font-weight: 300;
            text-align: center;
        }

        .form-description {
            color: #6d4c41;
            text-align: center;
            margin-bottom: 2rem;
            font-size: 1.1rem;
            font-style: italic;
        }

        .alert-message {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            font-weight: 500;
        }

        .alert-success {
            background: rgba(139, 69, 19, 0.1);
            color: #8b4513;
            border-left: 4px solid #8b4513;
        }

        .alert-error {
            background: rgba(220, 53, 69, 0.1);
            color: #dc3545;
            border-left: 4px solid #dc3545;
        }

        .form-group {
            margin-bottom: 1.5rem;
        }

        .form-label {
            display: block;
            color: #5d4037;
            font-weight: 600;
            margin-bottom: 0.5rem;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .form-input {
            width: 100%;
            padding: 1rem;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 1rem;
            background: #fafafa;
            color: #3e2723;
            transition: all 0.3s ease;
        }

        .form-input:focus {
            outline: none;
            border-color: #8b4513;
            background: white;
            box-shadow: 0 0 0 3px rgba(139, 69, 19, 0.1);
        }

        .role-selection {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
            margin-top: 0.5rem;
        }

        .role-card {
            position: relative;
        }

        .role-input {
            display: none;
        }

        .role-button {
            display: block;
            width: 100%;
            padding: 1.2rem;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            background: #fafafa;
            color: #5d4037;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: 600;
        }

        .role-input:checked + .role-button {
            background: #8b4513;
            color: white;
            border-color: #8b4513;
        }

        .submit-btn {
            width: 100%;
            padding: 1.2rem;
            background: linear-gradient(135deg, #8b4513 0%, #a0522d 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1.1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            margin: 1.5rem 0;
        }

        .submit-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(139, 69, 19, 0.3);
        }

        .form-footer {
            text-align: center;
            padding-top: 1rem;
            border-top: 1px solid #e0e0e0;
        }

        .back-link {
            color: #8b4513;
            text-decoration: none;
            font-weight: 500;
        }

        .back-link:hover {
            text-decoration: underline;
        }

        .welcome-section {
            background: linear-gradient(135deg, #8b4513 0%, #a0522d 100%);
            color: white;
            padding: 3rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            position: relative;
            overflow: hidden;
        }

        .welcome-section::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: repeating-linear-gradient(
                45deg,
                transparent,
                transparent 20px,
                rgba(255,255,255,0.05) 20px,
                rgba(255,255,255,0.05) 40px
            );
        }

        .welcome-content {
            position: relative;
            z-index: 1;
        }

        .welcome-brand {
            font-size: 3rem;
            font-weight: bold;
            margin-bottom: 1.5rem;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }

        .welcome-text {
            font-size: 1.2rem;
            margin-bottom: 2rem;
            opacity: 0.9;
            line-height: 1.6;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 2rem;
            width: 100%;
        }

        .stat-box {
            text-align: center;
        }

        .stat-number {
            font-size: 2rem;
            font-weight: bold;
            display: block;
            margin-bottom: 0.3rem;
        }

        .stat-text {
            font-size: 0.9rem;
            opacity: 0.8;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        @media (max-width: 768px) {
            .signup-container {
                grid-template-columns: 1fr;
                margin: 1rem;
            }

            .welcome-section {
                order: -1;
                padding: 2rem;
            }

            .form-section {
                padding: 2rem;
            }

            .role-selection {
                grid-template-columns: 1fr;
            }

            .stats-grid {
                grid-template-columns: repeat(4, 1fr);
                gap: 1rem;
            }
        }
    </style>
</head>
<body>
    <div class="signup-container">
        <div class="form-section">
            <h1 class="form-title">Join StreamVibe</h1>
            <p class="form-description">Create your account and become part of our exclusive community</p>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert-message alert-{{ category }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <form method="POST">
                <div class="form-group">
                    <label for="username" class="form-label">Choose Username</label>
                    <input type="text" id="username" name="username" class="form-input" required>
                </div>

                <div class="form-group">
                    <label for="email" class="form-label">Email Address</label>
                    <input type="email" id="email" name="email" class="form-input" required>
                </div>

                <div class="form-group">
                    <label for="password" class="form-label">Create Password</label>
                    <input type="password" id="password" name="password" class="form-input" required>
                </div>

                <div class="form-group">
                    <label class="form-label">Account Type</label>
                    <div class="role-selection">
                        <div class="role-card">
                            <input type="radio" id="creator" name="user_type" value="creator" class="role-input" required>
                            <label for="creator" class="role-button">Content Creator</label>
                        </div>
                        <div class="role-card">
                            <input type="radio" id="consumer" name="user_type" value="consumer" class="role-input" required>
                            <label for="consumer" class="role-button">Content Viewer</label>
                        </div>
                    </div>
                </div>

                <button type="submit" class="submit-btn">Create My Account</button>
            </form>

            <div class="form-footer">
                <a href="{{ url_for('home') }}" class="back-link">← Return to Homepage</a>
            </div>
        </div>

        <div class="welcome-section">
            <div class="welcome-content">
                <div class="welcome-brand">StreamVibe</div>
                <p class="welcome-text">Join thousands of creators and viewers in our premium streaming community where quality content meets passionate audiences.</p>
                <div class="stats-grid">
                    <div class="stat-box">
                        <span class="stat-number">5.2K</span>
                        <span class="stat-text">Creators</span>
                    </div>
                    <div class="stat-box">
                        <span class="stat-number">28K</span>
                        <span class="stat-text">Videos</span>
                    </div>
                    <div class="stat-box">
                        <span class="stat-number">95K</span>
                        <span class="stat-text">Members</span>
                    </div>
                    <div class="stat-box">
                        <span class="stat-number">150K</span>
                        <span class="stat-text">Views</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
'''

LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StreamVibe - Member Sign In</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Georgia', serif;
            background: linear-gradient(to right, #f5f5f0 0%, #ffffff 50%, #f0ebe5 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
        }

        body::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="10" cy="10" r="1" fill="rgba(139,69,19,0.1)"/><circle cx="90" cy="20" r="1" fill="rgba(139,69,19,0.1)"/><circle cx="30" cy="80" r="1" fill="rgba(139,69,19,0.1)"/><circle cx="70" cy="70" r="1" fill="rgba(139,69,19,0.1)"/></svg>') repeat;
            opacity: 0.5;
        }

        .login-container {
            background: white;
            border-radius: 15px;
            box-shadow: 0 25px 80px rgba(139, 69, 19, 0.2);
            overflow: hidden;
            width: 90%;
            max-width: 800px;
            position: relative;
            z-index: 1;
            border: 1px solid rgba(139, 69, 19, 0.1);
        }

        .login-header {
            background: linear-gradient(135deg, #8b4513 0%, #a0522d 100%);
            color: white;
            padding: 2rem;
            text-align: center;
            position: relative;
        }

        .login-header::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(45deg, transparent 30%, rgba(255,255,255,0.1) 50%, transparent 70%);
        }

        .header-content {
            position: relative;
            z-index: 1;
        }

        .brand-logo {
            font-size: 2.8rem;
            font-weight: bold;
            margin-bottom: 0.5rem;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }

        .brand-subtitle {
            font-size: 1.1rem;
            opacity: 0.9;
            font-style: italic;
        }

        .login-body {
            padding: 3rem;
        }

        .welcome-message {
            text-align: center;
            margin-bottom: 2.5rem;
        }

        .welcome-title {
            font-size: 2rem;
            color: #5d4037;
            margin-bottom: 0.5rem;
            font-weight: 400;
        }

        .welcome-text {
            color: #6d4c41;
            font-size: 1rem;
        }

        .notification {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 2rem;
            font-weight: 500;
        }

        .notification-success {
            background: rgba(139, 69, 19, 0.1);
            color: #8b4513;
            border-left: 4px solid #8b4513;
        }

        .notification-error {
            background: rgba(220, 53, 69, 0.1);
            color: #dc3545;
            border-left: 4px solid #dc3545;
        }

        .form-group {
            margin-bottom: 2rem;
            position: relative;
        }

        .input-label {
            display: block;
            color: #5d4037;
            font-weight: 600;
            margin-bottom: 0.5rem;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .login-input {
            width: 100%;
            padding: 1.2rem;
            border: 2px solid #e8e8e8;
            border-radius: 10px;
            font-size: 1.1rem;
            background: #f9f9f9;
            color: #3e2723;
            transition: all 0.3s ease;
        }

        .login-input:focus {
            outline: none;
            border-color: #8b4513;
            background: white;
            box-shadow: 0 0 0 4px rgba(139, 69, 19, 0.1);
        }

        .signin-button {
            width: 100%;
            padding: 1.3rem;
            background: linear-gradient(135deg, #8b4513 0%, #a0522d 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 1.2rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            margin-bottom: 2rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .signin-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(139, 69, 19, 0.3);
        }

        .form-navigation {
            text-align: center;
            padding-top: 1.5rem;
            border-top: 1px solid #e8e8e8;
        }

        .nav-link {
            color: #8b4513;
            text-decoration: none;
            font-weight: 500;
            transition: all 0.3s ease;
        }

        .nav-link:hover {
            color: #5d4037;
            text-decoration: underline;
        }

        .decorative-elements {
            position: absolute;
            top: 20px;
            right: 20px;
            width: 100px;
            height: 100px;
            background: radial-gradient(circle, rgba(139, 69, 19, 0.1) 0%, transparent 70%);
            border-radius: 50%;
        }

        .decorative-elements::before {
            content: '';
            position: absolute;
            top: 150px;
            left: -50px;
            width: 80px;
            height: 80px;
            background: radial-gradient(circle, rgba(139, 69, 19, 0.08) 0%, transparent 70%);
            border-radius: 50%;
        }

        @media (max-width: 768px) {
            .login-container {
                margin: 1rem;
                width: calc(100% - 2rem);
            }

            .login-body {
                padding: 2rem;
            }

            .brand-logo {
                font-size: 2.2rem;
            }

            .welcome-title {
                font-size: 1.6rem;
            }
        }
    </style>
</head>
<body>
    <div class="decorative-elements"></div>

    <div class="login-container">
        <div class="login-header">
            <div class="header-content">
                <div class="brand-logo">StreamVibe</div>
                <div class="brand-subtitle">Premium streaming community</div>
            </div>
        </div>

        <div class="login-body">
            <div class="welcome-message">
                <h2 class="welcome-title">Welcome Back</h2>
                <p class="welcome-text">Please sign in to access your account</p>
            </div>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="notification notification-{{ category }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <form method="POST">
                <div class="form-group">
                    <label for="username" class="input-label">Username</label>
                    <input type="text" id="username" name="username" class="login-input" required>
                </div>

                <div class="form-group">
                    <label for="password" class="input-label">Password</label>
                    <input type="password" id="password" name="password" class="login-input" required>
                </div>

                <button type="submit" class="signin-button">Sign In to Account</button>
            </form>

            <div class="form-navigation">
                <a href="{{ url_for('home') }}" class="nav-link">← Back to Homepage</a>
            </div>
        </div>
    </div>
</body>
</html>
'''

CREATOR_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StreamVibe - Creator Workshop</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Georgia', serif;
            background: linear-gradient(135deg, #f8f4f0 0%, #ffffff 100%);
            color: #3e2723;
            min-height: 100vh;
        }

        .dashboard-header {
            background: white;
            box-shadow: 0 4px 20px rgba(139, 69, 19, 0.1);
            border-bottom: 3px solid #8b4513;
            padding: 1.5rem 0;
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .header-container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .workshop-brand {
            font-size: 2rem;
            font-weight: bold;
            color: #8b4513;
            font-family: 'Times New Roman', serif;
        }

        .user-info {
            display: flex;
            align-items: center;
            gap: 2rem;
        }

        .creator-tag {
            padding: 0.5rem 1.2rem;
            background: rgba(139, 69, 19, 0.1);
            color: #8b4513;
            border: 2px solid #8b4513;
            border-radius: 20px;
            font-weight: 600;
            font-size: 0.9rem;
        }

        .logout-link {
            padding: 0.8rem 1.5rem;
            background: #dc3545;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .logout-link:hover {
            background: #c82333;
            transform: translateY(-1px);
        }

        .main-workspace {
            max-width: 1000px;
            margin: 0 auto;
            padding: 3rem 2rem;
        }

        .upload-section {
            background: white;
            border-radius: 15px;
            box-shadow: 0 15px 50px rgba(139, 69, 19, 0.1);
            overflow: hidden;
            border: 1px solid rgba(139, 69, 19, 0.1);
        }

        .section-header {
            background: linear-gradient(135deg, #8b4513 0%, #a0522d 100%);
            color: white;
            padding: 2rem;
            text-align: center;
        }

        .section-title {
            font-size: 2.5rem;
            font-weight: 300;
            margin-bottom: 0.5rem;
        }

        .section-subtitle {
            font-size: 1.1rem;
            opacity: 0.9;
            font-style: italic;
        }

        .form-content {
            padding: 3rem;
        }

        .notification {
            padding: 1rem 1.5rem;
            border-radius: 8px;
            margin-bottom: 2rem;
            font-weight: 500;
        }

        .notification-success {
            background: rgba(139, 69, 19, 0.1);
            color: #8b4513;
            border-left: 4px solid #8b4513;
        }

        .notification-error {
            background: rgba(220, 53, 69, 0.1);
            color: #dc3545;
            border-left: 4px solid #dc3545;
        }

        .form-layout {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 2rem;
            margin-bottom: 2.5rem;
        }

        .input-group {
            display: flex;
            flex-direction: column;
        }

        .input-group.full-width {
            grid-column: 1 / -1;
        }

        .input-label {
            color: #5d4037;
            font-weight: 600;
            margin-bottom: 0.5rem;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .form-field, .form-dropdown {
            padding: 1rem;
            border: 2px solid #e8e8e8;
            border-radius: 8px;
            font-size: 1rem;
            background: #fafafa;
            color: #3e2723;
            transition: all 0.3s ease;
        }

        .form-field:focus, .form-dropdown:focus {
            outline: none;
            border-color: #8b4513;
            background: white;
            box-shadow: 0 0 0 3px rgba(139, 69, 19, 0.1);
        }

        .file-upload-area {
            border: 3px dashed #8b4513;
            border-radius: 12px;
            padding: 4rem 2rem;
            text-align: center;
            background: rgba(139, 69, 19, 0.02);
            cursor: pointer;
            transition: all 0.3s ease;
            margin-bottom: 2rem;
        }

        .file-upload-area:hover {
            background: rgba(139, 69, 19, 0.05);
            border-color: #a0522d;
        }

        .upload-icon {
            font-size: 3rem;
            color: #8b4513;
            margin-bottom: 1rem;
        }

        .upload-title {
            font-size: 1.3rem;
            color: #5d4037;
            margin-bottom: 0.5rem;
            font-weight: 600;
        }

        .upload-description {
            color: #6d4c41;
            font-size: 1rem;
        }

        .file-info {
            background: rgba(139, 69, 19, 0.1);
            border: 1px solid #8b4513;
            border-radius: 8px;
            padding: 1rem;
            margin: 1.5rem 0;
            display: none;
            color: #8b4513;
        }

        .progress-container {
            margin: 2rem 0;
            display: none;
        }

        .progress-text {
            color: #5d4037;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }

        .progress-bar-bg {
            width: 100%;
            height: 8px;
            background: #e8e8e8;
            border-radius: 4px;
            overflow: hidden;
        }

        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #8b4513 0%, #a0522d 100%);
            width: 0%;
            transition: width 0.3s ease;
        }

        .publish-button {
            width: 100%;
            padding: 1.3rem;
            background: linear-gradient(135deg, #8b4513 0%, #a0522d 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1.2rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .publish-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(139, 69, 19, 0.3);
        }

        .publish-button:disabled {
            background: #ccc;
            color: #666;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }

        #videoFile {
            display: none;
        }

        @media (max-width: 768px) {
            .main-workspace {
                padding: 2rem 1rem;
            }

            .form-layout {
                grid-template-columns: 1fr;
                gap: 1.5rem;
            }

            .file-upload-area {
                padding: 3rem 1.5rem;
            }

            .header-container {
                flex-direction: column;
                gap: 1rem;
            }
        }
    </style>
</head>
<body>
    <div class="dashboard-header">
        <div class="header-container">
            <div class="workshop-brand">Creator Workshop</div>
            <div class="user-info">
                <span class="creator-tag">{{ current_user.username }}</span>
                <a href="{{ url_for('logout') }}" class="logout-link">Sign Out</a>
            </div>
        </div>
    </div>

    <div class="main-workspace">
        <div class="upload-section">
            <div class="section-header">
                <h1 class="section-title">Publish Your Content</h1>
                <p class="section-subtitle">Share your creative work with our community</p>
            </div>

            <div class="form-content">
                {% with messages = get_flashed_messages(with_categories=true) %}
                    {% if messages %}
                        {% for category, message in messages %}
                            <div class="notification notification-{{ category }}">{{ message }}</div>
                        {% endfor %}
                    {% endif %}
                {% endwith %}

                <form method="POST" action="{{ url_for('upload_video') }}" enctype="multipart/form-data" id="uploadForm">
                    <div class="form-layout">
                        <div class="input-group">
                            <label for="title" class="input-label">Content Title</label>
                            <input type="text" id="title" name="title" class="form-field" required>
                        </div>
                        <div class="input-group">
                            <label for="publisher" class="input-label">Publisher Name</label>
                            <input type="text" id="publisher" name="publisher" class="form-field" required>
                        </div>
                        <div class="input-group">
                            <label for="producer" class="input-label">Producer Name</label>
                            <input type="text" id="producer" name="producer" class="form-field" required>
                        </div>
                        <div class="input-group">
                            <label for="genre" class="input-label">Content Category</label>
                            <select id="genre" name="genre" class="form-dropdown" required>
                                <option value="">Choose Category</option>
                                <option value="Action">Action</option>
                                <option value="Comedy">Comedy</option>
                                <option value="Drama">Drama</option>
                                <option value="Horror">Horror</option>
                                <option value="Romance">Romance</option>
                                <option value="Sci-Fi">Science Fiction</option>
                                <option value="Documentary">Documentary</option>
                                <option value="Animation">Animation</option>
                                <option value="Thriller">Thriller</option>
                                <option value="Adventure">Adventure</option>
                            </select>
                        </div>
                        <div class="input-group full-width">
                            <label for="age_rating" class="input-label">Age Rating</label>
                            <select id="age_rating" name="age_rating" class="form-dropdown" required>
                                <option value="">Select Rating</option>
                                <option value="G">G - General Audiences</option>
                                <option value="PG">PG - Parental Guidance Suggested</option>
                                <option value="PG-13">PG-13 - Parents Strongly Cautioned</option>
                                <option value="R">R - Restricted (17+)</option>
                                <option value="NC-17">NC-17 - Adults Only</option>
                                <option value="18">18+ - Adult Content</option>
                            </select>
                        </div>
                    </div>

                    <div class="file-upload-area" onclick="document.getElementById('videoFile').click()">
                        <div class="upload-icon">📹</div>
                        <div class="upload-title">Choose Video File</div>
                        <div class="upload-description">Click here to select your video file for upload</div>
                    </div>

                    <input type="file" id="videoFile" name="video" accept="video/*" required>
                    <div class="file-info" id="fileInfo"></div>

                    <div class="progress-container" id="progressContainer">
                        <div class="progress-text">Uploading content...</div>
                        <div class="progress-bar-bg">
                            <div class="progress-bar" id="progressBar"></div>
                        </div>
                    </div>

                    <button type="submit" class="publish-button" id="publishBtn">Publish Content</button>
                </form>
            </div>
        </div>
    </div>

    <script>
        const videoFile = document.getElementById('videoFile');
        const fileUploadArea = document.querySelector('.file-upload-area');
        const fileInfo = document.getElementById('fileInfo');
        const uploadForm = document.getElementById('uploadForm');
        const progressContainer = document.getElementById('progressContainer');
        const progressBar = document.getElementById('progressBar');
        const publishBtn = document.getElementById('publishBtn');

        videoFile.addEventListener('change', handleFileSelect);

        function handleFileSelect(event) {
            const file = event.target.files[0];
            if (file) {
                fileInfo.style.display = 'block';
                fileInfo.innerHTML = `
                    <strong>Selected File:</strong> ${file.name}<br>
                    <strong>File Size:</strong> ${(file.size / 1024 / 1024).toFixed(2)} MB<br>
                    <strong>File Type:</strong> ${file.type}
                `;
                fileUploadArea.style.borderColor = '#8b4513';
                fileUploadArea.querySelector('.upload-title').textContent = 'Video Selected';
                fileUploadArea.querySelector('.upload-description').textContent = 'File ready for upload';
            }
        }

        // Drag and drop functionality
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            fileUploadArea.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        ['dragenter', 'dragover'].forEach(eventName => {
            fileUploadArea.addEventListener(eventName, highlight, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            fileUploadArea.addEventListener(eventName, unhighlight, false);
        });

        function highlight() {
            fileUploadArea.style.background = 'rgba(139, 69, 19, 0.1)';
        }

        function unhighlight() {
            fileUploadArea.style.background = 'rgba(139, 69, 19, 0.02)';
        }

        fileUploadArea.addEventListener('drop', handleDrop, false);

        function handleDrop(e) {
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                videoFile.files = files;
                handleFileSelect({ target: { files } });
            }
        }

        uploadForm.addEventListener('submit', function(e) {
            publishBtn.textContent = 'PUBLISHING...';
            publishBtn.disabled = true;
            progressContainer.style.display = 'block';

            let progress = 0;
            const interval = setInterval(() => {
                progress += Math.random() * 15;
                if (progress > 90) progress = 90;
                progressBar.style.width = progress + '%';
            }, 500);

            setTimeout(() => {
                clearInterval(interval);
                progressBar.style.width = '100%';
            }, 4000);
        });
    </script>
</body>
</html>
'''

CONSUMER_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StreamVibe - Content Library</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Georgia', serif;
            background: linear-gradient(to bottom, #f8f4f0 0%, #ffffff 100%);
            color: #3e2723;
            line-height: 1.6;
        }

        .main-header {
            background: white;
            box-shadow: 0 4px 20px rgba(139, 69, 19, 0.15);
            border-bottom: 3px solid #8b4513;
            padding: 1.5rem 0;
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .header-layout {
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 2rem;
            display: grid;
            grid-template-columns: auto 1fr auto;
            align-items: center;
            gap: 2rem;
        }

        .site-brand {
            font-size: 2.2rem;
            font-weight: bold;
            color: #8b4513;
            font-family: 'Times New Roman', serif;
        }

        .search-container {
            position: relative;
            max-width: 500px;
            width: 100%;
        }

        .search-input {
            width: 100%;
            padding: 1rem 1.5rem;
            padding-right: 3.5rem;
            border: 2px solid #e8e8e8;
            border-radius: 25px;
            font-size: 1rem;
            background: #f9f9f9;
            color: #3e2723;
            transition: all 0.3s ease;
        }

        .search-input:focus {
            outline: none;
            border-color: #8b4513;
            background: white;
            box-shadow: 0 0 0 3px rgba(139, 69, 19, 0.1);
        }

        .search-input::placeholder {
            color: #999;
        }

        .search-button {
            position: absolute;
            right: 5px;
            top: 50%;
            transform: translateY(-50%);
            background: #8b4513;
            color: white;
            border: none;
            padding: 0.7rem 1.2rem;
            border-radius: 20px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .search-button:hover {
            background: #a0522d;
        }

        .user-controls {
            display: flex;
            align-items: center;
            gap: 1.5rem;
        }

        .user-badge {
            padding: 0.6rem 1.2rem;
            background: rgba(139, 69, 19, 0.1);
            color: #8b4513;
            border: 2px solid #8b4513;
            border-radius: 20px;
            font-weight: 600;
        }

        .signout-link {
            padding: 0.8rem 1.5rem;
            background: #dc3545;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .signout-link:hover {
            background: #c82333;
            transform: translateY(-1px);
        }

        .content-library {
            max-width: 1400px;
            margin: 0 auto;
            padding: 3rem 2rem;
        }

        .library-title {
            font-size: 3rem;
            font-weight: 300;
            color: #5d4037;
            text-align: center;
            margin-bottom: 3rem;
            font-family: 'Times New Roman', serif;
        }

        .video-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 3rem;
        }

        .video-card {
            background: white;
            border-radius: 15px;
            overflow: hidden;
            box-shadow: 0 15px 40px rgba(139, 69, 19, 0.1);
            border: 1px solid rgba(139, 69, 19, 0.1);
            transition: all 0.3s ease;
        }

        .video-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 20px 60px rgba(139, 69, 19, 0.2);
        }

        .card-header {
            background: linear-gradient(135deg, #8b4513 0%, #a0522d 100%);
            color: white;
            padding: 1.5rem;
            font-weight: 600;
            font-size: 1.2rem;
        }

        .video-metadata {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 1rem;
            padding: 1.5rem;
            background: rgba(139, 69, 19, 0.02);
            border-bottom: 1px solid rgba(139, 69, 19, 0.1);
        }

        .metadata-item {
            font-size: 0.9rem;
        }

        .metadata-label {
            color: #8b4513;
            font-weight: 600;
            display: block;
            margin-bottom: 0.2rem;
            text-transform: uppercase;
            font-size: 0.8rem;
            letter-spacing: 0.5px;
        }

        .metadata-value {
            color: #5d4037;
        }

        .video-player {
            width: 100%;
            height: 300px;
            background: #000;
            border: none;
        }

        .interaction-panel {
            padding: 2rem;
            background: rgba(248, 244, 240, 0.5);
        }

        .rating-area {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid rgba(139, 69, 19, 0.2);
        }

        .star-rating {
            display: flex;
            gap: 0.3rem;
        }

        .star {
            font-size: 1.5rem;
            color: rgba(139, 69, 19, 0.3);
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .star:hover,
        .star.active {
            color: #8b4513;
            transform: scale(1.1);
        }

        .rating-info {
            color: #6d4c41;
            font-size: 0.9rem;
            font-weight: 500;
        }

        .comment-section textarea {
            width: 100%;
            padding: 1rem;
            border: 2px solid #e8e8e8;
            border-radius: 8px;
            background: #fafafa;
            color: #3e2723;
            font-family: inherit;
            font-size: 0.95rem;
            resize: vertical;
            min-height: 80px;
            margin-bottom: 1rem;
            transition: all 0.3s ease;
        }

        .comment-section textarea:focus {
            outline: none;
            border-color: #8b4513;
            background: white;
        }

        .comment-section textarea::placeholder {
            color: #999;
        }

        .comment-submit {
            background: #8b4513;
            color: white;
            border: none;
            padding: 0.7rem 1.5rem;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .comment-submit:hover {
            background: #a0522d;
            transform: translateY(-1px);
        }

        .comments-list {
            margin-top: 2rem;
            max-height: 300px;
            overflow-y: auto;
        }

        .comment {
            padding: 1.2rem 0;
            border-bottom: 1px solid rgba(139, 69, 19, 0.1);
        }

        .comment:last-child {
            border-bottom: none;
        }

        .comment-author {
            font-weight: 600;
            color: #8b4513;
            margin-bottom: 0.5rem;
        }

        .comment-text {
            color: #5d4037;
            margin-bottom: 0.8rem;
            line-height: 1.5;
        }

        .comment-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.8rem;
            color: #999;
        }

        .sentiment-label {
            padding: 0.2rem 0.6rem;
            border-radius: 10px;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
        }

        .sentiment-positive {
            background: rgba(139, 69, 19, 0.1);
            color: #8b4513;
        }

        .sentiment-negative {
            background: rgba(220, 53, 69, 0.1);
            color: #dc3545;
        }

        .sentiment-neutral {
            background: rgba(108, 117, 125, 0.1);
            color: #6c757d;
        }

        .empty-state {
            text-align: center;
            padding: 4rem 2rem;
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(139, 69, 19, 0.1);
            margin-top: 2rem;
        }

        .empty-state h3 {
            font-size: 1.8rem;
            color: #8b4513;
            margin-bottom: 1rem;
            font-weight: 400;
        }

        .empty-state p {
            color: #6d4c41;
            font-size: 1.1rem;
        }

        @media (max-width: 768px) {
            .header-layout {
                grid-template-columns: 1fr;
                gap: 1rem;
                text-align: center;
            }

            .content-library {
                padding: 2rem 1rem;
            }

            .library-title {
                font-size: 2.2rem;
            }

            .video-grid {
                grid-template-columns: 1fr;
                gap: 2rem;
            }

            .video-metadata {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="main-header">
        <div class="header-layout">
            <div class="site-brand">StreamVibe</div>
            <div class="search-container">
                <input type="text" class="search-input" id="searchInput" placeholder="Search for content...">
                <button class="search-button" onclick="searchContent()">Search</button>
            </div>
            <div class="user-controls">
                <span class="user-badge">{{ current_user.username }}</span>
                <a href="{{ url_for('logout') }}" class="signout-link">Sign Out</a>
            </div>
        </div>
    </div>

    <div class="content-library">
        <h1 class="library-title">Content Library</h1>

        <div class="video-grid" id="videoGrid">
            {% if videos %}
                {% for video in videos %}
                <div class="video-card">
                    <div class="card-header">{{ video[1] }}</div>

                    <div class="video-metadata">
                        <div class="metadata-item">
                            <span class="metadata-label">Publisher</span>
                            <span class="metadata-value">{{ video[2] }}</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Producer</span>
                            <span class="metadata-value">{{ video[3] }}</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Category</span>
                            <span class="metadata-value">{{ video[4] }}</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Rating</span>
                            <span class="metadata-value">{{ video[5] }}</span>
                        </div>
                    </div>

                    <video class="video-player" controls>
                        <source src="{{ video[6] }}" type="video/mp4">
                        Your browser does not support video playback.
                    </video>

                    <div class="interaction-panel">
                        <div class="rating-area">
                            <div class="star-rating" data-video-id="{{ video[0] }}">
                                {% set user_rating = user_ratings.get(video[0], 0) %}
                                {% for i in range(1, 6) %}
                                <span class="star {% if i <= user_rating %}active{% endif %}" data-rating="{{ i }}">★</span>
                                {% endfor %}
                            </div>
                            <div class="rating-info">
                                {% if video[7] %}
                                    Average Rating: {{ "%.1f"|format(video[7]) }}/5
                                {% else %}
                                    Not yet rated
                                {% endif %}
                            </div>
                        </div>

                        <div class="comment-section">
                            <textarea placeholder="Share your thoughts on this content..." data-video-id="{{ video[0] }}"></textarea>
                            <button class="comment-submit" onclick="addComment({{ video[0] }})">Post Comment</button>

                            <div class="comments-list">
                                {% if comments[video[0]] %}
                                    {% for comment in comments[video[0]] %}
                                    <div class="comment">
                                        <div class="comment-author">{{ comment.username }}</div>
                                        <div class="comment-text">{{ comment.comment }}</div>
                                        <div class="comment-meta">
                                            <span>{{ comment.created_at }}</span>
                                            <span class="sentiment-label sentiment-{{ comment.sentiment }}">
                                                {{ comment.sentiment }}
                                            </span>
                                        </div>
                                    </div>
                                    {% endfor %}
                                {% else %}
                                    <div class="comment">
                                        <div class="comment-text">No comments yet. Be the first to share your opinion!</div>
                                    </div>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="empty-state">
                    <h3>No Content Available</h3>
                    <p>Please check back soon for new video uploads from our creators.</p>
                </div>
            {% endif %}
        </div>
    </div>

    <script>
        // Rating system
        document.querySelectorAll('.star-rating').forEach(ratingGroup => {
            const stars = ratingGroup.querySelectorAll('.star');
            const videoId = ratingGroup.dataset.videoId;

            stars.forEach((star, index) => {
                star.addEventListener('click', () => {
                    const rating = index + 1;
                    
                    fetch('/rate-video', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            video_id: videoId,
                            rating: rating
                        })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            // Update star display
                            stars.forEach((s, i) => {
                                s.classList.toggle('active', i < rating);
                            });
                            
                            // Update average rating display
                            const ratingInfo = ratingGroup.parentElement.querySelector('.rating-info');
                            if (data.avg_rating) {
                                ratingInfo.textContent = `Average Rating: ${data.avg_rating.toFixed(1)}/5`;
                            }
                        }
                    })
                    .catch(error => console.error('Rating error:', error));
                });

                // Hover effects
                star.addEventListener('mouseenter', () => {
                    stars.forEach((s, i) => {
                        if (i <= index) {
                            s.style.color = '#8b4513';
                        } else {
                            s.style.color = 'rgba(139, 69, 19, 0.3)';
                        }
                    });
                });

                ratingGroup.addEventListener('mouseleave', () => {
                    stars.forEach(s => {
                        if (s.classList.contains('active')) {
                            s.style.color = '#8b4513';
                        } else {
                            s.style.color = 'rgba(139, 69, 19, 0.3)';
                        }
                    });
                });
            });
        });

        // Comment functionality
        function addComment(videoId) {
            const textarea = document.querySelector(`textarea[data-video-id="${videoId}"]`);
            const comment = textarea.value.trim();
            
            if (!comment) return;

            fetch('/add-comment', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    video_id: videoId,
                    comment: comment
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Add new comment to the list
                    const commentsList = textarea.closest('.comment-section').querySelector('.comments-list');
                    
                    const newComment = document.createElement('div');
                    newComment.className = 'comment';
                    newComment.innerHTML = `
                        <div class="comment-author">${data.comment.username}</div>
                        <div class="comment-text">${data.comment.comment}</div>
                        <div class="comment-meta">
                            <span>${data.comment.created_at}</span>
                            <span class="sentiment-label sentiment-${data.comment.sentiment}">
                                ${data.comment.sentiment}
                            </span>
                        </div>
                    `;
                    
                    commentsList.insertBefore(newComment, commentsList.firstChild);
                    textarea.value = '';
                }
            })
            .catch(error => console.error('Comment error:', error));
        }

        // Search functionality
        function searchContent() {
            const query = document.getElementById('searchInput').value.trim();
            const videoGrid = document.getElementById('videoGrid');
            
            if (!query) {
                location.reload();
                return;
            }

            fetch(`/search-videos?q=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(videos => {
                    displaySearchResults(videos);
                })
                .catch(error => console.error('Search error:', error));
        }

        function displaySearchResults(videos) {
            const videoGrid = document.getElementById('videoGrid');
            
            if (videos.length === 0) {
                videoGrid.innerHTML = `
                    <div class="empty-state">
                        <h3>No Results Found</h3>
                        <p>Try searching with different keywords or browse our full library.</p>
                    </div>
                `;
                return;
            }

            videoGrid.innerHTML = videos.map(video => `
                <div class="video-card">
                    <div class="card-header">${video.title}</div>

                    <div class="video-metadata">
                        <div class="metadata-item">
                            <span class="metadata-label">Publisher</span>
                            <span class="metadata-value">${video.publisher}</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Producer</span>
                            <span class="metadata-value">${video.producer}</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Category</span>
                            <span class="metadata-value">${video.category}</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Rating</span>
                            <span class="metadata-value">${video.age_rating}</span>
                        </div>
                    </div>

                    <video class="video-player" controls>
                        <source src="${video.video_url}" type="video/mp4">
                        Your browser does not support video playback.
                    </video>

                    <div class="interaction-panel">
                        <div class="rating-area">
                            <div class="star-rating" data-video-id="${video.id}">
                                ${[1,2,3,4,5].map(i => 
                                    `<span class="star ${i <= (video.user_rating || 0) ? 'active' : ''}" data-rating="${i}">★</span>`
                                ).join('')}
                            </div>
                            <div class="rating-display">
                                ${video.avg_rating ? `Average Rating: ${video.avg_rating.toFixed(1)}/5` : 'Not yet rated'}
                            </div>
                        </div>

                        <div class="comment-section">
                            <textarea placeholder="Share your thoughts on this content..." data-video-id="${video.id}"></textarea>
                            <button class="comment-submit" onclick="addComment(${video.id})">Post Comment</button>

                            <div class="comments-list">
                                ${video.comments.map(comment => `
                                    <div class="comment">
                                        <div class="comment-author">${comment.username}</div>
                                        <div class="comment-text">${comment.comment}</div>
                                        <div class="comment-meta">
                                            <span>${comment.created_at}</span>
                                            <span class="sentiment-label sentiment-${comment.sentiment}">
                                                ${comment.sentiment}
                                            </span>
                                        </div>
                                    </div>
                                `).join('') || '<div class="comment"><div class="comment-text">No comments yet. Be the first to share your opinion!</div></div>'}
                            </div>
                        </div>
                    </div>
                </div>
            `).join('');

            // Re-initialize event listeners for new content
            initializeRatingListeners();
        }

        function initializeRatingListeners() {
            document.querySelectorAll('.star-rating').forEach(ratingGroup => {
                const stars = ratingGroup.querySelectorAll('.star');
                const videoId = ratingGroup.dataset.videoId;

                stars.forEach((star, index) => {
                    star.addEventListener('click', () => {
                        const rating = index + 1;
                        
                        fetch('/rate-video', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({
                                video_id: videoId,
                                rating: rating
                            })
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                stars.forEach((s, i) => {
                                    s.classList.toggle('active', i < rating);
                                });
                                
                                const ratingInfo = ratingGroup.parentElement.querySelector('.rating-info');
                                if (data.avg_rating) {
                                    ratingInfo.textContent = `Average Rating: ${data.avg_rating.toFixed(1)}/5`;
                                }
                            }
                        })
                        .catch(error => console.error('Rating error:', error));
                    });
                });
            });
        }

        // Search on Enter key
        document.getElementById('searchInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                searchContent();
            }
        });
    </script>
</body>
</html>
'''
init_db()
if __name__ == '__main__':

    app.run(debug=True, host='0.0.0.0', port=5000)