
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import re
import traceback
import pymysql

pymysql.install_as_MySQLdb()

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Ganti dengan kunci rahasia yang lebih aman

# Konfigurasi database untuk XAMPP
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root:@localhost/scraper'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Model database
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    
    def __repr__(self):
        return f'<User {self.username}>'

class ChatGPTLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    link = db.Column(db.String(500), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    
    # Relasi ke user
    user = db.relationship('User', backref=db.backref('links', lazy=True))
    
    def __repr__(self):
        return f'<ChatGPTLink {self.link}>'

class ChatGPTConversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    link_id = db.Column(db.Integer, db.ForeignKey('chat_gpt_link.id'), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    
    # Relasi ke link
    link = db.relationship('ChatGPTLink', backref=db.backref('conversations', lazy=True))
    
    def __repr__(self):
        return f'<ChatGPTConversation {self.id}>'

class ChatGPTPreprocessing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    link_id = db.Column(db.Integer, db.ForeignKey('chat_gpt_link.id'), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    
    # Relasi ke link
    link = db.relationship('ChatGPTLink', backref=db.backref('preprocessing', lazy=True))
    
    def __repr__(self):
        return f'<ChatGPTPreprocessing {self.id}>'

# Fungsi untuk scrape link ChatGPT menggunakan Selenium
def scrape_chatgpt_conversation(link):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        print(f"Accessing link: {link}")
        driver.get(link)
        
        # Beri waktu untuk halaman memuat sepenuhnya
        wait = WebDriverWait(driver, 30)
        
        # Tangkap screenshot untuk debugging
        # debug_dir = 'debug_screenshots'
        # if not os.path.exists(debug_dir):
        #     os.makedirs(debug_dir)
        # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # driver.save_screenshot(f"{debug_dir}/screenshot_{timestamp}.png")
        
        # Tunggu sampai elemen artikel percakapan muncul
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "article[data-testid^='conversation-turn-']")))
        
        # Kumpulkan semua elemen artikel percakapan
        articles = driver.find_elements(By.CSS_SELECTOR, "article[data-testid^='conversation-turn-']")
        print(f"Found {len(articles)} conversation turns")
        
        # Simpan HTML untuk debugging
        # with open(f"{debug_dir}/page_content_{timestamp}.html", "w", encoding="utf-8") as f:
        #     f.write(driver.page_source)
        
        conversations = []
        current_prompt = None
        
        # Pendekatan 1: Proses artikel secara berurutan
        for i, article in enumerate(articles):
            try:
                # Cek apakah ini prompt pengguna atau respons asisten
                user_message = article.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='user']")
                assistant_message = article.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
                
                if user_message:
                    # Ini adalah prompt pengguna
                    try:
                        # Cari teks di dalam elemen dengan class yang mengandung whitespace-pre-wrap
                        prompt_text_element = user_message[0].find_element(By.CSS_SELECTOR, "div.whitespace-pre-wrap")
                        current_prompt = prompt_text_element.text
                        print(f"Found user prompt #{i+1}: {current_prompt[:50]}...")
                    except Exception as e:
                        print(f"Error extracting user prompt with whitespace-pre-wrap: {e}")
                        # Alternatif: ambil semua teks dari elemen user message
                        current_prompt = user_message[0].text
                        print(f"Using fallback for prompt #{i+1}: {current_prompt[:50]}...")
                
                elif assistant_message and current_prompt is not None:
                    # Ini adalah respons asisten
                    try:
                        # Cari teks dalam elemen dengan class markdown prose
                        response_text_element = assistant_message[0].find_element(By.CSS_SELECTOR, "div.markdown")
                        response_text = response_text_element.text
                        print(f"Found assistant response #{i+1}: {response_text[:50]}...")
                        
                        # Tambahkan ke daftar percakapan
                        conversations.append({
                            "prompt": current_prompt,
                            "response": response_text
                        })
                        
                        # Reset prompt untuk mencegah duplikasi jika ada kesalahan
                        current_prompt = None
                    except Exception as e:
                        print(f"Error extracting assistant response with markdown: {e}")
                        # Alternatif: ambil semua teks dari elemen assistant message
                        response_text = assistant_message[0].text
                        print(f"Using fallback for response #{i+1}: {response_text[:50]}...")
                        
                        if response_text:
                            conversations.append({
                                "prompt": current_prompt,
                                "response": response_text
                            })
                            current_prompt = None
            
            except Exception as e:
                print(f"Error processing article {i}: {e}")
                traceback.print_exc()
                continue
        
        # Jika pendekatan 1 gagal, coba pendekatan 2: Pasangkan secara manual
        if not conversations:
            print("Trying alternative approach for extracting conversations...")
            user_prompts = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='user']")
            assistant_responses = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
            
            print(f"Found {len(user_prompts)} user prompts and {len(assistant_responses)} assistant responses")
            
            # Pasangkan prompt dan respons
            for i in range(min(len(user_prompts), len(assistant_responses))):
                try:
                    # Ekstrak teks prompt
                    try:
                        prompt_element = user_prompts[i].find_element(By.CSS_SELECTOR, "div.whitespace-pre-wrap")
                        prompt = prompt_element.text
                    except:
                        prompt = user_prompts[i].text
                    
                    # Ekstrak teks respons
                    try:
                        response_element = assistant_responses[i].find_element(By.CSS_SELECTOR, "div.markdown")
                        response = response_element.text
                    except:
                        response = assistant_responses[i].text
                    
                    if prompt and response:
                        conversations.append({
                            "prompt": prompt,
                            "response": response
                        })
                        print(f"Paired conversation #{i+1} with alternative approach")
                except Exception as e:
                    print(f"Error pairing conversation {i}: {e}")
                    continue
        
        print(f"Extracted total of {len(conversations)} conversations")
        return conversations
    
    except Exception as e:
        print(f"Error during scraping: {e}")
        traceback.print_exc()
        return []
    
    finally:
        driver.quit()

def remove_emojis(text):
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"  # Emotikon wajah
        u"\U0001F300-\U0001F5FF"  # Simbol & Piktogram
        u"\U0001F680-\U0001F6FF"  # Transportasi & Simbol lainnya
        u"\U0001F700-\U0001F77F"  # Simbol Alkimia
        u"\U0001F780-\U0001F7FF"  # Simbol Geometrik Tambahan
        u"\U0001F800-\U0001F8FF"  # Simbol Panah Tambahan
        u"\U0001F900-\U0001F9FF"  # Emotikon Tangan
        u"\U0001FA00-\U0001FA6F"  # Simbol & Piktogram Tambahan
        u"\U0001FA70-\U0001FAFF"  # Simbol Olahraga & Aktivitas
        u"\U00002702-\U000027B0"  # Simbol lain-lain
        u"\U000024C2-\U0001F251" 
        "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)


def preprocess_text(text):
    # Remove emojis and convert to lowercase
    text = remove_emojis(text.lower())
    
    # Add line breaks after paragraphs
    # Match periods, question marks, or exclamation marks followed by a space or end of string
    text = re.sub(r'([.!?])\s+', r'\1\n\n', text)
    
    # Ensure proper spacing between paragraphs (remove extra line breaks)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('input_link'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Cek apakah username sudah ada
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username sudah digunakan.')
            return redirect(url_for('register'))
        
        # Buat user baru
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Registrasi berhasil! Silakan login.')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            print(f"Error during registration: {e}")
            flash('Terjadi kesalahan saat registrasi.')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Login berhasil!')
            return redirect(url_for('input_link'))
        else:
            flash('Username atau password salah.')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('Logout berhasil!')
    return redirect(url_for('login'))

@app.route('/input', methods=['GET', 'POST'])
def input_link():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        link = request.form['chatgpt_link']
        
        # Validasi link yang lebih fleksibel
        valid_domains = ['chatgpt.com/share/', 'chat.openai.com/share/']
        is_valid = any(domain in link for domain in valid_domains)
        
        if not is_valid:
            flash('Link tidak valid. Harap masukkan link share ChatGPT yang benar (contoh: https://chatgpt.com/share/... atau https://chat.openai.com/share/...).')
            return redirect(url_for('input_link'))
        
        # Simpan link ke database (Tabel chat_gpt_link)
        new_link = ChatGPTLink(link=link, user_id=session['user_id'])
        
        try:
            db.session.add(new_link)
            db.session.commit()
            
            # Redirect ke halaman scraping dengan ID link
            return redirect(url_for('scrape_result', link_id=new_link.id))
        except Exception as e:
            db.session.rollback()
            print(f"Error saving link: {e}")
            flash('Terjadi kesalahan saat menyimpan link.')
    
    return render_template('input.html', username=session.get('username'))

@app.route('/scrape/<int:link_id>')
def scrape_result(link_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Ambil link dari database
    link_data = ChatGPTLink.query.get_or_404(link_id)
    
    # Pastikan link milik user yang sedang login
    if link_data.user_id != session['user_id']:
        flash('Anda tidak memiliki akses ke link ini.')
        return redirect(url_for('input_link'))
    
    # Cek apakah sudah ada hasil scraping untuk link ini
    existing_conversations = ChatGPTConversation.query.filter_by(link_id=link_id).all()
    
    if not existing_conversations:
        try:
            print(f"Attempting to scrape: {link_data.link}")
            
            # Lakukan scraping jika belum ada hasil
            conversations = scrape_chatgpt_conversation(link_data.link)
            
            print(f"Scraping completed: {len(conversations)} conversations found")
            
            if conversations:
                for conv in conversations:
                    new_conversation = ChatGPTConversation(
                        link_id=link_id,
                        prompt=conv["prompt"],
                        response=conv["response"]
                    )
                    db.session.add(new_conversation)

                    conversation_preprocessing = ChatGPTPreprocessing(
                        link_id=link_id,
                        prompt=preprocess_text(conv["prompt"]),
                        response=preprocess_text(conv["response"])
                    )
                    db.session.add(conversation_preprocessing)
                
                try:
                    db.session.commit()
                    existing_conversations = ChatGPTConversation.query.filter_by(link_id=link_id).all()
                    print("Successfully saved conversations to database")
                    flash(f'Berhasil mengekstrak {len(conversations)} percakapan!')
                except Exception as e:
                    db.session.rollback()
                    print(f"Error saving to database: {e}")
                    traceback.print_exc()
                    flash('Terjadi kesalahan saat menyimpan hasil scraping.')
            else:
                flash('Tidak dapat melakukan scraping dari link tersebut. Pastikan link valid dan dapat diakses.')
                print("No conversations found during scraping")
        except Exception as e:
            print(f"Error in scrape_result route: {e}")
            traceback.print_exc()
            flash('Terjadi kesalahan saat melakukan scraping.')
    
    return render_template('scrape_result.html', 
                          link=link_data, 
                          conversations=existing_conversations,
                          username=session.get('username'))

@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Ambil semua link yang dimiliki user
    user_links = ChatGPTLink.query.filter_by(user_id=session['user_id']).order_by(ChatGPTLink.timestamp.desc()).all()
    
    # Kumpulkan data untuk ditampilkan
    history_data = []
    
    for link in user_links:
        conversations = ChatGPTConversation.query.filter_by(link_id=link.id).all()
        history_data.append({
            'link': link,
            'conversations': conversations
        })
    
    return render_template('history.html',
                          history_data=history_data,
                          username=session.get('username'))

@app.route('/preprocessing/<int:link_id>')
def preprocessing(link_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Ambil semua percakapan berdasarkan link_id
    conversations = ChatGPTPreprocessing.query.filter_by(link_id=link_id).all()
    
    if not conversations:
        flash('Tidak ada data untuk preprocessing.')
        return redirect(url_for('history'))

    # Lakukan preprocessing: ubah ke lowercase dan hapus emoticon
    preprocessed_data = [
        {
            "prompt": conv.prompt,
            "response": conv.response
        }
        for conv in conversations
    ]
    
    return render_template('preprocessing.html', preprocessed_data=preprocessed_data, link_id=link_id, username=session.get('username'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Buat tabel database jika belum ada
    app.run(debug=True)